# -*- coding: utf-8 -*-
"""
에러 처리 모듈

API 오류 응답 생성 및 에러 로깅을 위한 유틸리티를 제공합니다.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class ErrorHandler:
    """API 에러 처리를 위한 유틸리티 클래스"""

    CONTEXT_OVERFLOW_PATTERNS = [
        re.compile(r"prompt is too long", re.IGNORECASE),
        re.compile(r"prompt too long", re.IGNORECASE),
        re.compile(r"input is too long for requested model", re.IGNORECASE),
        re.compile(r"exceeds the context window", re.IGNORECASE),
        re.compile(r"input token count.*exceeds the maximum", re.IGNORECASE),
        re.compile(r"maximum prompt length is \d+", re.IGNORECASE),
        re.compile(r"reduce the length of the messages", re.IGNORECASE),
        re.compile(r"maximum context length is \d+ tokens", re.IGNORECASE),
        re.compile(r"exceeds the available context size", re.IGNORECASE),
        re.compile(r"greater than the context length", re.IGNORECASE),
        re.compile(r"context window exceeds limit", re.IGNORECASE),
        re.compile(r"exceeded model token limit", re.IGNORECASE),
        re.compile(r"context[_ ]length[_ ]exceeded", re.IGNORECASE),
        re.compile(r"request entity too large", re.IGNORECASE),
        re.compile(r"context length is only \d+ tokens", re.IGNORECASE),
        re.compile(r"input length.*exceeds.*context length", re.IGNORECASE),
    ]
    
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

    @staticmethod
    def extract_error_message(response_body: str) -> str:
        if not response_body:
            return ""

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError:
            return response_body

        if not isinstance(parsed, dict):
            return response_body

        message = parsed.get("message")
        if isinstance(message, str) and message:
            return message

        error = parsed.get("error")
        if isinstance(error, str) and error:
            return error
        if isinstance(error, dict):
            error_message = error.get("message")
            if isinstance(error_message, str) and error_message:
                return error_message

        return response_body

    @staticmethod
    def extract_error_code(response_body: str) -> Optional[str]:
        if not response_body:
            return None

        try:
            parsed = json.loads(response_body)
        except json.JSONDecodeError:
            return None

        if not isinstance(parsed, dict):
            return None

        error = parsed.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str) and code:
                return code
        return None

    @classmethod
    def is_context_overflow_message(cls, message: str) -> bool:
        if not message:
            return False
        return any(pattern.search(message) for pattern in cls.CONTEXT_OVERFLOW_PATTERNS)

    @classmethod
    def is_context_overflow_response(cls, status_code: Optional[int], response_body: str) -> bool:
        if status_code == 413:
            return True
        if cls.extract_error_code(response_body) == "context_length_exceeded":
            return True
        message = cls.extract_error_message(response_body)
        return cls.is_context_overflow_message(message)


@dataclass(frozen=True)
class ProxyRequestError:
    """라우트별 표준 포맷으로 변환 가능한 요청 단계 오류."""

    model: str
    message: str
    status_code: int = 400
    error_type: str = "invalid_request_error"
    error_code: Optional[str] = None

    def to_openai_response(self) -> dict:
        error = {
            "message": self.message,
            "type": self.error_type
        }
        if self.error_code:
            error["code"] = self.error_code
        return {
            "error": {
                **error
            }
        }

    def to_anthropic_response(self) -> dict:
        return {
            "type": "error",
            "error": {
                "type": self.error_type,
                "message": self.message
            }
        }

    def to_ollama_response(self) -> dict:
        return ErrorHandler.create_error_response(self.model, self.message)
