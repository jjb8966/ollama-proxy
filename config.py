# -*- coding: utf-8 -*-
"""
API 설정 모듈

각 LLM 제공업체의 API 키 순환기와 OAuth 관리자를 초기화합니다.
"""

from src.auth.key_rotator import KeyRotator
from src.auth.qwen_oauth import QwenOAuthManager


class ApiConfig:
    """
    API 설정 및 인증 관리 클래스
    
    각 제공업체별 KeyRotator 또는 OAuth 관리자를 초기화하고 관리합니다.
    """
    
    def __init__(self):
        """
        각 제공업체의 API 키 순환기를 초기화합니다.
        
        환경 변수에서 API 키를 로드하며, 키가 없는 제공업체는
        경고 로그만 출력하고 계속 진행합니다.
        """
        # 표준 API 키 순환기 초기화
        self.google_rotator = KeyRotator("Google", "GOOGLE_API_KEYS")
        self.google_rotator.log_key_count()
        
        self.openrouter_rotator = KeyRotator("OpenRouter", "OPENROUTER_API_KEYS")
        self.openrouter_rotator.log_key_count()
        
        self.akash_rotator = KeyRotator("Akash", "AKASH_API_KEYS")
        self.akash_rotator.log_key_count()
        
        self.cohere_rotator = KeyRotator("Cohere", "COHERE_API_KEYS")
        self.cohere_rotator.log_key_count()
        
        self.codestral_rotator = KeyRotator("Codestral", "CODESTRAL_API_KEYS")
        self.codestral_rotator.log_key_count()
        
        self.perplexity_rotator = KeyRotator("Perplexity", "PERPLEXITY_API_KEYS")
        self.perplexity_rotator.log_key_count()
        
        # Qwen은 OAuth 토큰 사용
        self.qwen_oauth_manager = QwenOAuthManager()
        self.qwen_oauth_manager.log_key_count()
