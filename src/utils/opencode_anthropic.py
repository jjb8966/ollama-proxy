# -*- coding: utf-8 -*-
"""
OpenCode Anthropic Messages API 변환 유틸리티

OpenCode의 일부 모델(qwen3.7-max 등)은 oa-compat chat/completions 대신
Anthropic Messages API(/messages)만 지원합니다.
"""

import json
import time
import uuid
from typing import Any, Dict, Generator, Iterable, List, Optional


OPENCODE_ANTHROPIC_MESSAGES_MODELS = frozenset({"qwen3.7-max"})


def iter_utf8_response_lines(resp) -> Generator[str, None, None]:
    """업스트림 응답을 UTF-8로 안전하게 한 줄씩 읽습니다."""
    for raw_line in resp.iter_lines(decode_unicode=False):
        if not raw_line:
            continue
        if isinstance(raw_line, str):
            yield raw_line
            continue
        yield raw_line.decode("utf-8")


def read_utf8_response_json(resp) -> Dict[str, Any]:
    """업스트림 JSON 응답을 UTF-8로 안전하게 파싱합니다."""
    raw = resp.content
    if isinstance(raw, bytes):
        return json.loads(raw.decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw)
    return resp.json()


def uses_opencode_anthropic_messages(model: str) -> bool:
    return model in OPENCODE_ANTHROPIC_MESSAGES_MODELS


def _extract_openai_text(content: Any) -> str:
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
    return "\n".join(part for part in parts if part)


