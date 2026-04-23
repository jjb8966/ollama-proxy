# -*- coding: utf-8 -*-
"""
Anthropic 호환 요청/응답 핸들러

Claude Code 등 Anthropic Messages API 클라이언트와의 호환을 위해
요청을 내부 ChatHandler 형식으로 변환하고, 응답을 Anthropic 형식으로 변환합니다.
"""

import inspect
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, Generator, Iterable, List, Optional, Union

from requests import Response

from src.utils.schema_sanitizer import SCHEMA_ALLOWED_KEYS, sanitize_schema
from src.utils.text_extraction import ANTHROPIC_TEXT_KEYS, extract_text_from_content_value

logger = logging.getLogger(__name__)


def _is_empty_value(value: Any) -> bool:
    """값이 empty string, None, 또는 whitespace-only string인지 확인합니다."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


class AnthropicHandler:
    """Anthropic Messages API 형식 변환 핸들러"""

    @staticmethod
    def _truncate_log_text(value: Any, limit: int = 300) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        if len(value) <= limit:
            return value
        return f"{value[:limit]}..."

    @staticmethod
    def _extract_text_from_content_value(content: Any) -> str:
        return extract_text_from_content_value(content, keys=ANTHROPIC_TEXT_KEYS)

    @staticmethod
    def _extract_stream_reasoning(choice: Dict[str, Any]) -> str:
        """스트리밍 청크에서 reasoning_content를 추출합니다."""
        if not isinstance(choice, dict):
            return ""
        delta = choice.get("delta", {})
        if isinstance(delta, dict):
            for key in ("reasoning_content", "reasoning"):
                extracted = extract_text_from_content_value(delta.get(key))
                if extracted:
                    return extracted
        message = choice.get("message", {})
        if isinstance(message, dict):
            for key in ("reasoning_content", "reasoning"):
                extracted = extract_text_from_content_value(message.get(key))
                if extracted:
                    return extracted
        return ""

    def _extract_stream_text(self, choice: Dict[str, Any]) -> str:
        if not isinstance(choice, dict):
            return ""

        delta = choice.get("delta", {})
        if isinstance(delta, dict):
            for key in ("content", "text"):
                extracted = self._extract_text_from_content_value(delta.get(key))
                if extracted:
                    return extracted

        message = choice.get("message", {})
        if isinstance(message, dict):
            for key in ("content",):
                extracted = self._extract_text_from_content_value(message.get(key))
                if extracted:
                    return extracted

        return self._extract_text_from_content_value(choice.get("text"))

    def _summarize_stream_choice(self, choice: Any) -> str:
        if not isinstance(choice, dict):
            return self._truncate_log_text(choice)

        summary: Dict[str, Any] = {"choice_keys": sorted(choice.keys())}
        delta = choice.get("delta")
        if isinstance(delta, dict):
            summary["delta_keys"] = sorted(delta.keys())
        message = choice.get("message")
        if isinstance(message, dict):
            summary["message_keys"] = sorted(message.keys())
        finish_reason = choice.get("finish_reason")
        if finish_reason is not None:
            summary["finish_reason"] = finish_reason

        return self._truncate_log_text(json.dumps(summary, ensure_ascii=False))

    @staticmethod
    def normalize_model_name(model_name: Any) -> Any:
        if not isinstance(model_name, str):
            return model_name
        if ":" in model_name:
            return model_name
        if "/" in model_name:
            provider, rest = model_name.split("/", 1)
            if provider and rest:
                return f"{provider}:{rest}"
        return model_name

    @staticmethod
    def _sanitize_tool_id(raw_id: Any) -> str:
        candidate = str(raw_id or "")
        candidate = re.sub(r"[^a-zA-Z0-9_-]", "_", candidate)
        if not candidate:
            candidate = f"toolu_{uuid.uuid4().hex[:24]}"
        return candidate

    @staticmethod
    def _normalize_tool_calls(tool_calls_value: Any) -> List[Dict[str, Any]]:
        if not isinstance(tool_calls_value, list):
            return []
        return [
            tool_call for tool_call in tool_calls_value if isinstance(tool_call, dict)
        ]

    @staticmethod
    def _content_blocks_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return ""

        text_parts: List[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_parts.append(str(block.get("text", "")))
        return "".join(text_parts)

    @staticmethod
    def _normalize_image_block(block: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(block, dict) or block.get("type") != "image":
            return None

        source = block.get("source")
        if not isinstance(source, dict):
            return None

        source_type = str(source.get("type", "")).strip()
        if source_type == "base64":
            media_type = str(source.get("media_type", "")).strip()
            data = source.get("data")
            if not media_type or not isinstance(data, str) or not data:
                return None
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            }

        if source_type == "url":
            url = source.get("url")
            if isinstance(url, str) and url:
                return {"type": "image_url", "image_url": {"url": url}}

        return None

    def _normalize_system_messages(self, system_value: Any) -> List[Dict[str, Any]]:
        if system_value is None:
            return []
        if isinstance(system_value, str):
            if not system_value:
                return []
            return [{"role": "system", "content": system_value}]
        if isinstance(system_value, list):
            text = self._content_blocks_to_text(system_value)
            if not text:
                return []
            return [{"role": "system", "content": text}]
        return []

    def _normalize_messages(self, messages: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(messages, list):
            return normalized

        for message in messages:
            if not isinstance(message, dict):
                continue

            role = str(message.get("role", ""))
            if role not in ("user", "assistant", "system"):
                continue

            content = message.get("content", "")
            if isinstance(content, str):
                normalized.append({"role": role, "content": content})
                continue

            if not isinstance(content, list):
                normalized.append({"role": role, "content": ""})
                continue

            if role == "assistant":
                text_parts: List[str] = []
                reasoning_parts: List[str] = []
                assistant_tool_calls: List[Dict[str, Any]] = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")

                    if block_type == "thinking":
                        thinking_text = block.get("thinking", "")
                        if isinstance(thinking_text, str) and thinking_text:
                            reasoning_parts.append(thinking_text)
                        continue

                    if block_type == "text":
                        text_parts.append(str(block.get("text", "")))
                        continue

                    if block_type != "tool_use":
                        continue

                    tool_id = self._sanitize_tool_id(block.get("id"))
                    tool_name = str(block.get("name", ""))
                    tool_input = block.get("input", {})
                    if not isinstance(tool_input, dict):
                        tool_input = {"input": tool_input}
                    assistant_tool_calls.append(
                        {
                            "id": tool_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(tool_input, ensure_ascii=False),
                            },
                        }
                    )

                assistant_message: Dict[str, Any] = {
                    "role": "assistant",
                    "content": "".join(text_parts),
                }
                if reasoning_parts:
                    assistant_message["reasoning_content"] = "\n".join(reasoning_parts)
                if assistant_tool_calls:
                    assistant_message["tool_calls"] = assistant_tool_calls
                normalized.append(assistant_message)
                continue

            if role == "user":
                pending_content_blocks: List[Dict[str, Any]] = []

                def flush_user_content() -> None:
                    if not pending_content_blocks:
                        return
                    if all(
                        block.get("type") == "text"
                        for block in pending_content_blocks
                    ):
                        normalized.append(
                            {
                                "role": "user",
                                "content": "".join(
                                    str(block.get("text", ""))
                                    for block in pending_content_blocks
                                ),
                            }
                        )
                    else:
                        normalized.append(
                            {
                                "role": "user",
                                "content": pending_content_blocks.copy(),
                            }
                        )
                    pending_content_blocks.clear()

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")

                    if block_type == "text":
                        pending_content_blocks.append(
                            {"type": "text", "text": str(block.get("text", ""))}
                        )
                        continue

                    if block_type == "image":
                        normalized_image_block = self._normalize_image_block(block)
                        if normalized_image_block is not None:
                            pending_content_blocks.append(normalized_image_block)
                        continue

                    if block_type != "tool_result":
                        continue

                    flush_user_content()

                    tool_id = self._sanitize_tool_id(block.get("tool_use_id"))
                    tool_content = block.get("content", "")
                    if isinstance(tool_content, list):
                        tool_text = self._content_blocks_to_text(tool_content)
                    elif isinstance(tool_content, str):
                        tool_text = tool_content
                    else:
                        tool_text = json.dumps(tool_content, ensure_ascii=False)
                    normalized.append(
                        {"role": "tool", "tool_call_id": tool_id, "content": tool_text}
                    )

                flush_user_content()
                continue

            normalized.append(
                {"role": role, "content": self._content_blocks_to_text(content)}
            )

        return normalized

    @staticmethod
    def _sanitize_tool_input_schema(schema: Any) -> Dict[str, Any]:
        return sanitize_schema(schema, allowed_keys=SCHEMA_ALLOWED_KEYS)

    @staticmethod
    def _extract_tools_contract(tools: Any) -> Dict[str, Dict[str, Any]]:
        """
        Anthropic tools 요청에서 내부용 tool contract 메타데이터를 추출합니다.

        반환값은 tool_name -> {schema, required} 맵핑입니다.
        이 정보는 응답 변환에서 tool_input을 정규화할 때 사용됩니다.
        """
        contracts: Dict[str, Dict[str, Any]] = {}
        if not isinstance(tools, list):
            return contracts

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            schema = tool.get("input_schema", {})
            if not isinstance(schema, dict):
                schema = {}
            raw_required = schema.get("required", [])
            if not isinstance(raw_required, (list, tuple, set)):
                required = set()
            else:
                required = {
                    item for item in raw_required if isinstance(item, str)
                }

            # properties 정보 보존
            properties = schema.get("properties", {})
            if not isinstance(properties, dict):
                properties = {}

            contracts[name] = {
                "schema": schema,
                "required": required,
                "properties": properties,
            }

        return contracts

    @staticmethod
    def _normalize_tool_input(
        tool_input: Dict[str, Any],
        tool_contract: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        tool_input을 schema-aware하게 정규화합니다.

        - required가 아닌 필드이고 값이 빈 문자열/None/공백이면 제거
        - Agent/Explore 스타일 payload에서 optional 빈 문자열 필드 제거
        - Read 도구의 pages="" 같은 경우 처리
        - nested object/array에도 같은 규칙을 재귀 적용
        """
        if not isinstance(tool_input, dict):
            return tool_input

        if not tool_contract:
            return tool_input

        def normalize_value(
            value: Any,
            schema: Optional[Dict[str, Any]],
            required_fields: set[str],
        ) -> Any:
            if isinstance(value, dict):
                nested_schema = schema if isinstance(schema, dict) else {}
                nested_properties = nested_schema.get("properties", {})
                if not isinstance(nested_properties, dict):
                    nested_properties = {}
                nested_required = nested_schema.get("required", [])
                if not isinstance(nested_required, (list, tuple, set)):
                    nested_required = []
                nested_required_set = {
                    item for item in nested_required if isinstance(item, str)
                }

                normalized_dict: Dict[str, Any] = {}
                for nested_key, nested_value in value.items():
                    child_schema = nested_properties.get(nested_key)
                    normalized_child = normalize_value(
                        nested_value,
                        child_schema if isinstance(child_schema, dict) else None,
                        nested_required_set,
                    )
                    if nested_key in nested_required_set:
                        normalized_dict[nested_key] = normalized_child
                        continue
                    if _is_empty_value(normalized_child):
                        continue
                    normalized_dict[nested_key] = normalized_child
                return normalized_dict

            if isinstance(value, list):
                item_schema = schema.get("items") if isinstance(schema, dict) else None
                normalized_list = [
                    normalize_value(
                        item,
                        item_schema if isinstance(item_schema, dict) else None,
                        set(),
                    )
                    for item in value
                ]
                return normalized_list

            return value

        schema = tool_contract.get("schema", {})
        if not isinstance(schema, dict):
            schema = {}
        properties = tool_contract.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}

        required_fields = tool_contract.get("required", set())
        if not isinstance(required_fields, (set, list, tuple)):
            required_fields = set()
        else:
            required_fields = {
                item for item in required_fields if isinstance(item, str)
            }

        normalized: Dict[str, Any] = {}
        for key, value in tool_input.items():
            child_schema = properties.get(key)
            normalized_value = normalize_value(
                value,
                child_schema if isinstance(child_schema, dict) else None,
                set(),
            )
            if key in required_fields:
                normalized[key] = normalized_value
                continue
            if _is_empty_value(normalized_value):
                continue
            normalized[key] = normalized_value

        if schema.get("type") == "object" and "properties" in schema and not normalized:
            return {}
        return normalized

    @staticmethod
    def _normalize_tools(tools: Any) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        if not isinstance(tools, list):
            return normalized

        for tool in tools:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name", "")).strip()
            if not name:
                continue
            input_schema = AnthropicHandler._sanitize_tool_input_schema(
                tool.get("input_schema", {"type": "object", "properties": {}})
            )
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.get("description", ""),
                        "parameters": input_schema,
                    },
                }
            )
        return normalized

    @staticmethod
    def _normalize_tool_choice(tool_choice: Any) -> Any:
        if not isinstance(tool_choice, dict):
            return tool_choice

        choice_type = tool_choice.get("type")
        if choice_type == "auto":
            return "auto"
        if choice_type == "any":
            return "required"
        if choice_type == "tool":
            name = tool_choice.get("name")
            if name:
                return {"type": "function", "function": {"name": name}}
        return tool_choice

    def build_proxy_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        system_messages = self._normalize_system_messages(req.get("system"))
        chat_messages = self._normalize_messages(req.get("messages"))
        request_tools = req.get("tools")
        normalized_tools = self._normalize_tools(request_tools)

        result: Dict[str, Any] = {
            "model": self.normalize_model_name(req.get("model")),
            "messages": system_messages + chat_messages,
            "stream": bool(req.get("stream", False)),
            "max_tokens": req.get("max_tokens"),
            "thinking_level": req.get("thinking_level", "minimal"),
            "tool_choice": self._normalize_tool_choice(req.get("tool_choice")),
            "_tools_contract": self._extract_tools_contract(request_tools),
        }
        if normalized_tools:
            result["tools"] = normalized_tools
        return result

    @staticmethod
    def _map_stop_reason(openai_reason: Optional[str]) -> str:
        if openai_reason == "length":
            return "max_tokens"
        if openai_reason == "tool_calls":
            return "tool_use"
        return "end_turn"

    def _build_anthropic_content(
        self,
        message: Dict[str, Any],
        tools_contract: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        content_blocks: List[Dict[str, Any]] = []

        # thinking 블록은 text 블록보다 먼저 와야 함 (Anthropic API 명세)
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            content_blocks.append({"type": "thinking", "thinking": reasoning_content})

        text_content = message.get("content")
        if isinstance(text_content, str) and text_content:
            content_blocks.append({"type": "text", "text": text_content})

        tool_calls = self._normalize_tool_calls(message.get("tool_calls"))
        for tool_call in tool_calls:
            function_info = tool_call.get("function", {})
            args_raw = function_info.get("arguments", "{}")
            try:
                tool_input = (
                    json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                )
            except json.JSONDecodeError:
                tool_input = {}
            if not isinstance(tool_input, dict):
                tool_input = {"input": tool_input}

            # tools_contract가 있으면 tool_input 정규화
            tool_name = str(function_info.get("name", ""))
            if tools_contract and tool_name in tools_contract:
                tool_contract = tools_contract[tool_name]
                tool_input = self._normalize_tool_input(tool_input, tool_contract)

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": self._sanitize_tool_id(tool_call.get("id")),
                    "name": tool_name,
                    "input": tool_input,
                }
            )

        if not content_blocks:
            content_blocks.append({"type": "text", "text": ""})
        return content_blocks

    def handle_non_streaming_response(
        self,
        resp: Union[Dict[str, Any], Response],
        requested_model: str,
        tools_contract: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        data = resp if isinstance(resp, dict) else resp.json()
        if "choices" not in data or not isinstance(data.get("choices"), list):
            raise ValueError("Expected OpenAI-compatible response with choices")

        usage = data.get("usage", {})
        choices = data.get("choices", [])
        finish_reason = None
        message: Dict[str, Any] = {}
        if choices:
            finish_reason = choices[0].get("finish_reason")
            message = choices[0].get("message", {})

        response_model = str(data.get("model", requested_model))
        return {
            "id": f"msg_{uuid.uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": response_model,
            "content": self._build_anthropic_content(message, tools_contract),
            "stop_reason": self._map_stop_reason(finish_reason),
            "stop_sequence": None,
            "usage": {
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            },
        }

    @staticmethod
    def _iter_stream_lines(
        resp: Union[Generator[str, None, None], Response],
    ) -> Iterable[str]:
        if inspect.isgenerator(resp):
            for chunk in resp:
                if chunk is None:
                    continue
                text = (
                    chunk.decode("utf-8", errors="ignore")
                    if isinstance(chunk, bytes)
                    else str(chunk)
                )
                for line in text.splitlines():
                    yield line
            return

        for line in resp.iter_lines():
            if not line:
                yield ""
                continue
            yield line.decode("utf-8", errors="ignore")

    def stream_anthropic_response(
        self,
        resp: Union[Generator[str, None, None], Response],
        requested_model: str,
        request_id: Optional[str] = None,
        tools_contract: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> Generator[str, None, None]:
        message_id = f"msg_{uuid.uuid4().hex}"
        response_model = requested_model
        stop_reason = "end_turn"
        current_index = 0
        thinking_block_open = False
        text_block_open = False
        tool_block_state: Dict[int, Dict[str, Any]] = {}
        stream_id = request_id or message_id
        start_time = time.time()
        first_chunk_time: Optional[float] = None
        last_chunk_time = start_time
        stream_done_received = False
        finish_reason_received = False
        blocks_closed = False
        stream_completed = False
        stream_closed_by_generator = False
        stream_ended_without_done = False
        line_count = 0
        data_line_count = 0
        empty_line_count = 0
        chunk_count = 0
        text_char_count = 0
        tool_delta_count = 0
        last_payload_sample = ""
        last_choice_summary = ""

        def sse(event: str, data: Dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        def ensure_tool_block_started(
            block_index: int, state: Dict[str, Any]
        ) -> List[str]:
            """Tool block이 시작되지 않았으면 시작 이벤트를 생성합니다."""
            if state.get("started") or not state.get("name"):
                return []

            logger.info(
                "[AnthropicStream] tool 블록 시작 | request_id=%s | index=%s | tool=%s | tool_id=%s",
                stream_id,
                block_index,
                state["name"],
                state["id"],
            )
            state["started"] = True
            return [
                sse(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": block_index,
                        "content_block": {
                            "type": "tool_use",
                            "id": state["id"],
                            "name": state["name"],
                            "input": {},
                        },
                    },
                )
            ]

        def flush_pending_tool_delta(
            block_index: int, state: Dict[str, Any]
        ) -> List[str]:
            """아직 전송하지 않은 tool argument delta를 플러시합니다."""
            if not state.get("started"):
                return []

            emitted_length = int(state.get("emitted_argument_length", 0))
            arguments = str(state.get("arguments", ""))
            pending_json = arguments[emitted_length:]
            if not pending_json:
                return []

            logger.debug(
                "[AnthropicStream] tool delta flush | request_id=%s | index=%s | tool=%s | arg_chars=%s",
                stream_id,
                block_index,
                state.get("name", "unknown"),
                len(pending_json),
            )
            state["emitted_argument_length"] = len(arguments)
            return [
                sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": block_index,
                        "delta": {
                            "type": "input_json_delta",
                            "partial_json": pending_json,
                        },
                    },
                )
            ]

        def close_open_blocks() -> List[str]:
            """모든 열린 content block을 닫습니다. 멱등 함수입니다."""
            nonlocal thinking_block_open, text_block_open, current_index, stop_reason, blocks_closed
            if blocks_closed:
                return []

            events: List[str] = []

            # 먼저 모든 tool block을 시작 (arguments가 name보다 먼저 왔을 경우)
            for block_index in sorted(tool_block_state.keys()):
                state = tool_block_state[block_index]
                if not state.get("started") and state.get("name"):
                    events.extend(ensure_tool_block_started(block_index, state))

            # tools_contract가 있으면 tool arguments 정규화
            if tools_contract:
                for block_index in sorted(tool_block_state.keys()):
                    state = tool_block_state[block_index]
                    tool_name = state.get("name", "")
                    if (
                        tool_name
                        and tool_name in tools_contract
                        and state.get("arguments")
                    ):
                        try:
                            parsed_args = json.loads(state["arguments"])
                            if isinstance(parsed_args, dict):
                                normalized_args = self._normalize_tool_input(
                                    parsed_args, tools_contract[tool_name]
                                )
                                normalized_json = json.dumps(
                                    normalized_args, ensure_ascii=False
                                )
                                if normalized_json != state["arguments"]:
                                    state["arguments"] = normalized_json
                                    state["emitted_argument_length"] = 0
                        except json.JSONDecodeError:
                            pass

            # 남은 tool argument delta 플러시
            for block_index in sorted(tool_block_state.keys()):
                state = tool_block_state[block_index]
                if state.get("started"):
                    events.extend(flush_pending_tool_delta(block_index, state))

            # finish_reason이 없고 tool block이 있으면 stop_reason 보정
            if not finish_reason_received and any(
                state.get("started") or state.get("name")
                for state in tool_block_state.values()
            ):
                stop_reason = "tool_use"

            # thinking block 종료
            if thinking_block_open:
                events.append(
                    sse(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": current_index},
                    )
                )
                thinking_block_open = False
                if not text_block_open:
                    current_index += 1

            # text block 종료
            if text_block_open:
                logger.info(
                    "[AnthropicStream] text 블록 종료 | request_id=%s | index=%s | text_chars=%s",
                    stream_id,
                    current_index,
                    text_char_count,
                )
                events.append(
                    sse(
                        "content_block_stop",
                        {"type": "content_block_stop", "index": current_index},
                    )
                )
                text_block_open = False

            # tool block 종료
            for block_index in sorted(tool_block_state.keys()):
                state = tool_block_state[block_index]
                if state.get("started") and not state.get("stopped"):
                    logger.info(
                        "[AnthropicStream] tool 블록 종료 | request_id=%s | index=%s | tool=%s | arg_chars=%s",
                        stream_id,
                        block_index,
                        state.get("name", "unknown"),
                        len(state.get("arguments", "")),
                    )
                    events.append(
                        sse(
                            "content_block_stop",
                            {"type": "content_block_stop", "index": block_index},
                        )
                    )
                    state["stopped"] = True
                elif state.get("arguments") and not state.get("name"):
                    logger.warning(
                        "[AnthropicStream] 이름 없는 tool arguments 폐기 | request_id=%s | index=%s | arg_chars=%s",
                        stream_id,
                        block_index,
                        len(state.get("arguments", "")),
                    )

            blocks_closed = True
            return events

        try:
            logger.info(
                "[AnthropicStream] ▶️ 시작 | request_id=%s | message_id=%s | model=%s",
                stream_id,
                message_id,
                requested_model,
            )
            yield sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": requested_model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )

            for raw_line in self._iter_stream_lines(resp):
                now = time.time()
                line_count += 1
                gap = now - last_chunk_time
                if gap > 5.0:
                    logger.warning(
                        "[AnthropicStream] ⚠️ 청크 지연 | request_id=%s | model=%s | gap=%.3fs | elapsed=%.3fs",
                        stream_id,
                        requested_model,
                        gap,
                        now - start_time,
                    )
                last_chunk_time = now

                line = raw_line.strip()
                if not line:
                    empty_line_count += 1
                    continue

                if not line.startswith("data:"):
                    logger.debug(
                        "[AnthropicStream] 비-data 라인 무시 | request_id=%s | sample=%s",
                        stream_id,
                        line[:120],
                    )
                    continue

                data_line_count += 1
                payload = line[5:].strip()
                last_payload_sample = self._truncate_log_text(payload)
                if payload == "[DONE]":
                    stream_done_received = True
                    logger.info(
                        "[AnthropicStream] [DONE] 수신 | request_id=%s | model=%s | elapsed=%.3fs",
                        stream_id,
                        requested_model,
                        time.time() - start_time,
                    )
                    for event in close_open_blocks():
                        yield event
                    break

                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    logger.warning(
                        "[AnthropicStream] JSON 디코드 실패 | request_id=%s | payload_sample=%s",
                        stream_id,
                        payload[:200],
                    )
                    continue

                chunk_count += 1
                if first_chunk_time is None:
                    first_chunk_time = now
                    logger.info(
                        "[AnthropicStream] ⏱️ 첫 청크 | request_id=%s | model=%s | latency=%.3fs",
                        stream_id,
                        requested_model,
                        first_chunk_time - start_time,
                    )

                response_model = str(data.get("model", response_model))
                choices = data.get("choices", [])
                if not choices:
                    logger.debug(
                        "[AnthropicStream] choices 없음 | request_id=%s | chunk_index=%s",
                        stream_id,
                        chunk_count,
                    )
                    continue

                choice = choices[0]
                last_choice_summary = self._summarize_stream_choice(choice)
                delta = choice.get("delta", {})
                finish_reason = choice.get("finish_reason")
                if finish_reason:
                    finish_reason_received = True
                    stop_reason = self._map_stop_reason(finish_reason)
                    logger.info(
                        "[AnthropicStream] finish_reason 수신 | request_id=%s | raw=%s | mapped=%s",
                        stream_id,
                        finish_reason,
                        stop_reason,
                    )

                reasoning = self._extract_stream_reasoning(choice)
                if reasoning:
                    if not thinking_block_open:
                        yield sse(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": current_index,
                                "content_block": {"type": "thinking", "thinking": ""},
                            },
                        )
                        thinking_block_open = True
                    yield sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": current_index,
                            "delta": {"type": "thinking_delta", "thinking": reasoning},
                        },
                    )

                text = self._extract_stream_text(choice)
                if text:
                    if thinking_block_open:
                        yield sse(
                            "content_block_stop",
                            {"type": "content_block_stop", "index": current_index},
                        )
                        thinking_block_open = False
                        current_index += 1
                    text_char_count += len(text)
                    if not text_block_open:
                        logger.info(
                            "[AnthropicStream] text 블록 시작 | request_id=%s | index=%s",
                            stream_id,
                            current_index,
                        )
                        yield sse(
                            "content_block_start",
                            {
                                "type": "content_block_start",
                                "index": current_index,
                                "content_block": {"type": "text", "text": ""},
                            },
                        )
                        text_block_open = True
                    yield sse(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": current_index,
                            "delta": {"type": "text_delta", "text": text},
                        },
                    )

                tool_calls = self._normalize_tool_calls(delta.get("tool_calls"))
                for tc_idx, tool_call in enumerate(tool_calls):
                    tc_index = tool_call.get("index", tc_idx)
                    block_index = current_index + 1 + tc_index
                    state = tool_block_state.setdefault(
                        block_index,
                        {
                            "id": self._sanitize_tool_id(tool_call.get("id")),
                            "name": "",
                            "arguments": "",
                            "started": False,
                            "stopped": False,
                            "emitted_argument_length": 0,
                        },
                    )

                    if tool_call.get("id"):
                        state["id"] = self._sanitize_tool_id(tool_call.get("id"))
                    function_info = tool_call.get("function", {})
                    if function_info.get("name"):
                        state["name"] = str(function_info.get("name"))
                    if function_info.get("arguments"):
                        state["arguments"] += str(function_info.get("arguments"))
                        tool_delta_count += 1

                    for event in ensure_tool_block_started(block_index, state):
                        yield event
                    if not tools_contract:
                        for event in flush_pending_tool_delta(block_index, state):
                            yield event

                if (
                    not text
                    and not tool_calls
                    and not finish_reason
                    and logger.isEnabledFor(logging.DEBUG)
                ):
                    logger.debug(
                        "[AnthropicStream] 텍스트 미추출 청크 | request_id=%s | choice_keys=%s | delta_keys=%s | sample=%s",
                        stream_id,
                        sorted(choice.keys()),
                        sorted(delta.keys()) if isinstance(delta, dict) else [],
                        json.dumps(choice, ensure_ascii=False)[:300],
                    )
            else:
                if not stream_done_received:
                    stream_ended_without_done = True
                    logger.warning(
                        "[AnthropicStream] [DONE] 없이 스트림 종료 | request_id=%s | message_id=%s | "
                        "model=%s | stop_reason=%s | chunks=%s | text_chars=%s | tool_deltas=%s | "
                        "last_payload=%s | last_choice=%s",
                        stream_id,
                        message_id,
                        response_model,
                        stop_reason,
                        chunk_count,
                        text_char_count,
                        tool_delta_count,
                        last_payload_sample,
                        last_choice_summary,
                    )

            for event in close_open_blocks():
                yield event

            if (
                stop_reason == "end_turn"
                and text_char_count == 0
                and tool_delta_count == 0
            ):
                logger.warning(
                    "[AnthropicStream] 빈 end_turn 응답 | request_id=%s | message_id=%s | "
                    "model=%s | chunks=%s | last_payload=%s | last_choice=%s",
                    stream_id,
                    message_id,
                    response_model,
                    chunk_count,
                    last_payload_sample,
                    last_choice_summary,
                )

            yield sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                },
            )
            yield sse("message_stop", {"type": "message_stop"})
            logger.info(
                "[AnthropicStream] ✅ 종료 | request_id=%s | message_id=%s | model=%s | "
                "done=%s | stop_reason=%s | chunks=%s | lines=%s | data_lines=%s | empty_lines=%s | "
                "text_chars=%s | tool_deltas=%s | duration=%.3fs",
                stream_id,
                message_id,
                response_model,
                stream_done_received,
                stop_reason,
                chunk_count,
                line_count,
                data_line_count,
                empty_line_count,
                text_char_count,
                tool_delta_count,
                time.time() - start_time,
            )
            stream_completed = True
        except GeneratorExit:
            stream_closed_by_generator = True
            logger.warning(
                "[AnthropicStream] ⚠️ generator 종료 | request_id=%s | message_id=%s | model=%s | "
                "done=%s | stop_reason=%s | chunks=%s | lines=%s | data_lines=%s | text_chars=%s | "
                "tool_deltas=%s | elapsed=%.3fs | last_payload=%s | last_choice=%s",
                stream_id,
                message_id,
                response_model,
                stream_done_received,
                stop_reason,
                chunk_count,
                line_count,
                data_line_count,
                text_char_count,
                tool_delta_count,
                time.time() - start_time,
                last_payload_sample,
                last_choice_summary,
            )
            raise
        except Exception as exc:
            logger.error(
                "[AnthropicStream] ❌ 예외 | request_id=%s | message_id=%s | model=%s | "
                "done=%s | chunks=%s | lines=%s | data_lines=%s | text_chars=%s | "
                "tool_deltas=%s | elapsed=%.3fs | error=%s",
                stream_id,
                message_id,
                response_model,
                stream_done_received,
                chunk_count,
                line_count,
                data_line_count,
                text_char_count,
                tool_delta_count,
                time.time() - start_time,
                exc,
                exc_info=True,
            )
            raise
        finally:
            logger.info(
                "[AnthropicStream] 🔒 close | request_id=%s | message_id=%s | model=%s | "
                "completed=%s | done=%s | generator_closed=%s | ended_without_done=%s | elapsed=%.3fs",
                stream_id,
                message_id,
                response_model,
                stream_completed,
                stream_done_received,
                stream_closed_by_generator,
                stream_ended_without_done,
                time.time() - start_time,
            )
            if isinstance(resp, Response):
                resp.close()
