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

logger = logging.getLogger(__name__)


class AnthropicHandler:
    """Anthropic Messages API 형식 변환 핸들러"""

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
                assistant_tool_calls: List[Dict[str, Any]] = []

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")

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
                if assistant_tool_calls:
                    assistant_message["tool_calls"] = assistant_tool_calls
                normalized.append(assistant_message)
                continue

            if role == "user":
                pending_text: List[str] = []

                def flush_user_text() -> None:
                    if pending_text:
                        normalized.append(
                            {"role": "user", "content": "".join(pending_text)}
                        )
                        pending_text.clear()

                for block in content:
                    if not isinstance(block, dict):
                        continue
                    block_type = block.get("type")

                    if block_type == "text":
                        pending_text.append(str(block.get("text", "")))
                        continue

                    if block_type != "tool_result":
                        continue

                    flush_user_text()

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

                flush_user_text()
                continue

            normalized.append(
                {"role": role, "content": self._content_blocks_to_text(content)}
            )

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
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.get("description", ""),
                        "parameters": tool.get(
                            "input_schema", {"type": "object", "properties": {}}
                        ),
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

        return {
            "model": self.normalize_model_name(req.get("model")),
            "messages": system_messages + chat_messages,
            "stream": bool(req.get("stream", False)),
            "max_tokens": req.get("max_tokens"),
            "thinking_level": req.get("thinking_level", "minimal"),
            "tools": self._normalize_tools(req.get("tools")),
            "tool_choice": self._normalize_tool_choice(req.get("tool_choice")),
        }

    @staticmethod
    def _map_stop_reason(openai_reason: Optional[str]) -> str:
        if openai_reason == "length":
            return "max_tokens"
        if openai_reason == "tool_calls":
            return "tool_use"
        return "end_turn"

    def _build_anthropic_content(self, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        content_blocks: List[Dict[str, Any]] = []

        text_content = message.get("content")
        if isinstance(text_content, str) and text_content:
            content_blocks.append({"type": "text", "text": text_content})

        tool_calls = message.get("tool_calls", [])
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue
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

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": self._sanitize_tool_id(tool_call.get("id")),
                    "name": str(function_info.get("name", "")),
                    "input": tool_input,
                }
            )

        if not content_blocks:
            content_blocks.append({"type": "text", "text": ""})
        return content_blocks

    def handle_non_streaming_response(
        self, resp: Union[Dict[str, Any], Response], requested_model: str
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
            "content": self._build_anthropic_content(message),
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
    ) -> Generator[str, None, None]:
        message_id = f"msg_{uuid.uuid4().hex}"
        response_model = requested_model
        stop_reason = "end_turn"
        current_index = 0
        text_block_open = False
        tool_block_state: Dict[int, Dict[str, Any]] = {}
        stream_id = request_id or message_id
        start_time = time.time()
        first_chunk_time: Optional[float] = None
        last_chunk_time = start_time
        stream_done_received = False
        finish_reason_received = False
        blocks_closed = False
        line_count = 0
        data_line_count = 0
        empty_line_count = 0
        chunk_count = 0
        text_char_count = 0
        tool_delta_count = 0

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
            nonlocal text_block_open, stop_reason, blocks_closed
            if blocks_closed:
                return []

            events: List[str] = []

            # 먼저 모든 tool block을 시작 (arguments가 name보다 먼저 왔을 경우)
            for block_index in sorted(tool_block_state.keys()):
                state = tool_block_state[block_index]
                if not state.get("started") and state.get("name"):
                    events.extend(ensure_tool_block_started(block_index, state))

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

                text = delta.get("content", "")
                if text:
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

                for tc_index, tool_call in enumerate(delta.get("tool_calls", [])):
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
                    for event in flush_pending_tool_delta(block_index, state):
                        yield event

            for event in close_open_blocks():
                yield event

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
                "[AnthropicStream] 🔒 close | request_id=%s | message_id=%s | model=%s | elapsed=%.3fs",
                stream_id,
                message_id,
                response_model,
                time.time() - start_time,
            )
            if isinstance(resp, Response):
                resp.close()
