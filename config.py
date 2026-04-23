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
        
        
        # Qwen은 OAuth 토큰 사용
        self.qwen_oauth_manager = QwenOAuthManager()
        self.qwen_oauth_manager.log_key_count()

        # Antigravity는 별도 프록시 컨테이너를 거치며,
        # 이 rotator의 값은 upstream LLM 키가 아니라 프록시 API 토큰으로 사용됩니다.
        self.antigravity_rotator = KeyRotator("Antigravity", "ANTIGRAVITY_API_KEYS")
        self.antigravity_rotator.log_key_count()

        # Nvidia NIM (OpenAI 호환)
        self.nvidia_nim_rotator = KeyRotator("NvidiaNIM", "NVIDIA_NIM_API_KEYS")
        self.nvidia_nim_rotator.log_key_count()

        # CLI Proxy API (OpenAI 호환, 로컬)
        self.cli_proxy_api_rotator = KeyRotator("CLIProxyAPI", "CLI_PROXY_API_KEYS")
        self.cli_proxy_api_rotator.log_key_count()

        # CLI Proxy API GPT (OpenAI 호환, 외부)
        self.cli_proxy_api_gpt_rotator = KeyRotator("CLIProxyAPI_GPT", "CLI_PROXY_API_GPT_KEYS")
        self.cli_proxy_api_gpt_rotator.log_key_count()

        # Ollama Cloud (OpenAI 호환)
        # ENV 이름은 기존 운영 설정을 깨지 않기 위해 그대로 OLLAMA_API_KEYS 를 사용합니다.
        self.ollama_cloud_rotator = KeyRotator("OllamaCloud", "OLLAMA_API_KEYS")
        self.ollama_cloud_rotator.log_key_count()

        # OpenCode Go (OpenAI 호환)
        self.opencode_rotator = KeyRotator("OpenCode", "OPENCODE_API_KEYS")
        self.opencode_rotator.log_key_count()
