# -*- coding: utf-8 -*-
"""
Anthropic 호환 API 라우트

/v1/messages 엔드포인트를 제공하여 Claude Code 등 Anthropic Messages API
클라이언트와의 호환을 지원합니다.
"""

import inspect
import json
import logging
import uuid
from flask import Blueprint, Response, current_app, request, stream_with_context

from src.handlers import AnthropicHandler, ChatHandler


logger = logging.getLogger(__name__)

anthropic_bp = Blueprint('anthropic', __name__, url_prefix='/v1')


@anthropic_bp.route('/messages', methods=['POST'])
def messages():
    """Anthropic Messages API 호환 엔드포인트"""
    api_config = current_app.config['api_config']
    chat_handler = ChatHandler(api_config)
    anthropic_handler = AnthropicHandler()
    request_id = request.headers.get("x-request-id") or f"anth_{uuid.uuid4().hex[:12]}"

    req = request.get_json(force=True)
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

    if proxied_req['stream'] and (inspect.isgenerator(resp) or hasattr(resp, 'iter_lines')):
        logger.info("Anthropic streaming response start: request_id=%s model=%s", request_id, requested_model)
        return Response(
            stream_with_context(anthropic_handler.stream_anthropic_response(resp, requested_model, request_id=request_id)),
            mimetype='text/event-stream'
        )

    try:
        response_body = anthropic_handler.handle_non_streaming_response(resp, requested_model)
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
