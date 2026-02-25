# -*- coding: utf-8 -*-
"""
Google API 클라이언트 모듈

native generateContent 엔드포인트를 사용하며,
x-goog-api-key 헤더로 인증합니다.
"""

import json
import logging
import time
from typing import Optional, Dict, Any

import requests

from src.auth.key_rotator import KeyRotator


class GoogleApiClient:
    """
    Google Gemini native API 클라이언트

    /v1beta/models/{model}:generateContent 엔드포인트를 사용합니다.
    응답을 OpenAI 호환 형식으로 변환하여 반환합니다.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
    REQUEST_TIMEOUT = (50, 300)
    MAX_RETRIES = 10

    def __init__(self, key_rotator: KeyRotator):
        self.key_rotator = key_rotator
        self.provider_name = "Google"

    def _build_contents(self, messages: list) -> list:
        """OpenAI messages 형식을 Google contents 형식으로 변환합니다."""
        contents = []
        system_parts = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")

            # content가 리스트인 경우 (멀티모달)
            if isinstance(content, list):
                parts = []
                for part in content:
                    if part.get("type") == "text":
                        parts.append({"text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            # base64 인라인 이미지
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
                # system 메시지는 첫 user 메시지 앞에 합침
                system_parts.extend(parts)
            elif role == "user":
                if system_parts:
                    # system 내용을 첫 user 메시지에 prepend
                    merged = system_parts + parts
                    system_parts = []
                    contents.append({"role": "user", "parts": merged})
                else:
                    contents.append({"role": "user", "parts": parts})
            elif role == "assistant":
                contents.append({"role": "model", "parts": parts})

        return contents

    def _to_openai_response(self, google_resp: dict, model: str, stream: bool) -> dict:
        """Google API 응답을 OpenAI 호환 형식으로 변환합니다."""
        candidates = google_resp.get("candidates", [])
        usage = google_resp.get("usageMetadata", {})

        choices = []
        for i, candidate in enumerate(candidates):
            parts = candidate.get("content", {}).get("parts", [])
            # thoughtSignature 등 제외하고 text만 추출
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            finish_reason = candidate.get("finishReason", "stop").lower()
            if finish_reason == "stop":
                finish_reason = "stop"
            elif finish_reason == "max_tokens":
                finish_reason = "length"

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

    def post_request(
        self,
        model: str,
        messages: list,
        thinking_level: str = "minimal",
        stream: bool = False,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Google generateContent API를 호출하고 OpenAI 형식으로 변환된 응답을 반환합니다.

        Args:
            model: 모델명 (prefix 제외, 예: gemini-3-flash-preview)
            messages: OpenAI 형식의 메시지 리스트
            thinking_level: minimal / low / medium / high (기본값: minimal)
            stream: 스트리밍 여부 (현재 미지원, 항상 False)
            max_tokens: 최대 출력 토큰 수

        Returns:
            OpenAI 호환 응답 dict, 실패 시 None
        """
        url = f"{self.BASE_URL}/{model}:generateContent"
        contents = self._build_contents(messages)

        generation_config = {}
        if max_tokens:
            generation_config["maxOutputTokens"] = max_tokens

        THINKING_LEVEL_MODELS = ("gemini-3",)
        THINKING_BUDGET_MODELS = ("gemini-2.5",)

        if any(model.startswith(p) for p in THINKING_LEVEL_MODELS):
            generation_config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        elif any(model.startswith(p) for p in THINKING_BUDGET_MODELS):
            generation_config["thinkingConfig"] = {"thinkingBudget": -1}

        payload = {
            "contents": contents,
            "generationConfig": generation_config
        }

        for try_count in range(self.MAX_RETRIES):
            api_key = self.key_rotator.get_next_key()
            if not api_key:
                logging.error(f"[{self.provider_name}] API 키를 가져올 수 없습니다.")
                return None

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": api_key
            }

            masked_key = api_key[:8] + "..." + api_key[-4:]
            logging.info(f"[KeyRotator] [{self.provider_name}] API_KEY_USED - key_ending: {api_key[-8:]}, 재시도: {try_count + 1}/{self.MAX_RETRIES}")

            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.REQUEST_TIMEOUT
                )
                resp.raise_for_status()
                return self._to_openai_response(resp.json(), model, stream)

            except requests.exceptions.RequestException as e:
                response_body = ""
                if hasattr(e, "response") and e.response is not None:
                    response_body = e.response.text[:300]
                logging.error(
                    f"[{self.provider_name}] API 요청 실패 - URL: {url}, "
                    f"에러: {str(e)}, 키: {masked_key}, 응답: {response_body}, "
                    f"재시도: {try_count + 1}/{self.MAX_RETRIES}"
                )
                time.sleep(1)

        return None