def build_anthropic_payload(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    stream: bool,
    max_tokens: Optional[int],
    tools: Any = None,
) -> Dict[str, Any]:
    system_parts: List[str] = []
    anthropic_messages: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue

        role = str(message.get("role", ""))
        if role == "system":
            text = _extract_openai_text(message.get("content"))
            if text:
                system_parts.append(text)
            continue

        if role == "user":
            content = message.get("content")
            if isinstance(content, list):
                blocks: List[Dict[str, Any]] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        blocks.append({"type": "text", "text": str(block.get("text", ""))})
                    elif block.get("type") == "image_url":
                        image_url = block.get("image_url")
                        url = image_url.get("url") if isinstance(image_url, dict) else image_url
                        if isinstance(url, str) and url:
                            blocks.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": url,
                                    },
                                }
                            )
                if blocks:
                    anthropic_messages.append({"role": "user", "content": blocks})
            else:
                text = _extract_openai_text(content)
                if text:
                    anthropic_messages.append({"role": "user", "content": text})
            continue

        if role == "assistant":
            text = _extract_openai_text(message.get("content"))
            reasoning = message.get("reasoning_content")
            tool_calls = message.get("tool_calls")
            blocks: List[Dict[str, Any]] = []
            if isinstance(reasoning, str) and reasoning:
                blocks.append({"type": "thinking", "thinking": reasoning})
            if text:
                blocks.append({"type": "text", "text": text})
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function_info = tool_call.get("function", {})
                    if not isinstance(function_info, dict):
                        function_info = {}
                    arguments = function_info.get("arguments", "{}")
                    try:
                        tool_input = json.loads(arguments) if isinstance(arguments, str) else arguments
                    except json.JSONDecodeError:
                        tool_input = {}
                    if not isinstance(tool_input, dict):
                        tool_input = {"input": tool_input}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(tool_call.get("id", "")),
                            "name": str(function_info.get("name", "tool")),
                            "input": tool_input,
                        }
                    )
            if blocks:
                anthropic_messages.append({"role": "assistant", "content": blocks})
            continue

        if role == "tool":
            tool_call_id = str(message.get("tool_call_id", "")).strip()
            if not tool_call_id:
                continue
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": _extract_openai_text(message.get("content")),
                        }
                    ],
                }
            )

    payload: Dict[str, Any] = {
        "model": model,
        "messages": anthropic_messages,
        "stream": stream,
        "max_tokens": max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else 4096,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if isinstance(tools, list) and tools:
        anthropic_tools: List[Dict[str, Any]] = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            function_info = tool.get("function", {})
            if not isinstance(function_info, dict):
                continue
            name = str(function_info.get("name", "")).strip()
            if not name:
                continue
            parameters = function_info.get("parameters", {})
            if not isinstance(parameters, dict):
                parameters = {}
            anthropic_tools.append(
                {
                    "name": name,
                    "description": str(function_info.get("description", "")),
                    "input_schema": parameters,
                }
            )
        if anthropic_tools:
            payload["tools"] = anthropic_tools
    return payload


def _map_stop_reason(stop_reason: Optional[str]) -> str:
    if stop_reason == "max_tokens":
        return "length"
    if stop_reason == "tool_use":
        return "tool_calls"
    return "stop"


def anthropic_response_to_openai(data: Dict[str, Any], requested_model: str) -> Dict[str, Any]:
    content_blocks = data.get("content", [])
    text_parts: List[str] = []
    reasoning_parts: List[str] = []
    tool_calls: List[Dict[str, Any]] = []

    if isinstance(content_blocks, list):
        for block in content_blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
            elif block_type == "thinking":
                thinking = block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    reasoning_parts.append(thinking)
            elif block_type == "tool_use":
                tool_calls.append(
                    {
                        "id": str(block.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": str(block.get("name", "tool")),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    }
                )

    message: Dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join(text_parts),
    }
    if reasoning_parts:
        message["reasoning_content"] = "\n".join(reasoning_parts)
    if tool_calls:
        message["tool_calls"] = tool_calls

    usage = data.get("usage", {})
    input_tokens = int(usage.get("input_tokens", 0) or 0)
    output_tokens = int(usage.get("output_tokens", 0) or 0)

    return {
        "id": str(data.get("id", f"chatcmpl-{uuid.uuid4().hex}")),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": _map_stop_reason(data.get("stop_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _emit_openai_chunk(
    completion_id: str,
    requested_model: str,
    delta: Dict[str, Any],
    finish_reason: Optional[str] = None,
) -> str:
    payload: Dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def stream_anthropic_sse_to_openai(
    lines: Iterable[str],
    requested_model: str,
) -> Generator[str, None, None]:
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"
    role_sent = False
    finish_reason: Optional[str] = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data_text = line[5:].strip()
        if not data_text:
            continue
        try:
            event = json.loads(data_text)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        if event_type == "message_start":
            if not role_sent:
                yield _emit_openai_chunk(
                    completion_id,
                    requested_model,
                    {"role": "assistant"},
                )
                role_sent = True
            continue

        if event_type == "content_block_delta":
            delta = event.get("delta", {})
            if not isinstance(delta, dict):
                continue
            delta_type = delta.get("type")
            if delta_type == "text_delta":
                text = delta.get("text")
                if isinstance(text, str) and text:
                    if not role_sent:
                        yield _emit_openai_chunk(
                            completion_id,
                            requested_model,
                            {"role": "assistant"},
                        )
                        role_sent = True
                    yield _emit_openai_chunk(
                        completion_id,
                        requested_model,
                        {"content": text},
                    )
            elif delta_type == "thinking_delta":
                thinking = delta.get("thinking")
                if isinstance(thinking, str) and thinking:
                    if not role_sent:
                        yield _emit_openai_chunk(
                            completion_id,
                            requested_model,
                            {"role": "assistant"},
                        )
                        role_sent = True
                    yield _emit_openai_chunk(
                        completion_id,
                        requested_model,
                        {"reasoning_content": thinking},
                    )
            continue

        if event_type == "message_delta":
            delta = event.get("delta", {})
            if isinstance(delta, dict):
                stop_reason = delta.get("stop_reason")
                if isinstance(stop_reason, str):
                    finish_reason = _map_stop_reason(stop_reason)

    yield _emit_openai_chunk(
        completion_id,
        requested_model,
        {},
        finish_reason=finish_reason or "stop",
    )
    yield "data: [DONE]\n\n"
