# -*- coding: utf-8 -*-
"""
Anthropic 호환 API 라우트

/v1/messages 엔드포인트를 제공하여 Claude Code 등 Anthropic Messages API
클라이언트와의 호환을 지원합니다.
"""

import html
import inspect
import json
import logging
import re
import uuid
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse

import requests
from flask import Blueprint, Response, current_app, request, stream_with_context

from src.core.errors import ProxyRequestError
from src.handlers import AnthropicHandler, ChatHandler
from src.utils.opencode_anthropic import AnthropicMessagePassthrough, AnthropicSsePassthrough


logger = logging.getLogger(__name__)

anthropic_bp = Blueprint('anthropic', __name__, url_prefix='/v1')


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
    return "\n".join(parts)


def _latest_user_text(messages_value: Any) -> str:
    if not isinstance(messages_value, list):
        return ""
    for message in reversed(messages_value):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = _extract_text_content(message.get("content"))
        if text:
            return text
    return ""


def _extract_search_query(req: Dict[str, Any]) -> str:
    text = _latest_user_text(req.get("messages"))
    if not text:
        return ""
    match = re.search(r"<query>(.*?)</query>", text, flags=re.DOTALL)
    if match:
        return html.unescape(match.group(1)).strip()
    for pattern in (
        r"perform a web search for the query:\s*(.+)",
        r"web search(?: for)?[:\s]+(.+)",
        r"search(?: for)?[:\s]+(.+)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return text.strip()


def _duckduckgo_result_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path == "/l/":
        uddg = parse_qs(parsed.query).get("uddg", [])
        if uddg:
            return unquote(uddg[0])
    return raw_url


def _extract_duckduckgo_results(markup: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        flags=re.DOTALL,
    )
    for match in pattern.finditer(markup):
        title = re.sub(r"<[^>]+>", "", match.group("title"))
        title = html.unescape(title).strip()
        url = html.unescape(match.group("href")).strip()
        url = _duckduckgo_result_url(url)
        if title and url:
            results.append({"title": title, "url": url})
        if len(results) >= 5:
            break
    return results


def _has_web_search_tool(req: Dict[str, Any]) -> bool:
    tools = req.get("tools")
    if not isinstance(tools, list):
        return False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", "")).strip().lower()
        tool_type = str(tool.get("type", "")).strip().lower()
        if name in ("websearch", "web_search") or tool_type.startswith("web_search"):
            return True
    return False


def _is_web_search_tool_sampling_request(req: Dict[str, Any]) -> bool:
    if req.get("source") == "web_search_tool":
        return True
    if not _has_web_search_tool(req):
        return False
    text = _latest_user_text(req.get("messages")).strip().lower()
    return req.get("tool_choice") is not None and text.startswith(
        "perform a web search for the query:"
    )


def _local_web_search_content(
    query: str,
    results: List[Dict[str, str]],
    tool_use_id: str,
) -> List[Dict[str, Any]]:
    result_content = [
        {
            "type": "web_search_result",
            "title": item["title"],
            "url": item["url"],
        }
        for item in results
    ]
    return [
        {
            "type": "server_tool_use",
            "id": tool_use_id,
            "name": "web_search",
            "input": {"query": query},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": tool_use_id,
            "content": result_content,
        },
    ]


def _handle_local_web_search(req: Dict[str, Any]) -> Response | None:
    request_model = req.get("model")
    is_sampling_request = _is_web_search_tool_sampling_request(req)
    if not is_sampling_request and request_model != "cli-proxy-api-plus:gpt-5.5":
        return None
    if not is_sampling_request and not _has_web_search_tool(req):
        return None
    response_model = request_model if isinstance(request_model, str) else "cli-proxy-api-plus:gpt-5.5"

    query = _extract_search_query(req)
    if not query:
        query = "web search"
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        response.raise_for_status()
        results = _extract_duckduckgo_results(response.text)
    except requests.RequestException as exc:
        logger.warning("Local web search failed: query=%s error=%s", query, exc)
        results = []

    message_id = f"msg_{uuid.uuid4().hex}"
    tool_use_id = f"srvtoolu_{uuid.uuid4().hex}"
    content = _local_web_search_content(query, results, tool_use_id)
    server_tool_use = {"web_search_requests": 1, "web_fetch_requests": 0}
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "server_tool_use": server_tool_use,
    }
    if req.get("stream"):
        def sse(event: str, data: Dict[str, Any]) -> str:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        chunks = [
            sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": response_model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": usage,
                    },
                },
            ),
            sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "server_tool_use",
                        "id": tool_use_id,
                        "name": "web_search",
                        "input": {},
                    },
                },
            ),
            sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": json.dumps({"query": query}, ensure_ascii=False),
                    },
                },
            ),
            sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
            sse(
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": content[1],
                },
            ),
            sse("content_block_stop", {"type": "content_block_stop", "index": 1}),
            sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {
                        "output_tokens": 0,
                        "server_tool_use": server_tool_use,
                    },
                },
            ),
            sse("message_stop", {"type": "message_stop"}),
        ]
        return Response("".join(chunks), status=200, mimetype="text/event-stream")

    body = {
        "id": message_id,
        "type": "message",
        "role": "assistant",
        "model": response_model,
        "content": content,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": usage,
    }
    return Response(json.dumps(body, ensure_ascii=False), status=200, mimetype="application/json")


