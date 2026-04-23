# -*- coding: utf-8 -*-
import json
import logging
import time
import uuid
from typing import Optional, Dict, Any, Generator, Union, List

import requests

from src.auth.key_rotator import KeyRotator


_SCHEMA_TYPE_MAP = {
    "string": "STRING",
    "number": "NUMBER",
    "integer": "INTEGER",
    "boolean": "BOOLEAN",
    "array": "ARRAY",
    "object": "OBJECT",
}

_UNSUPPORTED_CONSTRAINT_KEYS = {
    "minLength",
    "maxLength",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "pattern",
    "minItems",
    "maxItems",
    "format",
    "default",
    "examples",
}
_UNSUPPORTED_SCHEMA_KEYS = {
    "$schema",
    "$defs",
    "definitions",
    "$ref",
    "const",
    "additionalProperties",
    "patternProperties",
    "unevaluatedProperties",
    "dependentSchemas",
    "propertyNames",
    "title",
    "$id",
    "$comment",
}
_ALLOWED_SCHEMA_KEYS = {
    "type",
    "description",
    "enum",
    "items",
    "properties",
    "required",
    "nullable",
    "anyOf",
    "oneOf",
    "allOf",
}


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

    @staticmethod
    def _sanitize_schema_for_google(schema: Any) -> dict:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}

        # $ref가 있어도 sibling 정보(type, description 등)는 보존
        # $ref 자체는 _UNSUPPORTED_SCHEMA_KEYS에 의해 필터링됨

        working = dict(schema)
        if "const" in working and "enum" not in working:
            working["enum"] = [working["const"]]

        result: Dict[str, Any] = {}
        for key, value in working.items():
            if key in _UNSUPPORTED_CONSTRAINT_KEYS or key in _UNSUPPORTED_SCHEMA_KEYS:
                continue
            if key not in _ALLOWED_SCHEMA_KEYS:
                continue

            if key == "properties":
                if not isinstance(value, dict):
                    continue
                result["properties"] = {
                    prop_name: GoogleApiClient._sanitize_schema_for_google(prop_schema)
                    for prop_name, prop_schema in value.items()
                    if isinstance(prop_name, str)
                }
                continue

            if key == "items":
                if isinstance(value, dict):
                    result["items"] = GoogleApiClient._sanitize_schema_for_google(value)
                continue

            if key in ("anyOf", "oneOf", "allOf"):
                if isinstance(value, list):
                    variants = [
                        GoogleApiClient._sanitize_schema_for_google(item)
                        for item in value if isinstance(item, dict)
                    ]
                    if variants:
                        result[key] = variants
                continue

            if key == "required":
                if isinstance(value, list):
                    result["required"] = [item for item in value if isinstance(item, str)]
                continue

            if key == "enum":
                if isinstance(value, list):
                    result["enum"] = [item for item in value if isinstance(item, (str, int, float, bool))]
                continue

            result[key] = value

        if not result:
            return {"type": "object", "properties": {}}

        if "type" not in result:
            if "properties" in result:
                result["type"] = "object"
            elif "items" in result:
                result["type"] = "array"

        if result.get("type") == "object" and "properties" not in result:
            result["properties"] = {}

        return result

    @staticmethod
    def _convert_schema_types(schema: Any) -> Any:
        if not isinstance(schema, dict):
            return schema

        result: Dict[str, Any] = {}
        for key, value in schema.items():
            if key == "type" and isinstance(value, str):
                result[key] = _SCHEMA_TYPE_MAP.get(value, value.upper())
            elif isinstance(value, dict):
                result[key] = GoogleApiClient._convert_schema_types(value)
            elif isinstance(value, list):
                result[key] = [
                    GoogleApiClient._convert_schema_types(item)
                    if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    @staticmethod
    def _convert_tools(tools: Optional[list]) -> list:
        declarations = []
        for tool in tools or []:
            if tool.get("type") != "function":
                continue
            func = tool.get("function", {})
            name = func.get("name")
            if not name:
                continue
            declaration: Dict[str, Any] = {"name": name}
            if func.get("description"):
                declaration["description"] = func["description"]
            parameters = func.get("parameters")
            if parameters:
                cleaned_parameters = GoogleApiClient._sanitize_schema_for_google(parameters)
                declaration["parameters"] = GoogleApiClient._convert_schema_types(cleaned_parameters)
            declarations.append(declaration)

        if not declarations:
            return []
        return [{"functionDeclarations": declarations}]

    @staticmethod
    def _convert_tool_choice(tool_choice: Any) -> Optional[dict]:
        if tool_choice is None:
            return None

        if isinstance(tool_choice, str):
            mode_map = {
                "auto": "AUTO",
                "none": "NONE",
                "required": "ANY",
            }
            mode = mode_map.get(tool_choice)
            if mode:
                return {"functionCallingConfig": {"mode": mode}}
            return None

        if isinstance(tool_choice, dict):
            func_name = tool_choice.get("function", {}).get("name")
            if func_name:
                return {
                    "functionCallingConfig": {
                        "mode": "ANY",
                        "allowedFunctionNames": [func_name],
                    }
                }
        return None

    def _build_contents(self, messages: list) -> list:
        contents = []
        system_parts = []
        tool_call_id_to_name: Dict[str, str] = {}

        i = 0
        while i < len(messages):
            msg = messages[i]
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
                parts = [{"text": content if content is not None else ""}]

            if role == "system":
                system_parts.extend(parts)
                i += 1
            elif role == "user":
                if system_parts:
                    merged = system_parts + parts
                    system_parts = []
                    contents.append({"role": "user", "parts": merged})
                else:
                    contents.append({"role": "user", "parts": parts})
                i += 1
            elif role == "assistant":
                assistant_parts = list(parts)
                for tc in msg.get("tool_calls", []):
                    if tc.get("type") != "function":
                        continue
                    func = tc.get("function", {})
                    tc_id = str(tc.get("id", ""))
                    if tc_id:
                        tool_call_id_to_name[tc_id] = str(func.get("name", ""))
                    args_raw = func.get("arguments", "{}")
                    try:
                        args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                    except json.JSONDecodeError:
                        args = {}
                    if not isinstance(args, dict):
                        args = {"input": args}
                    assistant_parts.append({
                        "functionCall": {
                            "name": str(func.get("name", "")),
                            "args": args
                        }
                    })
                contents.append({"role": "model", "parts": assistant_parts})
                i += 1
            elif role == "tool":
                function_parts = []
                while i < len(messages) and messages[i].get("role") == "tool":
                    tool_msg = messages[i]
                    tool_call_id = str(tool_msg.get("tool_call_id", ""))
                    function_name = (
                        tool_msg.get("name")
                        or tool_call_id_to_name.get(tool_call_id, "unknown")
                    )
                    tool_content = tool_msg.get("content", "")
                    try:
                        response_obj = json.loads(tool_content) if isinstance(tool_content, str) else tool_content
                    except (json.JSONDecodeError, TypeError):
                        response_obj = {"result": tool_content}
                    if not isinstance(response_obj, dict):
                        response_obj = {"result": response_obj}
                    function_parts.append({
                        "functionResponse": {
                            "name": str(function_name),
                            "response": response_obj
                        }
                    })
                    i += 1
                if function_parts:
                    contents.append({"role": "function", "parts": function_parts})
            else:
                i += 1

        return contents

    def _build_generation_config(
        self,
        model: str,
        thinking_level: str,
        max_tokens: Optional[int],
        tools_present: bool = False,
    ) -> dict:
        config = {"temperature": self.GEMINI_TEMPERATURE}

        if max_tokens:
            config["maxOutputTokens"] = max_tokens

        if any(model.startswith(p) for p in self.THINKING_LEVEL_MODELS):
            config["thinkingConfig"] = {"thinkingLevel": thinking_level}
        elif any(model.startswith(p) for p in self.THINKING_BUDGET_MODELS):
            config["thinkingConfig"] = {"thinkingBudget": 0 if tools_present else -1}

        return config

    @staticmethod
    def _encode_tool_call_id(part: dict) -> str:
        function_call = part.get("functionCall", {})
        function_name = str(function_call.get("name", "tool"))
        return f"call_{function_name}_{uuid.uuid4().hex[:12]}"

    def _to_openai_response(self, google_resp: dict, model: str) -> dict:
        candidates = google_resp.get("candidates", [])
        usage = google_resp.get("usageMetadata", {})
        logging.info(
            "[Google] non-stream response summary: model=%s candidates=%s usage=%s",
            model,
            len(candidates),
            usage,
        )

        choices = []
        for i, candidate in enumerate(candidates):
            parts = candidate.get("content", {}).get("parts", [])
            logging.info(
                "[Google] candidate[%s] finishReason=%s parts=%s",
                i,
                candidate.get("finishReason"),
                json.dumps(parts, ensure_ascii=False)[:1000],
            )
            text = "".join(p.get("text", "") for p in parts if "text" in p)
            tool_calls = []
            for part in parts:
                if "functionCall" not in part:
                    continue
                function_call = part["functionCall"]
                tool_calls.append({
                    "id": self._encode_tool_call_id(part),
                    "type": "function",
                    "function": {
                        "name": function_call.get("name", ""),
                        "arguments": json.dumps(function_call.get("args", {}), ensure_ascii=False),
                    },
                })

            finish_reason_raw = candidate.get("finishReason", "stop").lower()
            if tool_calls:
                finish_reason = "tool_calls"
            elif finish_reason_raw == "max_tokens":
                finish_reason = "length"
            else:
                finish_reason = "stop"

            message: Dict[str, Any] = {"role": "assistant", "content": text}
            if tool_calls:
                message["tool_calls"] = tool_calls

            choices.append({
                "index": i,
                "message": message,
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
        logging.info("[Google] stream response started: model=%s", model)
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
            logging.info(
                "[Google] stream chunk finishReason=%s parts=%s",
                candidate.get("finishReason"),
                json.dumps(parts, ensure_ascii=False)[:1000],
            )
            finish_reason_raw = candidate.get("finishReason", "")
            finish_reason = None
            if finish_reason_raw:
                normalized_finish = finish_reason_raw.lower()
                finish_reason = "length" if normalized_finish == "max_tokens" else "stop"

            emitted = False
            emitted_tool_call = False
            for part in parts:
                if "text" in part and part.get("text"):
                    openai_chunk = {
                        "id": "google-stream",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {"role": "assistant", "content": part.get("text", "")},
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(openai_chunk, ensure_ascii=False)}\n\n"
                    emitted = True
                elif "functionCall" in part:
                    emitted_tool_call = True
                    function_call = part["functionCall"]
                    tool_chunk = {
                        "id": "google-stream",
                        "object": "chat.completion.chunk",
                        "created": 0,
                        "model": model,
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "tool_calls": [{
                                    "index": 0,
                                    "id": self._encode_tool_call_id(part),
                                    "type": "function",
                                    "function": {
                                        "name": function_call.get("name", ""),
                                        "arguments": json.dumps(function_call.get("args", {}), ensure_ascii=False)
                                    }
                                }]
                            },
                            "finish_reason": None
                        }]
                    }
                    yield f"data: {json.dumps(tool_chunk, ensure_ascii=False)}\n\n"
                    emitted = True

            if emitted_tool_call:
                finish_reason = "tool_calls"

            if finish_reason and emitted:
                final_chunk = {
                    "id": "google-stream",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [{
                        "index": 0,
                        "delta": {},
                        "finish_reason": finish_reason
                    }]
                }
                yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"

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
        tools: Optional[list] = None,
        tool_choice: Any = None,
        **kwargs
    ) -> Optional[Union[Dict[str, Any], Generator]]:
        contents = self._build_contents(messages)
        generation_config = self._build_generation_config(
            model,
            thinking_level,
            max_tokens,
            tools_present=bool(tools),
        )

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config
        }

        gemini_tools = self._convert_tools(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools
        tool_config = self._convert_tool_choice(tool_choice)
        if tool_config:
            payload["toolConfig"] = tool_config

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
