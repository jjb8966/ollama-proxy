# -*- coding: utf-8 -*-
import json
import logging
import time
from typing import Optional, Dict, Any, Generator, Union

import requests

from src.auth.key_rotator import KeyRotator


class GoogleApiClient:

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    REQUEST_TIMEOUT = (50, 300)
    MAX_RETRIES = 10

    THINKING_LEVEL_MODELS = ("gemini-3",)
    THINKING_BUDGET_MODELS = ("gemini-2.5",)
    GEMINI_TEMPERATURE = 1.0

    def __init__(self, key_rotator: KeyRotator):
        self.key_rotator = key_rotator
        self.provider_name = "Google"

    def _build_contents(self, messages: list) -> list:
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime_type = url.split(";")[0].replace("data:", "")
                            b64_data = url.split(",")[1]
                            parts.append({
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64_data
                                }
                            })
            else:
                parts = [{"text": content}]

            if role == "system":
                system_parts.extend(parts)
            elif role == "user":
                if system_parts:
                    merged = system_parts + parts
                    system_parts = []
                    contents.append({"role": "user", "parts": merged})
                else:
                    contents.append({"role": "user", "parts": parts})
            elif role == "assistant":
                contents.append({"role": "model", "parts": parts})

        return contents

    def _build_generation_config(self, model: str, thinking_level: str, max_tokens: Optional[int]) -> dict:
        config = {"temperature": self.GEMINI_TEMPERATURE}

        if max_tokens:
            config["maxOutputTokens"] = max_tokens

        if any(model.startswith(p) for p in self.THINKING_LEVEL_MODELS):
            config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        elif any(model.startswith(p) for p in self.THINKING_BUDGET_MODELS):
            config["thinkingConfig"] = {"thinkingBudget": -1}

        return config

    def _to_openai_response(self, google_resp: dict, model: str) -> dict:
        candidates = google_resp.get("candidates", [])
        usage = google_resp.get("usageMetadata", {})

        choices = []
        for i, candidate in enumerate(candidates):
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            finish_reason_raw = candidate.get("finishReason", "stop").lower()
            finish_reason = "length" if finish_reason_raw == "max_tokens" else "stop"

            choices.append({
                "index": i,
                "message": {"role": "assistant", "content": text},
                "finish_reason": finish_reason
            })

        return {
            "id": google_resp.get("responseId", "google-native"),
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": choices,
            "usage": {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0)
            }
        }

    def _stream_as_openai_sse(self, resp: requests.Response, model: str) -> Generator[str, None, None]:
        for line in resp.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8").strip()
            if not decoded.startswith("data:"):
                continue

            json_str = decoded[len("data:"):].strip()
            if not json_str:
                continue

            try:
                chunk = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            candidates = chunk.get("candidates", [])
            if not candidates:
                continue

            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            finish_reason_raw = candidate.get("finishReason", "")
            finish_reason = None
            if finish_reason_raw:
                finish_reason = "length" if finish_reason_raw.lower() == "max_tokens" else "stop"

            openai_chunk = {
                "id": "google-stream",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"role": "assistant", "content": text},
                    "finish_reason": finish_reason
                }]
            }
            yield f"data: {json.dumps(openai_chunk)}\n\n"

        yield "data: [DONE]\n\n"

    def _make_request(self, url: str, payload: dict, stream: bool = False) -> Optional[requests.Response]:
        for try_count in range(self.MAX_RETRIES):
            api_key = self.key_rotator.get_next_key()
            if not api_key:
                logging.error(f"[{self.provider_name}] API 키를 가져올 수 없습니다.")
                return None

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            }

            logging.info(
                f"[KeyRotator] [{self.provider_name}] API_KEY_USED - "
                f"key_ending: {api_key[-8:]}, 시도: {try_count + 1}/{self.MAX_RETRIES}"
            )

            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=stream,
                    timeout=self.REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                return resp

            except requests.exceptions.RequestException as e:
                response_body = ""
                if hasattr(e, "response") and e.response is not None:
                    response_body = e.response.text[:300]
                masked_key = api_key[:8] + "..." + api_key[-4:]
                logging.error(
                    f"[{self.provider_name}] API 요청 실패 - URL: {url}, "
                    f"에러: {str(e)}, 키: {masked_key}, 응답: {response_body}, "
                    f"시도: {try_count + 1}/{self.MAX_RETRIES}"
                )
                time.sleep(1)

        return None

    def post_request(
        self,
        model: str,
        messages: list,
        thinking_level: str = "minimal",
        stream: bool = False,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Optional[Union[Dict[str, Any], Generator]]:
        contents = self._build_contents(messages)
        generation_config = self._build_generation_config(model, thinking_level, max_tokens)

        payload = {
            "contents": contents,
            "generationConfig": generation_config
        }

        if stream:
            url = f"{self.BASE_URL}/{model}:streamGenerateContent?alt=sse"
            resp = self._make_request(url, payload, stream=True)
            if resp is None:
                return None
            return self._stream_as_openai_sse(resp, model)

        url = f"{self.BASE_URL}/{model}:generateContent"
        resp = self._make_request(url, payload, stream=False)
        if resp is None:
            return None
        return self._to_openai_response(resp.json(), model)
