# -*- coding: utf-8 -*-
"""
Anthropic 호환 API 라우트

/v1/messages 엔드포인트를 통해 Claude Messages API 형식의 요청을 수신하고,
내부적으로 OpenAI 호환 API로 변환하여 처리한 뒤 Anthropic 형식으로 응답합니다.
"""

import json
import logging
import uuid
from typing import Dict, List, Optional, Generator

from flask import Blueprint, request, Response, stream_with_context, current_app

from src.handlers.chat import ChatHandler

logger = logging.getLogger(__name__)

anthropic_bp = Blueprint("anthropic", __name__, url_prefix="/v1")

FINISH_REASON_MAP = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "end_turn",
    "tool_calls": "tool_use",
}


def _generate_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _extract_system_text(system) -> Optional[str]:
    """system 필드에서 텍스트를 추출합니다. 문자열 또는 content block 배열 모두 지원."""
    if system is None:
        return None
    if isinstance(system, str):
        return system
    if isinstance(system, list):
        parts = []
        for block in system:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n\n".join(parts) if parts else None
    return str(system)


def _convert_content_block(block: dict) -> dict:
    """Anthropic content block → OpenAI content part 변환."""
    block_type = block.get("type")

    if block_type == "text":
        return {"type": "text", "text": block.get("text", "")}

    if block_type == "image":
        source = block.get("source", {})
        source_type = source.get("type")

        if source_type == "base64":
            media_type = source.get("media_type", "image/png")
            data = source.get("data", "")
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            }
        if source_type == "url":
            return {
                "type": "image_url",
                "image_url": {"url": source.get("url", "")},
            }

    return {"type": "text", "text": str(block)}


def _convert_anthropic_to_openai_messages(anthropic_request: dict) -> List[Dict]:
    messages: List[Dict] = []

    system_text = _extract_system_text(anthropic_request.get("system"))
    if system_text:
        messages.append({"role": "system", "content": system_text})

    for msg in anthropic_request.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")

        if isinstance(content, str):
            messages.append({"role": role, "content": content})
        elif isinstance(content, list):
            converted = [
                _convert_content_block(b) for b in content if isinstance(b, dict)
            ]
            has_image = any(b.get("type") == "image_url" for b in converted)
            if has_image:
                messages.append({"role": role, "content": converted})
            else:
                text = "\n".join(
                    b.get("text", "") for b in converted if b.get("type") == "text"
                )
                messages.append({"role": role, "content": text})
        else:
            messages.append({"role": role, "content": str(content) if content else ""})

    return messages


def _build_proxied_request(req: dict, openai_messages: list) -> dict:
    proxied = {
        "model": req.get("model"),
        "messages": openai_messages,
        "stream": req.get("stream", False),
    }

    if "max_tokens" in req:
        proxied["max_tokens"] = req["max_tokens"]
    if "temperature" in req:
        proxied["temperature"] = req["temperature"]
    if "top_p" in req:
        proxied["top_p"] = req["top_p"]
    if "top_k" in req:
        proxied["top_k"] = req["top_k"]
    if "stop_sequences" in req:
        proxied["stop"] = req["stop_sequences"]

    return proxied


def _map_stop_reason(finish_reason: Optional[str]) -> str:
    if not finish_reason:
        return "end_turn"
    return FINISH_REASON_MAP.get(finish_reason, "end_turn")


def _create_anthropic_response(openai_response: dict, model: str) -> dict:
    content_text = ""
    stop_reason = "end_turn"

    if "choices" in openai_response and openai_response["choices"]:
        choice = openai_response["choices"][0]
        message = choice.get("message", {})
        content_text = message.get("content", "")
        stop_reason = _map_stop_reason(choice.get("finish_reason"))

    usage = openai_response.get("usage", {})

    return {
        "id": _generate_message_id(),
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
        },
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _filter_thought_chunk(text: str, in_tag: bool) -> tuple:
    """스트리밍 청크에서 <thought>...</thought> 내용을 제거합니다."""
    result = []
    i = 0
    while i < len(text):
        if in_tag:
            end_tag = "</thought>"
            if text[i:].startswith(end_tag):
                in_tag = False
                i += len(end_tag)
                continue
            i += 1
            continue

        start_tag = "<thought>"
        if text[i:].startswith(start_tag):
            in_tag = True
            i += len(start_tag)
            continue

        result.append(text[i])
        i += 1

    return "".join(result), in_tag


def _generate_streaming_response(
    openai_stream, model: str
) -> Generator[str, None, None]:
    message_id = _generate_message_id()
    output_tokens = 0
    in_thought_tag = False

    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )

    yield _sse(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    )

    final_stop_reason = "end_turn"

    try:
        for chunk in openai_stream.iter_lines():
            if not chunk:
                continue

            decoded = chunk.decode("utf-8").strip()
            if not decoded or decoded.startswith(":"):
                continue
            if decoded.startswith("data: "):
                decoded = decoded[6:]
            if decoded == "[DONE]":
                break

            try:
                data = json.loads(decoded)
            except json.JSONDecodeError:
                continue

            if "choices" not in data or not data["choices"]:
                continue

            choice = data["choices"][0]
            delta = choice.get("delta", {})
            text = delta.get("content", "")

            if not text:
                text = delta.get("text", "")
            if not text:
                text = delta.get("reasoning", "")

            if text and ("<thought>" in text or "</thought>" in text or in_thought_tag):
                text, in_thought_tag = _filter_thought_chunk(text, in_thought_tag)

            if text:
                output_tokens += 1
                yield _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )

            finish_reason = choice.get("finish_reason")
            if finish_reason:
                final_stop_reason = _map_stop_reason(finish_reason)
                break
    finally:
        openai_stream.close()

    yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})

    yield _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": final_stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )

    yield _sse("message_stop", {"type": "message_stop"})


def _anthropic_error(error_type: str, message: str, status: int) -> Response:
    return Response(
        json.dumps(
            {"type": "error", "error": {"type": error_type, "message": message}}
        ),
        status=status,
        mimetype="application/json",
    )


@anthropic_bp.route("/messages", methods=["POST"])
def create_message():
    """Anthropic /v1/messages 엔드포인트."""
    api_config = current_app.config["api_config"]
    chat_handler = ChatHandler(api_config)

    req = request.get_json(force=True)
    requested_model = req.get("model")

    if not requested_model:
        return _anthropic_error("invalid_request_error", "model is required", 400)

    if not req.get("messages"):
        return _anthropic_error("invalid_request_error", "messages is required", 400)

    stream = req.get("stream", False)

    openai_messages = _convert_anthropic_to_openai_messages(req)
    proxied_req = _build_proxied_request(req, openai_messages)

    resp = chat_handler.handle_chat_request(proxied_req)
    if resp is None:
        return _anthropic_error("api_error", "API request failed", 500)

    if stream:
        return Response(
            stream_with_context(_generate_streaming_response(resp, requested_model)),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        openai_response = resp.json()
        anthropic_response = _create_anthropic_response(
            openai_response, requested_model
        )
        return Response(
            json.dumps(anthropic_response),
            status=200,
            mimetype="application/json",
        )
    except Exception as e:
        logger.error(f"응답 변환 실패: {e}", exc_info=True)
        return _anthropic_error(
            "api_error", f"Response conversion failed: {str(e)}", 500
        )
