import os
from utils.key_rotator import KeyRotator

class ApiConfig:
    def __init__(self):
        # KeyRotator 인스턴스 생성
        self.google_rotator = KeyRotator("Google", "GOOGLE_API_KEYS")
        self.google_rotator.log_key_count()
        self.openrouter_rotator = KeyRotator("OpenRouter", "OPENROUTER_API_KEYS")
        self.openrouter_rotator.log_key_count()
        self.akash_rotator = KeyRotator("Akash", "AKASH_API_KEYS")
        self.akash_rotator.log_key_count()
        self.cohere_rotator = KeyRotator("Cohere", "COHERE_API_KEYS")
        self.cohere_rotator.log_key_count()

        # 기본 URL 설정
        self.GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        self.AKASH_BASE_URL = "https://chatapi.akash.network/api/v1"
        self.COHERE_BASE_URL = "https://api.cohere.ai/compatibility/v1"

    def get_api_config(self, requested_model):
        # API 설정을 가져오는 메서드
        if requested_model.startswith("google:"):
            model = requested_model.replace('google:', '')
            base_url = self.GOOGLE_BASE_URL
            api_key = self.google_rotator.get_next_key()
            api_key_index = self.google_rotator.get_current_index()

        elif requested_model.startswith("openrouter:"):
            model = requested_model.replace('openrouter:', '')
            base_url = self.OPENROUTER_BASE_URL
            api_key = self.openrouter_rotator.get_next_key()
            api_key_index = self.openrouter_rotator.get_current_index()

        elif requested_model.startswith("akash:"):
            model = requested_model.replace('akash:', '')
            base_url = self.AKASH_BASE_URL
            api_key = self.akash_rotator.get_next_key()
            api_key_index = self.akash_rotator.get_current_index()

        elif requested_model.startswith("cohere:"):
            model = requested_model.replace('cohere:', '')
            base_url = self.COHERE_BASE_URL
            api_key = self.cohere_rotator.get_next_key()
            api_key_index = self.cohere_rotator.get_current_index()

        else:
            model = requested_model
            base_url = None
            api_key = None
            api_key_index = None

        return {
            "model": model,
            "base_url": base_url,
            "api_key": api_key,
            "api_key_index": api_key_index
        }

    def get_next_api_key(self, base_url) -> tuple:
        # API 키를 순환하며 반환하는 메서드
        if base_url == self.GOOGLE_BASE_URL:
            api_key = self.google_rotator.get_next_key()
            api_key_index = self.google_rotator.get_current_index()
        elif base_url == self.OPENROUTER_BASE_URL:
            api_key = self.openrouter_rotator.get_next_key()
            api_key_index = self.openrouter_rotator.get_current_index()
        elif base_url == self.AKASH_BASE_URL:
            api_key = self.akash_rotator.get_next_key()
            api_key_index = self.akash_rotator.get_current_index()
        elif base_url == self.COHERE_BASE_URL:
            api_key = self.cohere_rotator.get_next_key()
            api_key_index = self.cohere_rotator.get_current_index()
        else:
            api_key = None
            api_key_index = None

        return (api_key, api_key_index)
