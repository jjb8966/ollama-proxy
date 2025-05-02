import os


class ApiConfig:
    _API_KEY_INDEX = 0

    def __init__(self):
        self.GOOGLE_API_KEYS = os.getenv('GOOGLE_API_KEYS', '')
        self.OPENROUTER_API_KEYS = os.getenv('OPENROUTER_API_KEYS', '')
        self.AKASH_API_KEYS = os.getenv('AKASH_API_KEYS', '')

        # API 키가 제대로 로드되었는지 확인하거나 로깅할 수 있습니다.
        if not self.GOOGLE_API_KEYS:
            print("Warning: GOOGLE_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.OPENROUTER_API_KEYS:
            print("Warning: OPENROUTER_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.AKASH_API_KEYS:
            print("Warning: AKASH_API_KEYS 환경 변수가 설정되지 않았습니다.")

        self.GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        self.AKASH_BASE_URL = "https://chatapi.akash.network/api/v1"

        self.API_KEYS = ['A', 'B', 'C']

    def get_api_config(self, requested_model):
        ApiConfig._API_KEY_INDEX = 0
        # API 설정을 가져오는 메서드
        if requested_model.startswith("google:"):
            self.API_KEYS = [key.strip() for key in self.GOOGLE_API_KEYS.split(',')]
            print('GOOGLE_API_KEYS Count =', len(self.API_KEYS))

            return {
                "model": requested_model.replace('google:', ''),
                "base_url": self.GOOGLE_BASE_URL,
                "api_key": self.API_KEYS[ApiConfig._API_KEY_INDEX],
                "api_key_index": ApiConfig._API_KEY_INDEX
            }
        elif requested_model.startswith("openrouter:"):
            self.API_KEYS = [key.strip() for key in self.OPENROUTER_API_KEYS.split(',')]
            print('OPENROUTER_API_KEYS Count =', len(self.API_KEYS))

            return {
                "model": requested_model.replace("openrouter:", ""),
                "base_url": self.OPENROUTER_BASE_URL,
                "api_key": self.API_KEYS[ApiConfig._API_KEY_INDEX],
                "api_key_index": ApiConfig._API_KEY_INDEX
            }
        elif requested_model.startswith("akash:"):
            self.API_KEYS = [key.strip() for key in self.AKASH_API_KEYS.split(',')]
            print('AKASH_API_KEYS Count =', len(self.API_KEYS))

            return {
                "model": requested_model.replace("akash:", ""),
                "base_url": self.AKASH_BASE_URL,
                "api_key": self.API_KEYS[ApiConfig._API_KEY_INDEX],
                "api_key_index": ApiConfig._API_KEY_INDEX
            }
        else:
            return {
                "model": requested_model,
                "base_url": None,
                "api_key": None
            }

    def get_next_api_key(self) -> dict:
        # API 키를 순환하며 반환하는 메서드
        if not self.API_KEYS:
            raise ValueError("No API keys available.")

        ApiConfig._API_KEY_INDEX = (ApiConfig._API_KEY_INDEX + 1) % len(self.API_KEYS)
        api_key = self.API_KEYS[ApiConfig._API_KEY_INDEX]

        return (api_key, ApiConfig._API_KEY_INDEX)
