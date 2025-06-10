import os
import multiprocessing
from multiprocessing import Manager, Lock

# multiprocessing 시작 방법 설정
multiprocessing.set_start_method('fork')

_manager = Manager()


class ApiConfig:
    _shared_indices = _manager.dict({
        'GOOGLE': 0,
        'OPENROUTER': 0,
        'AKASH': 0,
        'COHERE': 0
    })
    
    # 각 API 키 인덱스에 대한 락 (multiprocessing locks)
    _GOOGLE_LOCK = Lock()
    _OPENROUTER_LOCK = Lock()
    _AKASH_LOCK = Lock()
    _COHERE_LOCK = Lock()

    def __init__(self):
        self.GOOGLE_API_KEYS_EXP = os.getenv('GOOGLE_API_KEYS', '')
        self.OPENROUTER_API_KEYS_EXP = os.getenv('OPENROUTER_API_KEYS', '')
        self.AKASH_API_KEYS_EXP = os.getenv('AKASH_API_KEYS', '')
        self.COHERE_API_KEYS_EXP = os.getenv('COHERE_API_KEYS', '')

        # API 키가 제대로 로드되었는지 확인하거나 로깅할 수 있습니다.
        if not self.GOOGLE_API_KEYS_EXP:
            print("Warning: GOOGLE_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.OPENROUTER_API_KEYS_EXP:
            print("Warning: OPENROUTER_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.AKASH_API_KEYS_EXP:
            print("Warning: AKASH_API_KEYS 환경 변수가 설정되지 않았습니다.")
        if not self.COHERE_API_KEYS_EXP:
            print("Warning: COHERE_API_KEYS 환경 변수가 설정되지 않았습니다.")

        self.GOOGLE_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
        self.OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
        self.AKASH_BASE_URL = "https://chatapi.akash.network/api/v1"
        self.COHERE_BASE_URL = "https://api.cohere.ai/compatibility/v1"

        self.GOOGLE_API_KEYS = [key.strip() for key in self.GOOGLE_API_KEYS_EXP.split(',')]
        self.OPENROUTER_API_KEYS = [key.strip() for key in self.OPENROUTER_API_KEYS_EXP.split(',')]
        self.AKASH_API_KEYS = [key.strip() for key in self.AKASH_API_KEYS_EXP.split(',')]
        self.COHERE_API_KEYS = [key.strip() for key in self.COHERE_API_KEYS_EXP.split(',')]

        print('GOOGLE_API_KEYS Count =', len(self.GOOGLE_API_KEYS))
        print('OPENROUTER_API_KEYS Count =', len(self.OPENROUTER_API_KEYS))
        print('AKASH_API_KEYS Count =', len(self.AKASH_API_KEYS))
        print('COHERE_API_KEYS Count =', len(self.COHERE_API_KEYS))

    def get_api_config(self, requested_model):
        # API 설정을 가져오는 메서드
        if requested_model.startswith("google:"):
            model = requested_model.replace('google:', '')
            base_url = self.GOOGLE_BASE_URL
            
            with ApiConfig._GOOGLE_LOCK:
                api_key_index = ApiConfig._shared_indices['GOOGLE']
                api_key = self.GOOGLE_API_KEYS[api_key_index]
                ApiConfig._shared_indices['GOOGLE'] = (api_key_index + 1) % len(self.GOOGLE_API_KEYS)

        elif requested_model.startswith("openrouter:"):
            model = requested_model.replace('openrouter:', '')
            base_url = self.OPENROUTER_BASE_URL
            
            with ApiConfig._OPENROUTER_LOCK:
                api_key_index = ApiConfig._shared_indices['OPENROUTER']
                api_key = self.OPENROUTER_API_KEYS[api_key_index]
                ApiConfig._shared_indices['OPENROUTER'] = (api_key_index + 1) % len(self.OPENROUTER_API_KEYS)

        elif requested_model.startswith("akash:"):
            model = requested_model.replace('akash:', '')
            base_url = self.AKASH_BASE_URL
            
            with ApiConfig._AKASH_LOCK:
                api_key_index = ApiConfig._shared_indices['AKASH']
                api_key = self.AKASH_API_KEYS[api_key_index]
                ApiConfig._shared_indices['AKASH'] = (api_key_index + 1) % len(self.AKASH_API_KEYS)

        elif requested_model.startswith("cohere:"):
            model = requested_model.replace('cohere:', '')
            base_url = self.COHERE_BASE_URL

            with ApiConfig._COHERE_LOCK:
                api_key_index = ApiConfig._shared_indices['COHERE']
                api_key = self.COHERE_API_KEYS[api_key_index]
                ApiConfig._shared_indices['COHERE'] = (api_key_index + 1) % len(self.COHERE_API_KEYS)

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
            with ApiConfig._GOOGLE_LOCK:
                api_key_index = ApiConfig._shared_indices['GOOGLE']
                api_key = self.GOOGLE_API_KEYS[api_key_index]
                ApiConfig._shared_indices['GOOGLE'] = (ApiConfig._shared_indices['GOOGLE'] + 1) % len(self.GOOGLE_API_KEYS)

        elif base_url == self.OPENROUTER_BASE_URL:
            with ApiConfig._OPENROUTER_LOCK:
                api_key_index = ApiConfig._shared_indices['OPENROUTER']
                api_key = self.OPENROUTER_API_KEYS[api_key_index]
                ApiConfig._shared_indices['OPENROUTER'] = (ApiConfig._shared_indices['OPENROUTER'] + 1) % len(self.OPENROUTER_API_KEYS)

        elif base_url == self.AKASH_BASE_URL:
            with ApiConfig._AKASH_LOCK:
                api_key_index = ApiConfig._shared_indices['AKASH']
                api_key = self.AKASH_API_KEYS[api_key_index]
                ApiConfig._shared_indices['AKASH'] = (ApiConfig._shared_indices['AKASH'] + 1) % len(self.AKASH_API_KEYS)

        elif base_url == self.COHERE_BASE_URL:
            with ApiConfig._COHERE_LOCK:
                api_key_index = ApiConfig._shared_indices['COHERE']
                api_key = self.COHERE_API_KEYS[api_key_index]
                ApiConfig._shared_indices['COHERE'] = (ApiConfig._shared_indices['COHERE'] + 1) % len(self.COHERE_API_KEYS)

        return (api_key, api_key_index)
