import os


class ApiConfig:
    _GOOGLE_API_KEY_INDEX = 0
    _OPENROUTER_API_KEY_INDEX = 0
    _AKASH_API_KEY_INDEX = 0

    def __init__(self):
        self.GOOGLE_API_KEYS_EXP = os.getenv('GOOGLE_API_KEYS', '')
        self.OPENROUTER_API_KEYS_EXP = os.getenv('OPENROUTER_API_KEYS', '')
        self.AKASH_API_KEYS_EXP = os.getenv('AKASH_API_KEYS', '')

        # API 키가 제대로 로드되었는지 확인하거나 로깅할 수 있습니다.
        if not self.GOOGLE_API_KEYS_EXP:
            print("Warning: GOOGLE_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.OPENROUTER_API_KEYS_EXP:
            print("Warning: OPENROUTER_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.AKASH_API_KEYS_EXP:
            print("Warning: AKASH_API_KEYS 환경 변수가 설정되지 않았습니다.")

        self.GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        self.AKASH_BASE_URL = "https://chatapi.akash.network/api/v1"

        self.GOOGLE_API_KEYS = [key.strip() for key in self.GOOGLE_API_KEYS_EXP.split(',')]
        self.OPENROUTER_API_KEYS = [key.strip() for key in self.OPENROUTER_API_KEYS_EXP.split(',')]
        self.AKASH_API_KEYS = [key.strip() for key in self.AKASH_API_KEYS_EXP.split(',')]
        print('GOOGLE_API_KEYS Count =', len(self.GOOGLE_API_KEYS))
        print('OPENROUTER_API_KEYS Count =', len(self.OPENROUTER_API_KEYS))
        print('AKASH_API_KEYS Count =', len(self.AKASH_API_KEYS))

    def get_api_config(self, requested_model):
        # API 설정을 가져오는 메서드
        if requested_model.startswith("google:"):
            model = requested_model.replace('google:', '')
            base_url = self.GOOGLE_BASE_URL
            api_key = self.GOOGLE_API_KEYS[ApiConfig._GOOGLE_API_KEY_INDEX]
            api_key_index = ApiConfig._GOOGLE_API_KEY_INDEX

            ApiConfig._GOOGLE_API_KEY_INDEX = (api_key_index + 1) % len(self.GOOGLE_API_KEYS)

        elif requested_model.startswith("openrouter:"):
            model = requested_model.replace('openrouter:', '')
            base_url = self.OPENROUTER_BASE_URL
            api_key = self.OPENROUTER_API_KEYS[ApiConfig._OPENROUTER_API_KEY_INDEX]
            api_key_index = ApiConfig._OPENROUTER_API_KEY_INDEX

            ApiConfig._OPENROUTER_API_KEY_INDEX = (api_key_index + 1) % len(self.OPENROUTER_API_KEYS)

        elif requested_model.startswith("akash:"):
            model = requested_model.replace('akash:', '')
            base_url = self.AKASH_BASE_URL
            api_key = self.AKASH_API_KEYS[ApiConfig._AKASH_API_KEY_INDEX]
            api_key_index = ApiConfig._AKASH_API_KEY_INDEX

            ApiConfig._AKASH_API_KEY_INDEX = (api_key_index + 1) % len(self.AKASH_API_KEYS)

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

    def get_next_api_key(self, base_url) -> dict:
        # API 키를 순환하며 반환하는 메서드
        if base_url == self.GOOGLE_BASE_URL:
            api_key = self.GOOGLE_API_KEYS[ApiConfig._GOOGLE_API_KEY_INDEX]
            api_key_index = ApiConfig._GOOGLE_API_KEY_INDEX
            ApiConfig._GOOGLE_API_KEY_INDEX = (ApiConfig._GOOGLE_API_KEY_INDEX + 1) % len(self.GOOGLE_API_KEYS)

        elif base_url == self.OPENROUTER_BASE_URL:
            api_key = self.OPENROUTER_API_KEYS[ApiConfig._OPENROUTER_API_KEY_INDEX]
            api_key_index = ApiConfig._OPENROUTER_API_KEY_INDEX
            ApiConfig._OPENROUTER_API_KEY_INDEX = (ApiConfig._OPENROUTER_API_KEY_INDEX + 1) % len(self.OPENROUTER_API_KEYS)

        elif base_url == self.AKASH_BASE_URL:
            api_key = self.AKASH_API_KEYS[ApiConfig._AKASH_API_KEY_INDEX]
            api_key_index = ApiConfig._AKASH_API_KEY_INDEX
            ApiConfig._AKASH_API_KEY_INDEX = (ApiConfig._AKASH_API_KEY_INDEX + 1) % len(self.AKASH_API_KEYS)

        return (api_key, api_key_index)
