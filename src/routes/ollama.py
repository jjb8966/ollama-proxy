# -*- coding: utf-8 -*-
"""
Ollama 호환 API 라우트

/api/chat, /api/tags, /api/version 등 Ollama 스타일 엔드포인트를 정의합니다.
"""

import json
import logging
import os
from flask import Blueprint, request, Response, stream_with_context, current_app

from src.handlers.chat import ChatHandler
from src.handlers.response import ResponseHandler


logger = logging.getLogger(__name__)

# Blueprint 생성
ollama_bp = Blueprint('ollama', __name__)


def _load_models() -> list:
    """models.json 파일에서 모델 목록을 로드합니다."""
    models_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'models.json'
    )
    try:
        with open(models_path, 'r') as f:
            data = json.load(f)
            return data.get('models', [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"models.json 로드 실패, 기본 목록 사용: {e}")
        return []


@ollama_bp.route('/', methods=['GET'])
def root_status():
    """
    루트 상태 응답.
    
    Ollama가 동작 중임을 알려주는 텍스트를 반환합니다.
    """
    return Response(
        "Ollama is running",
        status=200,
        mimetype='text/plain'
    )


@ollama_bp.route('/api/version', methods=['GET'])
def get_version():
    """
    버전 정보를 반환합니다.
    
    Ollama의 /api/version 및 루트 경로(/)를 모방합니다.
    """
    logger.info("버전 정보 요청 수신")
    version_response = {
        "version": "0.1.0-openai-proxy"
    }
    return Response(
        json.dumps(version_response), 
        status=200, 
        mimetype='application/json'
    )


@ollama_bp.route('/api/tags', methods=['GET'])
def get_tags():
    """
    사용 가능한 모델 목록을 반환합니다.
    
    Ollama의 /api/tags 엔드포인트를 모방합니다.
    models.json 파일에서 모델 목록을 로드합니다.
    """
    models = _load_models()
    
    # models.json이 없으면 기본 목록 반환
    if not models:
        models = [
            {"name": "google:gemini-3-flash-preview", "model": "google:gemini-3-flash-preview"},
            {"name": "google:gemini-2.5-flash", "model": "google:gemini-2.5-flash"},
            {"name": "openrouter:mistralai/devstral-2512:free", "model": "openrouter:mistralai/devstral-2512:free"},
            {"name": "cohere:command-a-03-2025", "model": "cohere:command-a-03-2025"},
            {"name": "qwen:qwen3-coder-plus", "model": "qwen:qwen3-coder-plus"},
            {"name": "perplexity:sonar", "model": "perplexity:sonar"}
        ]
    
    response = {"models": models}
    return Response(
        json.dumps(response), 
        status=200, 
        mimetype='application/json'
    )


@ollama_bp.route('/api/chat', methods=['POST'])
def chat():
    """
    채팅 요청을 처리합니다.
    
    Ollama 형식의 요청을 받아 OpenAI 호환 API로 전달하고,
    응답을 Ollama 형식으로 변환하여 반환합니다.
    
    스트리밍/비스트리밍 모드를 모두 지원합니다.
    """
    api_config = current_app.config['api_config']
    chat_handler = ChatHandler(api_config)
    response_handler = ResponseHandler()

    req = request.get_json(force=True)
    requested_model = req.get('model')
    stream = req.get('stream', True)

    # API 요청 처리
    resp = chat_handler.handle_chat_request(req)
    if resp is None:
        error_response = {"error": "API request failed"}
        return Response(
            json.dumps(error_response), 
            status=500, 
            mimetype='application/json'
        )

    # 스트리밍/비스트리밍 응답 처리
    if stream:
        generator = response_handler.handle_streaming_response(resp, requested_model)
        return Response(
            stream_with_context(generator), 
            mimetype='application/x-ndjson'
        )
    else:
        ollama_response = response_handler.handle_non_streaming_response(
            resp, 
            requested_model
        )
        return Response(
            json.dumps(ollama_response), 
            mimetype='application/json'
        )
