# -*- coding: utf-8 -*-
"""
OpenAI 호환 API 라우트

/v1/chat/completions, /v1/models 등 OpenAI 스타일 엔드포인트를 정의합니다.
"""

import json
import logging
from flask import Blueprint, request, Response, stream_with_context, current_app

from src.handlers.chat import ChatHandler


logger = logging.getLogger(__name__)

# Blueprint 생성
openai_bp = Blueprint('openai', __name__, url_prefix='/v1')


@openai_bp.route('/models', methods=['GET'])
def list_models():
    """
    모델 목록을 OpenAI 형식으로 반환합니다.
    
    OpenAI의 /v1/models 엔드포인트를 모방합니다.
    """
    # 내부적으로 /api/tags 응답을 가져와서 변환
    from src.routes.ollama import get_tags
    
    try:
        tags_resp = get_tags()
        data = json.loads(tags_resp.get_data(as_text=True))
    except Exception as e:
        logger.error(f"모델 목록 로드 실패: {e}")
        empty_response = {"object": "list", "data": []}
        return Response(
            json.dumps(empty_response), 
            status=200, 
            mimetype='application/json'
        )

    models = data.get("models", [])
    result = {
        "object": "list",
        "data": []
    }

    for m in models:
        model_id = m.get("model") or m.get("name")
        if not model_id:
            continue
        result["data"].append({
            "id": model_id,
            "object": "model",
            "created": 0,
            "owned_by": "proxy"
        })

    return Response(
        json.dumps(result), 
        status=200, 
        mimetype='application/json'
    )


@openai_bp.route('/chat/completions', methods=['POST'])
def chat_completions():
    """
    채팅 완료 요청을 처리합니다.
    
    OpenAI의 /v1/chat/completions 엔드포인트를 모방합니다.
    요청을 백엔드 API로 프록시하고 응답을 그대로 반환합니다.
    """
    api_config = current_app.config['api_config']
    chat_handler = ChatHandler(api_config)

    req = request.get_json(force=True)
    requested_model = req.get('model')
    
    # 모델 필수 검증
    if not requested_model:
        error_body = {
            "error": {
                "message": "model is required",
                "type": "invalid_request_error"
            }
        }
        return Response(
            json.dumps(error_body), 
            status=400, 
            mimetype='application/json'
        )

    stream = req.get('stream', False)

    # 프록시 요청 구성
    proxied_req = {
        "model": requested_model,
        "messages": req.get('messages'),
        "stream": stream
    }

    # API 요청 처리
    resp = chat_handler.handle_chat_request(proxied_req)
    if resp is None:
        error_body = {
            "error": {
                "message": "API request failed",
                "type": "api_error"
            }
        }
        return Response(
            json.dumps(error_body), 
            status=500, 
            mimetype='application/json'
        )

    # 응답 프록시 (OpenAI 형식 그대로 반환)
    if stream:
        def generate():
            try:
                for chunk in resp.iter_content(chunk_size=None):
                    if chunk:
                        yield chunk
            finally:
                resp.close()

        return Response(
            stream_with_context(generate()),
            mimetype=resp.headers.get('Content-Type', 'text/event-stream')
        )
    else:
        return Response(
            resp.content,
            status=resp.status_code,
            mimetype=resp.headers.get('Content-Type', 'application/json')
        )