@anthropic_bp.route('/messages', methods=['POST'])
def messages():
    """Anthropic Messages API 호환 엔드포인트"""
    request_id = request.headers.get("x-request-id") or f"anth_{uuid.uuid4().hex[:12]}"

    req = request.get_json(force=True)
    local_web_search_response = _handle_local_web_search(req)
    if local_web_search_response is not None:
        return local_web_search_response

    api_config = current_app.config['api_config']
    chat_handler = ChatHandler(api_config)
    anthropic_handler = AnthropicHandler()

    requested_model = req.get('model')
    if not requested_model:
        error_body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "model is required"
            }
        }
        return Response(json.dumps(error_body), status=400, mimetype='application/json')

    logger.info(
        "Anthropic /v1/messages request: request_id=%s model=%s stream=%s tools=%s tool_choice=%s",
        request_id,
        req.get('model'),
        bool(req.get('stream', False)),
        len(req.get('tools', [])) if isinstance(req.get('tools'), list) else 0,
        'present' if req.get('tool_choice') is not None else 'absent'
    )

    proxied_req = anthropic_handler.build_proxy_request(req)
    tools_contract = proxied_req.pop('_tools_contract', None)
    if not proxied_req.get('messages'):
        error_body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "messages is required"
            }
        }
        return Response(json.dumps(error_body), status=400, mimetype='application/json')

    resp = chat_handler.handle_chat_request(proxied_req)
    if resp is None:
        logger.error("Anthropic upstream request failed before streaming: request_id=%s model=%s", request_id, requested_model)
        error_body = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "API request failed"
            }
        }
        return Response(json.dumps(error_body), status=500, mimetype='application/json')

    if isinstance(resp, ProxyRequestError):
        logger.warning(
            "Anthropic request rejected before upstream call: request_id=%s model=%s status=%s type=%s",
            request_id,
            requested_model,
            resp.status_code,
            resp.error_type
        )
        return Response(
            json.dumps(resp.to_anthropic_response()),
            status=resp.status_code,
            mimetype='application/json'
        )

    if proxied_req['stream']:
        if isinstance(resp, AnthropicSsePassthrough):
            logger.info(
                "Anthropic streaming passthrough start: request_id=%s model=%s",
                request_id,
                requested_model,
            )

            def generate_passthrough():
                for chunk in resp:
                    yield chunk

            return Response(
                stream_with_context(generate_passthrough()),
                mimetype='text/event-stream',
            )
        if inspect.isgenerator(resp) or hasattr(resp, 'iter_lines'):
            logger.info("Anthropic streaming response start: request_id=%s model=%s", request_id, requested_model)
            return Response(
                stream_with_context(anthropic_handler.stream_anthropic_response(resp, requested_model, request_id=request_id, tools_contract=tools_contract)),
                mimetype='text/event-stream'
            )

    if isinstance(resp, AnthropicMessagePassthrough):
        logger.info("Anthropic non-streaming passthrough success: request_id=%s model=%s", request_id, requested_model)
        return Response(
            json.dumps(resp.data, ensure_ascii=False),
            status=200,
            mimetype='application/json',
        )

    try:
        response_body = anthropic_handler.handle_non_streaming_response(resp, requested_model, tools_contract=tools_contract)
        logger.info("Anthropic non-streaming response success: request_id=%s model=%s", request_id, requested_model)
    except Exception as exc:
        logger.error(f"Anthropic 응답 변환 실패: request_id={request_id} model={requested_model} error={exc}", exc_info=True)
        error_body = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "Failed to transform API response"
            }
        }
        return Response(json.dumps(error_body), status=500, mimetype='application/json')

    return Response(json.dumps(response_body), status=200, mimetype='application/json')
