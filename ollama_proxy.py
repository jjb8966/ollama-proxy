import json
import os
from dotenv import load_dotenv
from flask import Flask, request, Response, stream_with_context

from chat_handler import ChatHandler
from config import ApiConfig
from response_handler import ResponseHandler
from utils.logging_config import setup_logging

load_dotenv()

# 로깅 설정
logger = setup_logging()
app = Flask(__name__)
api_config = ApiConfig()


@app.route('/api/chat', methods=['POST'])
def chat():
    chat_handler = ChatHandler(api_config)
    response_handler = ResponseHandler()

    req = request.get_json(force=True)
    requested_model = req.get('model')

    resp = chat_handler.handle_chat_request(req)
    if resp is None:
        return Response(json.dumps({"error": "API request failed"}), status=500, mimetype='application/json')

    stream = req.get('stream', True)
    if stream:
        response = response_handler.handle_streaming_response(resp, requested_model)
        context = stream_with_context(response)
        return Response(context, mimetype='application/x-ndjson')
    else:
        ollama_response = response_handler.handle_non_streaming_response(resp, requested_model)
        return Response(json.dumps(ollama_response), mimetype='application/json')


@app.route('/v1/chat/completions', methods=['POST'])
def openai_chat_completions():
    chat_handler = ChatHandler(api_config)

    req = request.get_json(force=True)
    requested_model = req.get('model')
    if not requested_model:
        error_body = {
            "error": {
                "message": "model is required",
                "type": "invalid_request_error"
            }
        }
        return Response(json.dumps(error_body), status=400, mimetype='application/json')

    stream = req.get('stream', False)

    proxied_req = {
        "model": requested_model,
        "messages": req.get('messages'),
        "stream": stream
    }

    resp = chat_handler.handle_chat_request(proxied_req)
    if resp is None:
        error_body = {
            "error": {
                "message": "API request failed",
                "type": "api_error"
            }
        }
        return Response(json.dumps(error_body), status=500, mimetype='application/json')

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


@app.route('/api/tags', methods=['GET'])
def get_tags():
    """
    Ollama의 /api/tags 엔드포인트를 모방하여 로컬 모델 목록을 반환합니다.
    현재 구현에서는 예시 데이터를 정적으로 반환합니다.
    """
    # Ollama의 /api/tags 엔드포인트를 모방하여 사용 가능한 모델 목록 반환
    available_models = {
        "models": [
            {
                "name": "google:gemini-2.5-pro",
                "model": "google:gemini-2.5-pro"
            },
            {
                "name": "google:gemini-2.5-flash-preview-09-2025",
                "model": "google:gemini-2.5-flash-preview-09-2025"
            },
            {
                "name": "google:gemini-2.5-flash",
                "model": "google:gemini-2.5-flash"
            },
            {
                "name": "openrouter:qwen/qwen3-235b-a22b:free",
                "model": "openrouter:qwen/qwen3-235b-a22b:free"
            },
            {
                "name": "openrouter:qwen/qwen3-coder:free",
                "model": "openrouter:qwen/qwen3-coder:free"
            },
            {
                "name": "openrouter:minimax/minimax-m2:free",
                "model": "openrouter:minimax/minimax-m2:free"
            },
            {
                "name": "openrouter:tngtech/deepseek-r1t2-chimera:free",
                "model": "openrouter:tngtech/deepseek-r1t2-chimera:free"
            },
            {
                "name": "openrouter:kwaipilot/kat-coder-pro:free",
                "model": "openrouter:kwaipilot/kat-coder-pro:free"
            },
            {
                "name": "openrouter:x-ai/grok-4.1-fast:free",
                "model": "openrouter:x-ai/grok-4.1-fast:free"
            },
            {
                "name": "akash:gpt-oss-120b",
                "model": "akash:gpt-oss-120b"
            },
            {
                "name": "akash:DeepSeek-V3-1",
                "model": "akash:DeepSeek-V3-1"
            },
            {
                "name": "akash:Qwen3-235B-A22B-Instruct-2507-FP8",
                "model": "akash:Qwen3-235B-A22B-Instruct-2507-FP8"
            },
            {
                "name": "cohere:command-a-03-2025",
                "model": "cohere:command-a-03-2025"
            },
            {
                "name": "codestral:codestral-2508",
                "model": "codestral:codestral-2508"
            },
            {
                "name": "qwen:qwen3-coder-plus",
                "model": "qwen:qwen3-coder-plus"
            }
        ]
    }
    return Response(json.dumps(available_models), status=200, mimetype='application/json')


@app.route('/v1/models', methods=['GET'])
def list_models():
    tags_resp = get_tags()
    try:
        data = json.loads(tags_resp.get_data(as_text=True))
    except Exception:
        empty_body = {"object": "list", "data": []}
        return Response(json.dumps(empty_body), status=200, mimetype='application/json')

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

    return Response(json.dumps(result), status=200, mimetype='application/json')


@app.route('/', methods=['GET'])  # 루트 경로 추가
@app.route('/api/version', methods=['GET'])
def get_version():
    """
    Ollama의 /api/version 엔드포인트 및 루트 경로(/)를 모방하여 버전을 반환합니다.
    현재 구현에서는 예시 데이터를 정적으로 반환합니다.
    """
    logger.info("Received request for /api/version")
    logger.info("Received request for / or /api/version")
    # Ollama의 버전 엔드포인트를 모방
    version_response = {
        "version": "0.1.0-openai-proxy"  # 프록시 버전 정보 명시
    }
    return Response(json.dumps(version_response), status=200, mimetype='application/json')


if __name__ == '__main__':
    # 가상 환경 경로 확인 및 사용 권장 메시지
    venv_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'myenv'))
    python_executable = os.path.join(venv_path, 'bin', 'python')
    logger.info("--- Ollama Proxy Server ---")
    logger.info(f"Flask app: {__name__}")
    logger.info(f"Expected venv path: {venv_path}")
    if os.path.exists(python_executable):
        logger.info(f"To run with venv: {python_executable} {os.path.abspath(__file__)}")
    else:
        logger.warning(f"Virtual environment not found at {venv_path}. Running with system Python.")
        logger.warning("It's recommended to create and use a virtual environment.")
        logger.warning(f"Example creation: python3 -m venv {venv_path}")
        logger.warning(f"Example activation: source {venv_path}/bin/activate")

    # 환경 변수에서 포트 번호 가져오기 (개발 포트 5005)
    port = int(os.environ.get("PORT", 5005))
    # 디버그 모드는 환경 변수 `FLASK_DEBUG` 또는 기본값 False 사용
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    logger.info(f"Starting server on host 0.0.0.0, port {port}, debug mode: {debug_mode}")
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
