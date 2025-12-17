# -*- coding: utf-8 -*-
"""
Ollama Proxy Server - 메인 애플리케이션

여러 LLM 제공업체의 OpenAI 호환 API를 Ollama 및 OpenAI 형식으로 제공하는 프록시 서버입니다.

지원 제공업체:
- Google (Gemini)
- OpenRouter
- Akash
- Cohere
- Codestral (Mistral)
- Qwen (OAuth)
- Perplexity
"""

import os
import logging
from dotenv import load_dotenv
from flask import Flask

from config import ApiConfig
from src.core.logging import setup_logging
from src.routes import ollama_bp, openai_bp


def create_app() -> Flask:
    """
    Flask 애플리케이션 팩토리
    
    애플리케이션을 생성하고 설정, Blueprint를 등록합니다.
    
    Returns:
        설정된 Flask 앱 인스턴스
    """
    # 환경 변수 로드
    load_dotenv()
    
    # 로깅 설정
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Flask 앱 생성
    app = Flask(__name__)
    
    # 업로드 파일 크기 제한 (50MB)
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    
    # API 설정 초기화 및 앱 컨텍스트에 저장
    app.config['api_config'] = ApiConfig()
    
    # Blueprint 등록
    app.register_blueprint(ollama_bp)
    app.register_blueprint(openai_bp)
    
    logger.info("Flask 애플리케이션 초기화 완료")
    return app


# 애플리케이션 인스턴스 생성
app = create_app()


if __name__ == '__main__':
    logger = logging.getLogger(__name__)
    
    # 가상 환경 경로 확인 (개발 목적 정보)
    venv_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), 'venv')
    )
    
    logger.info("=" * 50)
    logger.info("Ollama Proxy Server 시작")
    logger.info("=" * 50)
    
    if os.path.exists(venv_path):
        logger.info(f"가상 환경: {venv_path}")
    else:
        logger.warning("가상 환경이 감지되지 않았습니다.")
        logger.warning(f"가상 환경 생성 명령: python3 -m venv {venv_path}")
    
    # 서버 설정
    port = int(os.environ.get("PORT", 5005))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    
    logger.info(f"서버 주소: http://0.0.0.0:{port}")
    logger.info(f"디버그 모드: {debug_mode}")
    logger.info("=" * 50)
    
    app.run(debug=debug_mode, host='0.0.0.0', port=port)
