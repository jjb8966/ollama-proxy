# -*- coding: utf-8 -*-
"""
에러 처리 모듈

API 오류 응답 생성 및 에러 로깅을 위한 유틸리티를 제공합니다.
"""

from datetime import datetime


class ErrorHandler:
    """API 에러 처리를 위한 유틸리티 클래스"""
    
    @staticmethod
    def handle_api_error(provider: str, error: Exception, api_key: str = "") -> str:
        """
        API 오류를 표준화된 형식으로 처리합니다.
        
        Args:
            provider: API 제공업체 이름 (예: Google, OpenRouter)
            error: 발생한 예외 객체
            api_key: 사용된 API 키 (로그에는 마스킹 처리됨)
            
        Returns:
            표준화된 에러 메시지 문자열
        """
        masked_key = ErrorHandler.mask_api_key(api_key)
        return f"[{provider} API Error] Key: {masked_key} - {str(error)}"
    
    @staticmethod
    def mask_api_key(api_key: str) -> str:
        """
        API 키를 마스킹 처리합니다.
        
        보안을 위해 키의 앞 6자리와 뒤 4자리만 표시하고 중간은 마스킹합니다.
        
        Args:
            api_key: 마스킹할 API 키
            
        Returns:
            마스킹된 API 키 문자열
        """
        if not api_key:
            return "None"
        if len(api_key) > 10:
            return f"{api_key[:6]}...{api_key[-4:]}"
        return "***"

    @staticmethod
    def create_error_response(model: str, error_msg: str) -> dict:
        """
        Ollama 형식의 오류 응답을 생성합니다.
        
        Args:
            model: 요청된 모델 이름
            error_msg: 오류 메시지
            
        Returns:
            Ollama 형식의 오류 응답 딕셔너리
        """
        return {
            "model": model,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "message": {"role": "assistant", "content": f"오류 발생: {error_msg}"},
            "done": True,
            "error": error_msg
        }
