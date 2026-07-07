# -*- coding: utf-8 -*-
"""
채팅 요청 핸들러 모듈

클라이언트의 채팅 요청을 처리하고 적절한 API 제공업체로 라우팅합니다.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional

import requests

from src.core.errors import ProxyRequestError, ErrorHandler
from src.providers.provider_config import PROVIDER_CONFIG, parse_provider_model
from src.providers.standard import StandardApiClient
from src.utils.message_compaction import build_compacted_request
from src.utils.opencode_anthropic import (
    AnthropicMessagePassthrough,
    AnthropicSsePassthrough,
    anthropic_response_to_openai,
    build_anthropic_payload,
    iter_utf8_response_lines,
    read_utf8_response_json,
    stream_anthropic_sse_to_openai,
    uses_opencode_anthropic_messages,
)


# Claude Code tool bridge: compact system prompt instead of full tools payload
CURSOR_BRIDGE_PROVIDERS = frozenset({"ccs"})


class ChatHandler:
    """
    채팅 요청 핸들러

    모델 prefix에 따라 적절한 API 제공업체로 요청을 라우팅합니다.
    이미지 처리, 메시지 정규화 등의 전처리도 수행합니다.
    """

    REMOVED_ANTIGRAVITY_MODELS = {
        "claude-opus-4-6-thinking",
        "claude-sonnet-4-6",
        "gemini-3-flash",
        "gemini-3.1-pro-high",
        "gemini-3.1-pro-low",
        "gcli-gemini-3.1-pro-preview",
        "gcli-gemini-3.1-pro-preview-customtools",
    }

    AUTO_COMPACTION_ENABLED = (
        __import__("os").environ.get("ENABLE_AUTO_COMPACTION", "true").lower() != "false"
    )
    MAX_COMPACTION_ATTEMPTS = max(
        1, int(__import__("os").environ.get("MAX_COMPACTION_ATTEMPTS", "5"))
    )

    PROVIDER_CONFIG = PROVIDER_CONFIG

    def __init__(self, api_config):
        """
        Args:
            api_config: ApiConfig 인스턴스 (각 제공업체의 rotator 포함)
        """
        self.api_config = api_config

        # 각 제공업체별 클라이언트 생성
        self.antigravity_client = StandardApiClient(api_config.antigravity_rotator)
        self.cli_proxy_api_client = StandardApiClient(api_config.cli_proxy_api_rotator)
        self.cli_proxy_api_plus_client = StandardApiClient(api_config.cli_proxy_api_plus_rotator)
        self.ccs_client = StandardApiClient(api_config.ccs_rotator)
        self.opencode_client = StandardApiClient(api_config.opencode_rotator)

    @staticmethod
    def _is_context_overflow_result(result: Any) -> bool:
        if isinstance(result, ProxyRequestError):
            if result.error_code == "context_length_exceeded":
                return True
            return ErrorHandler.is_context_overflow_message(result.message)

        if isinstance(result, dict):
            choices = result.get("choices")
            if not isinstance(choices, list) or not choices:
                return False
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                return False
            message = first_choice.get("message", {})
            if not isinstance(message, dict):
                return False
            content = message.get("content", "")
            if not isinstance(content, str):
                return False
            return (
                ErrorHandler.is_context_overflow_message(content)
                or "[Context Window Exceeded]" in content
            )

        return False

    def _maybe_retry_after_context_overflow(
        self,
        req: Dict[str, Any],
        result: Any,
    ) -> Any:
        if not self.AUTO_COMPACTION_ENABLED:
            return result
        if not self._is_context_overflow_result(result):
            return result

        round_index = int(req.get("_compaction_round", 0))
        if round_index >= self.MAX_COMPACTION_ATTEMPTS:
            logging.warning(
                "[AutoCompaction] 최대 재시도 횟수 도달 | model=%s | attempts=%s",
                req.get("model"),
                round_index,
            )
            return result

        compacted_req = build_compacted_request(req, round_index)
        if compacted_req is None:
            logging.warning(
                "[AutoCompaction] 더 이상 compact할 수 없음 | model=%s | round=%s",
                req.get("model"),
                round_index,
            )
            return result

        logging.warning(
            "[AutoCompaction] context overflow 후 재시도 | model=%s | round=%s | messages=%s→%s",
            req.get("model"),
            round_index + 1,
            len(req.get("messages", [])),
            len(compacted_req.get("messages", [])),
        )
        return self.handle_chat_request(compacted_req)

    def _parse_model(self, requested_model: str) -> tuple:
        """
        모델 문자열에서 제공업체와 모델명을 추출합니다.

        Args:
            requested_model: "provider:model_name" 형식의 문자열

        Returns:
            (제공업체, 모델명, base_url) 튜플
        """
        return parse_provider_model(requested_model)

    def _get_client(self, provider: str):
        """제공업체에 해당하는 API 클라이언트를 반환합니다."""
        if provider not in self.PROVIDER_CONFIG:
            raise ValueError(f"지원되지 않는 제공업체: {provider}")

        client_attr = self.PROVIDER_CONFIG[provider]['client_attr']
        return getattr(self, client_attr)

    def _handle_opencode_anthropic_messages_request(
        self,
        *,
        base_url: str,
        model: str,
        requested_model: str,
        messages: List[Dict[str, Any]],
        stream: bool,
        max_tokens: Optional[int],
        tools: Any = None,
        tool_choice: Any = None,
        anthropic_passthrough: bool = False,
    ):
        payload = build_anthropic_payload(
            model=model,
            messages=messages,
            stream=stream,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
        )
        endpoint = f"{base_url}/messages"
        headers = {"Content-Type": "application/json"}
        client = self.opencode_client
        api_key = client._get_api_key()
        if not api_key:
            logging.error("[OpenCode] Anthropic Messages API 키를 가져올 수 없습니다.")
            return None
        headers["x-api-key"] = api_key

        resp = client.post_request(
            url=endpoint,
            payload=payload,
            headers=headers,
            stream=stream,
        )
        if resp is None or isinstance(resp, ProxyRequestError):
            return resp

        if stream:
            if anthropic_passthrough:
                return AnthropicSsePassthrough(resp)

            def generate():
                try:
                    for chunk in stream_anthropic_sse_to_openai(
                        iter_utf8_response_lines(resp),
                        requested_model,
                    ):
                        yield chunk
                finally:
                    resp.close()

            return generate()

        data = resp if isinstance(resp, dict) else read_utf8_response_json(resp)
        if anthropic_passthrough:
            return AnthropicMessagePassthrough(data)
        return anthropic_response_to_openai(data, requested_model)

    def _validate_provider_model(
        self,
        provider: Optional[str],
        model: str,
        requested_model: str
    ) -> Optional[ProxyRequestError]:
        """제공업체별 비활성화 모델을 차단합니다."""
        if provider != 'antigravity':
            return None
        if model not in self.REMOVED_ANTIGRAVITY_MODELS:
            return None
        return ProxyRequestError(
            model=requested_model,
            message=f"Model is no longer supported: {requested_model}",
            status_code=400,
            error_type="invalid_request_error"
        )

    def _process_image_content(self, messages: List[Dict]) -> None:
        """
        메시지 내 이미지 데이터를 OpenAI 형식으로 변환합니다.

        Cline의 이미지 요청 형식을 OpenAI Vision API 형식으로 변환합니다.
        원본 messages 리스트를 직접 수정합니다.
        """
        if not messages:
            return

        for message in messages:
            if message['role'] != 'user':
                continue

            content = message.get('content', '')
            if not isinstance(content, str) or 'data:image' not in content:
                continue

            # 이미지 데이터 분리
            try:
                split1 = content.split('data:image')
                split2 = split1[1].split('<environment_details>')

                text_data = split1[0] + split2[1]
                image_data = 'data:image' + split2[0]

                # OpenAI Vision API 형식으로 변환
                message['content'] = [
                    {'type': 'text', 'text': text_data},
                    {'type': 'image_url', 'image_url': {'url': image_data}}
                ]
            except (IndexError, KeyError) as e:
                logging.warning(f"이미지 처리 실패: {e}")

    @staticmethod
    def _escape_cursor_xml(text: str) -> str:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    @classmethod
    def _sanitize_cursor_tool_call_id(cls, raw_id: Any) -> str:
        candidate = str(raw_id or "").strip().split("\n", maxsplit=1)[0]
        if not candidate:
            return ""
        if candidate.startswith("call_"):
            candidate = f"toolu_{candidate[5:]}"
        if re.fullmatch(r"[a-zA-Z0-9_-]+", candidate):
            return candidate
        sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", candidate)
        return sanitized if sanitized else ""

    @classmethod
    def _build_cursor_tool_result_block(
        cls, tool_name: str, tool_call_id: str, result_text: str
    ) -> str:
        clean_result = cls._escape_cursor_xml(result_text)
        return "\n".join(
            [
                "<tool_result>",
                f"<tool_name>{cls._escape_cursor_xml(tool_name or 'tool')}</tool_name>",
                f"<tool_call_id>{cls._escape_cursor_xml(tool_call_id)}</tool_call_id>",
                f"<result>{clean_result}</result>",
                "</tool_result>",
            ]
        )

    @staticmethod
    def _extract_openai_function_tool(tool: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(tool, dict):
            return None
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            return tool["function"]
        if isinstance(tool.get("name"), str):
            return tool
        return None

    @classmethod
    def _build_compact_tools_system_text(cls, tools: Any) -> Optional[str]:
        """cursor-api-proxy toolsToSystemText 대신 짧은 도구 목록을 만듭니다 (E2BIG 방지)."""
        if not isinstance(tools, list) or not tools:
            return None

        lines = [
            "Claude Code tool bridge instructions:",
            "- Emit tool calls for Claude Code to execute. Claude Code runs the tools.",
            "- Ignore Cursor CLI Ask/Agent mode. Never tell the user to switch modes.",
            "- Use WebSearch for general web searches or recent information requests.",
            "- Use WebFetch when a concrete HTTP(S) URL is available in the conversation.",
            "- Never claim WebSearch, WebFetch, Bash, Read, Grep, Task, or Glob are unavailable if listed below.",
            "- Use Task to spawn Claude Code subagents for parallel exploration or delegated work.",
            "- To call a tool, reply with ONLY one JSON object: "
            '{"name":"ToolName","arguments":{...}}',
            "- Do not answer from memory when a WebFetch url is available in the conversation.",
            "",
            "Available tools (respond with a JSON object to call one):",
            "",
        ]
        for tool in tools:
            function_info = cls._extract_openai_function_tool(tool)
            if not function_info:
                continue
            name = str(function_info.get("name", "")).strip()
            if not name:
                continue
            description = str(function_info.get("description", "")).strip()
            if len(description) > 120:
                description = f"{description[:117]}..."

            schema = function_info.get("parameters", {})
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            if not isinstance(properties, dict):
                properties = {}
            required = schema.get("required", []) if isinstance(schema, dict) else []
            if not isinstance(required, (list, tuple, set)):
                required = []
            required_names = {item for item in required if isinstance(item, str)}

            param_parts: List[str] = []
            for prop_name in properties:
                marker = "*" if prop_name in required_names else ""
                param_parts.append(f"{prop_name}{marker}")
            params_display = ", ".join(param_parts)

            if params_display:
                lines.append(f"Function: {name}({params_display})")
            else:
                lines.append(f"Function: {name}")
            if description:
                lines.append(f"Description: {description}")
            lines.append("")

        if len(lines) <= 2:
            return None
        return "\n".join(lines).strip()

    @classmethod
    def _inject_compact_tools_for_cursor(
        cls, messages: List[Dict[str, Any]], tools: Any
    ) -> List[Dict[str, Any]]:
        tools_text = cls._build_compact_tools_system_text(tools)
        if not tools_text:
            return messages
        return [{"role": "system", "content": tools_text}, *messages]

    @classmethod
    def _extract_openai_message_text(cls, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""
        parts: List[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)

    @classmethod
    def _convert_messages_for_cursor_provider(
        cls, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """ccs cursor-translator와 동일한 tool/system 메시지 평탄화."""
        tool_call_meta: Dict[str, str] = {}
        for message_index, message in enumerate(messages):
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            for tool_call_index, tool_call in enumerate(tool_calls):
                if not isinstance(tool_call, dict):
                    continue
                tool_call_id = cls._sanitize_cursor_tool_call_id(tool_call.get("id"))
                if not tool_call_id:
                    tool_call_id = (
                        f"toolu_ollama_fallback_{message_index}_{tool_call_index}"
                    )
                function_info = tool_call.get("function", {})
                tool_name = (
                    str(function_info.get("name", "")).strip()
                    if isinstance(function_info, dict)
                    else ""
                ) or "tool"
                tool_call_meta[tool_call_id] = tool_name

        converted: List[Dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role", ""))
            if role == "system":
                system_text = cls._extract_openai_message_text(message.get("content"))
                if not system_text:
                    continue
                if system_text.startswith("Claude Code tool bridge instructions:"):
                    converted.append({"role": "system", "content": system_text})
                else:
                    converted.append(
                        {
                            "role": "user",
                            "content": f"[System Instructions]\n{system_text}",
                        }
                    )
                continue

            if role == "tool":
                tool_call_id = cls._sanitize_cursor_tool_call_id(
                    message.get("tool_call_id")
                )
                if not tool_call_id:
                    continue
                tool_name = (
                    str(message.get("name", "")).strip()
                    or tool_call_meta.get(tool_call_id, "tool")
                )
                converted.append(
                    {
                        "role": "user",
                        "content": cls._build_cursor_tool_result_block(
                            tool_name,
                            tool_call_id,
                            cls._extract_openai_message_text(message.get("content")),
                        ),
                    }
                )
                continue

            if role == "assistant":
                assistant_text = cls._extract_openai_message_text(message.get("content"))
                tool_calls = message.get("tool_calls")
                tool_call_lines: List[str] = []
                if isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        function_info = tool_call.get("function", {})
                        if not isinstance(function_info, dict):
                            function_info = {}
                        tool_call_lines.append(
                            "[tool_use {name} {args}]".format(
                                name=function_info.get("name", "tool"),
                                args=function_info.get("arguments", "{}"),
                            )
                        )
                merged_content = "\n".join(
                    part for part in [assistant_text, *tool_call_lines] if part
                )
                assistant_message: Dict[str, Any] = {
                    "role": "assistant",
                    "content": merged_content,
                }
                if isinstance(tool_calls, list) and tool_calls:
                    assistant_message["tool_calls"] = tool_calls
                if merged_content or assistant_message.get("tool_calls"):
                    converted.append(assistant_message)
                continue

            converted.append(message)

        return converted

    def _normalize_ollama_cloud_image_content(self, messages: List[Dict]) -> None:
        """ollama-cloud 업스트림 호환 형식으로 image_url 블록을 정규화합니다."""
        if not messages:
            return

        for message in messages:
            if message.get('role') != 'user':
                continue

            content = message.get('content')
            if not isinstance(content, list):
                continue

            normalized_parts: List[Dict[str, Any]] = []
            changed = False
            for part in content:
                if not isinstance(part, dict):
                    normalized_parts.append(part)
                    continue

                if part.get('type') != 'image_url':
                    normalized_parts.append(part)
                    continue

                image_url = part.get('image_url')
                if not isinstance(image_url, dict):
                    normalized_parts.append(part)
                    continue

                url = image_url.get('url')
                if not isinstance(url, str) or not url:
                    normalized_parts.append(part)
                    continue

                normalized_parts.append({'type': 'image_url', 'image_url': url})
                changed = True

            if changed:
                message['content'] = normalized_parts

    def handle_chat_request(self, req: Dict[str, Any]) -> Optional[requests.Response | Dict[str, Any] | ProxyRequestError]:
        messages = req.get('messages')
        stream = req.get('stream', True)
        requested_model = req.get('model')
        thinking_level = req.get('thinking_level')
        max_tokens = req.get('max_tokens')

        if messages:
            self._process_image_content(messages)
        else:
            logging.warning("요청에 messages가 없습니다.")
            return None

        provider, model, base_url = self._parse_model(requested_model)

        if not provider:
            logging.error(f"지원되지 않는 모델: {requested_model}")
            return None

        removed_model_error = self._validate_provider_model(provider, model, requested_model)
        if removed_model_error is not None:
            logging.warning("비활성화된 모델 요청 차단: %s", requested_model)
            return removed_model_error

        cursor_request_tools = req.get("tools")
        cursor_has_tools = (
            isinstance(cursor_request_tools, list) and len(cursor_request_tools) > 0
        )
        if provider in CURSOR_BRIDGE_PROVIDERS and messages:
            if cursor_has_tools:
                messages = self._inject_compact_tools_for_cursor(
                    messages, cursor_request_tools
                )
            messages = self._convert_messages_for_cursor_provider(messages)

        if provider == "opencode" and uses_opencode_anthropic_messages(model):
            result = self._handle_opencode_anthropic_messages_request(
                base_url=base_url,
                model=model,
                requested_model=requested_model,
                messages=messages,
                stream=stream,
                max_tokens=max_tokens,
                tools=req.get("tools"),
                tool_choice=req.get("tool_choice"),
                anthropic_passthrough=bool(req.get("_anthropic_passthrough")),
            )
            return self._maybe_retry_after_context_overflow(req, result)

        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if provider not in CURSOR_BRIDGE_PROVIDERS:
            if req.get("tools") is not None:
                payload["tools"] = req.get("tools")
            if req.get("tool_choice") is not None:
                payload["tool_choice"] = req.get("tool_choice")
        if provider == 'opencode':
            thinking_level = req.get('thinking_level')
            if thinking_level and thinking_level != 'minimal':
                payload['reasoning_effort'] = thinking_level
        endpoint = f"{base_url}/chat/completions"
        headers = {'Content-Type': 'application/json'}
        if provider in CURSOR_BRIDGE_PROVIDERS:
            headers["X-Cursor-Mode"] = "agent"

        client = self._get_client(provider)
        result = client.post_request(
            url=endpoint,
            payload=payload,
            headers=headers,
            stream=stream
        )
        return self._maybe_retry_after_context_overflow(req, result)
