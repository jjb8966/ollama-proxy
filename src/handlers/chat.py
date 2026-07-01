# -*- coding: utf-8 -*-
"""
채팅 요청 핸들러 모듈

클라이언트의 채팅 요청을 처리하고 적절한 API 제공업체로 라우팅합니다.
"""

import json
import json
import logging
import os
import re
import time
import os
import time
from typing import Dict, Any, List, Optional

import requests

from src.core.errors import ProxyRequestError, ErrorHandler
from src.providers.standard import StandardApiClient
from src.providers.qwen import QwenApiClient
from src.providers.google import GoogleApiClient
from src.utils.model_limits import get_model_limits, load_model_limits
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


def _strip_quotes(value: str) -> str:
    """문자열 값에서 양쪽 따옴표를 제거합니다."""
    if not value:
        return value
    return value.strip('"\'')


# #region agent log
_DEBUG_LOG_PATH = os.environ.get(
    "DEBUG_NDJSON_LOG",
    "/Users/jbj/Desktop/work/my/project/.cursor/debug-dfc5c9.log",
)


def _agent_debug_log(
    location: str,
    message: str,
    data: dict,
    hypothesis_id: str,
    run_id: str = "pre-fix",
) -> None:
    try:
        payload = {
            "sessionId": "dfc5c9",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        pass


# #endregion


class ChatHandler:
    """
    채팅 요청 핸들러

    모델 prefix에 따라 적절한 API 제공업체로 요청을 라우팅합니다.
    이미지 처리, 메시지 정규화 등의 전처리도 수행합니다.
    """

    COMPACTION_THRESHOLD_RATIO = 0.8
    COMPACTION_REQUIRED_MESSAGE = (
        "현재 요청 페이로드가 모델의 최대 컨텍스트 임계값을 초과했습니다. "
        "사용자가 직접 대화 또는 입력을 compact한 뒤 다시 시도해 주세요."
    )
    REMOVED_ANTIGRAVITY_MODELS = {
        "claude-opus-4-6-thinking",
        "claude-sonnet-4-6",
        "gemini-3-flash",
        "gemini-3.1-pro-high",
        "gemini-3.1-pro-low",
        "gcli-gemini-3.1-pro-preview",
        "gcli-gemini-3.1-pro-preview-customtools",
    }

    COMPACTION_ENABLED = os.environ.get("ENABLE_COMPACTION", "true").lower() != "false"

    # 제공업체별 prefix와 base_url 매핑
    PROVIDER_CONFIG = {
        'google': {
            'base_url': None,
            'client_attr': 'google_client'
        },
        'openrouter': {
            'base_url': 'https://openrouter.ai/api/v1',
            'client_attr': 'openrouter_client'
        },
        'akash': {
            'base_url': 'https://chatapi.akash.network/api/v1',
            'client_attr': 'akash_client'
        },
        'cohere': {
            'base_url': 'https://api.cohere.ai/compatibility/v1',
            'client_attr': 'cohere_client'
        },
        'codestral': {
            'base_url': 'https://codestral.mistral.ai/v1',
            'client_attr': 'codestral_client'
        },
        'qwen': {
            'base_url': 'https://portal.qwen.ai/v1',
            'client_attr': 'qwen_client'
        },
        'antigravity': {
            'base_url': _strip_quotes(os.getenv('ANTIGRAVITY_PROXY_URL', 'http://antigravity-proxy:5010/v1')),
            'client_attr': 'antigravity_client'
        },
        'nvidia-nim': {
            'base_url': _strip_quotes(os.getenv('NVIDIA_NIM_BASE_URL', 'https://integrate.api.nvidia.com/v1')),
            'client_attr': 'nvidia_nim_client'
        },
        'cli-proxy-api': {
            'base_url': _strip_quotes(os.getenv('CLI_PROXY_API_BASE_URL', 'http://cli-proxy-api:8317/v1')),
            'client_attr': 'cli_proxy_api_client'
        },
        'cli-proxy-api-plus': {
            'base_url': _strip_quotes(os.getenv('CLI_PROXY_API_PLUS_BASE_URL', 'http://cli-proxy-api-plus:8317/v1')),
            'client_attr': 'cli_proxy_api_plus_client'
        },
        'ccs': {
            'base_url': _strip_quotes(os.getenv('CCS_API_BASE_URL', 'http://ccs:8317/api/provider/cursor/v1')),
            'client_attr': 'ccs_client'
        },
        'cursor': {
            'base_url': _strip_quotes(os.getenv('CURSOR_API_BASE_URL', 'http://host.docker.internal:8765/v1')),
            'client_attr': 'cursor_client'
        },
        # Primary: ollama-cloud
        'ollama-cloud': {
            'base_url': _strip_quotes(os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1')),
            'client_attr': 'ollama_cloud_client'
        },
        # Backward-compatible alias
        'ollama': {
            'base_url': _strip_quotes(os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1')),
            'client_attr': 'ollama_cloud_client'
        },
        'opencode': {
            'base_url': _strip_quotes(os.getenv('OPENCODE_BASE_URL', 'https://opencode.ai/zen/go/v1')),
            'client_attr': 'opencode_client'
        }
    }

    def __init__(self, api_config):
        """
        Args:
            api_config: ApiConfig 인스턴스 (각 제공업체의 rotator 포함)
        """
        self.api_config = api_config

        # 각 제공업체별 클라이언트 생성
        self.google_client = GoogleApiClient(api_config.google_rotator)
        self.openrouter_client = StandardApiClient(api_config.openrouter_rotator)
        self.akash_client = StandardApiClient(api_config.akash_rotator)
        self.cohere_client = StandardApiClient(api_config.cohere_rotator)
        self.codestral_client = StandardApiClient(api_config.codestral_rotator)
        self.qwen_client = QwenApiClient(api_config.qwen_oauth_manager)
        self.antigravity_client = StandardApiClient(api_config.antigravity_rotator)
        self.nvidia_nim_client = StandardApiClient(api_config.nvidia_nim_rotator)
        self.cli_proxy_api_client = StandardApiClient(api_config.cli_proxy_api_rotator)
        self.cli_proxy_api_plus_client = StandardApiClient(api_config.cli_proxy_api_plus_rotator)
        self.ccs_client = StandardApiClient(api_config.ccs_rotator)
        self.cli_proxy_api_gpt_client = StandardApiClient(api_config.cli_proxy_api_gpt_rotator)
        self.cursor_client = StandardApiClient(api_config.cursor_rotator)
        self.ollama_cloud_client = StandardApiClient(api_config.ollama_cloud_rotator)
        self.opencode_client = StandardApiClient(api_config.opencode_rotator)

    @staticmethod
    def _estimate_request_tokens(req: Dict[str, Any]) -> int:
        messages = req.get("messages", [])
        total_chars = 0

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        total_chars += len(str(block.get("text", "")))
                    elif block.get("type") == "image_url":
                        # base64 이미지는 실제 토큰화 시 약 85 토큰만 사용
                        # 과대추정 방지를 위해 작은 고정값 사용
                        total_chars += 340  # 약 85 tokens × 4 chars
                    else:
                        # tool_result 등 기타 블록
                        total_chars += len(
                            json.dumps(block, ensure_ascii=False, default=str)
                        )
            elif isinstance(content, dict):
                total_chars += len(
                    json.dumps(content, ensure_ascii=False, default=str)
                )

        # tools, tool_choice
        tools = req.get("tools")
        if isinstance(tools, list):
            total_chars += len(json.dumps(tools, ensure_ascii=False, default=str))
        tool_choice = req.get("tool_choice")
        if tool_choice is not None:
            total_chars += len(json.dumps(tool_choice, ensure_ascii=False, default=str))

        return max(1, int(total_chars / 3.5))  # chars/3.5가 chars/4보다 정확

    def _build_compaction_notice_content(
        self,
        requested_model: str,
        estimated_tokens: int,
        context_length: int
    ) -> str:
        threshold_tokens = int(context_length * self.COMPACTION_THRESHOLD_RATIO)
        return (
            f"{self.COMPACTION_REQUIRED_MESSAGE}\n\n"
            f"- model: {requested_model}\n"
            f"- estimated_tokens: {estimated_tokens}\n"
            f"- context_length: {context_length}\n"
            f"- compaction_threshold_tokens: {threshold_tokens}"
        )

    def _build_compaction_notice_response(
        self,
        req: Dict[str, Any],
        estimated_tokens: int,
        context_length: int
    ) -> Dict[str, Any]:
        requested_model = req.get("model", "unknown")
        content = self._build_compaction_notice_content(
            requested_model=requested_model,
            estimated_tokens=estimated_tokens,
            context_length=context_length,
        )
        return {
            "id": f"chatcmpl-compaction-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": requested_model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
        }

    def _build_compaction_notice_stream(
        self,
        req: Dict[str, Any],
        estimated_tokens: int,
        context_length: int
    ):
        requested_model = req.get("model", "unknown")
        created = int(time.time())
        content = self._build_compaction_notice_content(
            requested_model=requested_model,
            estimated_tokens=estimated_tokens,
            context_length=context_length,
        )

        chunk = {
            "id": f"chatcmpl-compaction-{created}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": requested_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "content": content,
                    },
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        final_chunk = {
            "id": f"chatcmpl-compaction-{created}",
            "object": "chat.completion.chunk",
            "created": created,
            "model": requested_model,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    def _find_long_context_model(self, requested_model: str) -> Optional[str]:
        """현재 모델보다 context_length가 더 큰 같은 provider의 fallback 모델을 찾는다."""
        if not isinstance(requested_model, str) or not requested_model:
            return None

        current_limits = get_model_limits(requested_model)
        if not current_limits or not current_limits.context_length:
            return None

        provider, model, _ = self._parse_model(requested_model)
        if not provider:
            return None

        all_limits = load_model_limits()
        best_model = None
        best_length = current_limits.context_length

        for model_name, limits in all_limits.items():
            if not limits.context_length or limits.context_length <= best_length:
                continue
            p, _, _ = self._parse_model(model_name)
            if p == provider:
                best_length = limits.context_length
                best_model = model_name

        return best_model

    def _handle_context_overflow_fallback(
        self,
        req: Dict[str, Any],
        error: Any,
    ) -> Optional[Any]:
        """CCR-style: context overflow 발생 시 long-context 모델로 자동 재시도"""
        requested_model = req.get("model", "")
        error_msg = ""
        if isinstance(error, str):
            error_msg = error
        elif hasattr(error, 'text'):
            error_msg = error.text
        elif isinstance(error, Exception):
            error_msg = str(error)

        if not ErrorHandler.is_context_overflow_message(error_msg):
            return None  # context overflow가 아니면 재시도 안 함

        long_context_model = self._find_long_context_model(requested_model)
        if not long_context_model or long_context_model == requested_model:
            return None  # 재시도할 모델이 없음

        logging.warning(
            "[ContextOverflowFallback] %s → %s 재시도",
            requested_model, long_context_model
        )

        retry_req = dict(req)
        retry_req["model"] = long_context_model
        return self.handle_chat_request(retry_req)

    def _maybe_route_long_context(
        self,
        req: Dict[str, Any]
    ) -> Optional[Any]:
        # Returns: dict (routed req), generator (compaction notice stream),
        # or dict (compaction notice response)
        if not self.COMPACTION_ENABLED:
            return None

        requested_model = req.get("model")
        if not isinstance(requested_model, str) or not requested_model:
            return None

        limits = get_model_limits(requested_model)
        if limits is None or limits.context_length is None or limits.context_length <= 0:
            return None

        estimated_tokens = self._estimate_request_tokens(req)
        threshold_tokens = int(limits.context_length * self.COMPACTION_THRESHOLD_RATIO)
        if estimated_tokens <= threshold_tokens:
            return None

        long_context_model = self._find_long_context_model(requested_model)
        if long_context_model:
            logging.info(
                "[LongContextRouting] %s → %s (tokens: %d, threshold: %d)",
                requested_model, long_context_model, estimated_tokens, threshold_tokens
            )
            req = dict(req)
            req["model"] = long_context_model
            return req

        # fallback 없으면 에러 반환 (기존 compaction 동작 유지)
        logging.warning(
            "[LongContextRouting] fallback 모델 없음, compaction 필요: model=%s tokens=%d",
            requested_model, estimated_tokens
        )
        if req.get("stream", True):
            return self._build_compaction_notice_stream(req, estimated_tokens, limits.context_length)
        return self._build_compaction_notice_response(req, estimated_tokens, limits.context_length)

    def _parse_model(self, requested_model: str) -> tuple:
        """
        모델 문자열에서 제공업체와 모델명을 추출합니다.

        Args:
            requested_model: "provider:model_name" 형식의 문자열

        Returns:
            (제공업체, 모델명, base_url) 튜플
        """
        for prefix, config in self.PROVIDER_CONFIG.items():
            if requested_model.startswith(f"{prefix}:"):
                model = requested_model.replace(f'{prefix}:', '')
                return prefix, model, config['base_url']

        # 매칭되는 제공업체가 없는 경우
        return None, requested_model, None

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

        routed = self._maybe_route_long_context(req)
        if routed is not None:
            if isinstance(routed, dict) and "model" in routed and "messages" in routed:
                # long-context 모델로 라우팅된 경우 req 교체
                req = routed
                requested_model = req.get("model", requested_model)
            else:
                # compaction notice 응답인 경우 그대로 반환
                return routed

        provider, model, base_url = self._parse_model(requested_model)

        if not provider:
            logging.error(f"지원되지 않는 모델: {requested_model}")
            return None

        removed_model_error = self._validate_provider_model(provider, model, requested_model)
        if removed_model_error is not None:
            logging.warning("비활성화된 모델 요청 차단: %s", requested_model)
            return removed_model_error

        if provider == 'ollama-cloud':
            self._normalize_ollama_cloud_image_content(messages)

        cursor_request_tools = req.get("tools")
        cursor_has_tools = (
            isinstance(cursor_request_tools, list) and len(cursor_request_tools) > 0
        )
        if provider in ("cursor", "ccs") and messages:
            if cursor_has_tools:
                messages = self._inject_compact_tools_for_cursor(
                    messages, cursor_request_tools
                )
            messages = self._convert_messages_for_cursor_provider(messages)

        if provider == 'google':
            return self.google_client.post_request(
                model=model,
                messages=messages,
                thinking_level=thinking_level,
                stream=stream,
                max_tokens=req.get('max_tokens'),
                tools=req.get('tools'),
                tool_choice=req.get('tool_choice')
            )

        if provider == "opencode" and uses_opencode_anthropic_messages(model):
            return self._handle_opencode_anthropic_messages_request(
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

        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }

        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if provider != "cursor":
            if req.get("tools") is not None:
                payload["tools"] = req.get("tools")
            if req.get("tool_choice") is not None:
                payload["tool_choice"] = req.get("tool_choice")
        if provider == 'opencode':
            thinking_level = req.get('thinking_level')
            if thinking_level and thinking_level != 'minimal':
                payload['reasoning_effort'] = thinking_level
        if provider == 'cursor':
            reasoning_effort = req.get('reasoning_effort')
            if reasoning_effort:
                payload['reasoning_effort'] = reasoning_effort

        endpoint = f"{base_url}/chat/completions"
        headers = {'Content-Type': 'application/json'}
        if provider in ("cursor", "ccs"):
            headers["X-Cursor-Mode"] = "ask" if cursor_has_tools else "agent"

        # #region agent log
        if provider in ("cursor", "ccs"):
            messages_json_size = len(
                json.dumps(messages, ensure_ascii=False, default=str)
            )
            _agent_debug_log(
                "chat.py:handle_chat_request",
                "cursor upstream payload",
                {
                    "model": requested_model,
                    "payload_has_tools": "tools" in payload,
                    "payload_tools_count": len(payload.get("tools", []))
                    if isinstance(payload.get("tools"), list)
                    else 0,
                    "req_tools_count": len(cursor_request_tools)
                    if isinstance(cursor_request_tools, list)
                    else 0,
                    "cursor_mode_header": headers.get("X-Cursor-Mode"),
                    "compact_tools_injected": cursor_has_tools,
                    "messages_json_size": messages_json_size,
                    "message_roles": [
                        str(message.get("role", ""))
                        for message in messages[-8:]
                        if isinstance(message, dict)
                    ],
                    "assistant_tool_call_messages": sum(
                        1
                        for message in messages
                        if isinstance(message, dict) and message.get("tool_calls")
                    ),
                    "tool_result_messages": sum(
                        1
                        for message in messages
                        if isinstance(message, dict) and message.get("role") == "tool"
                    ),
                },
                "H6",
                run_id="post-fix-e2big",
            )
        # #endregion

        client = self._get_client(provider)
        return client.post_request(
            url=endpoint,
            payload=payload,
            headers=headers,
            stream=stream
        )
