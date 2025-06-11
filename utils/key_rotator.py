import os
import logging
from threading import Lock

class KeyRotator:
    def __init__(self, provider_name: str, env_var_name: str):
        """
        API 키 순환 관리 클래스
        :param provider_name: 제공업체 이름 (Google, OpenRouter 등)
        :param env_var_name: 환경 변수 이름 (GOOGLE_API_KEYS 등)
        """
        self.provider = provider_name
        self.api_keys = self._load_api_keys(env_var_name)
        self.provider_name = provider_name
        self.current_index = 0
        self.lock = Lock()

    def _load_api_keys(self, env_var_name: str) -> list:
        """
        환경 변수에서 API 키 목록 로드
        :param env_var_name: 환경 변수 이름
        :return: API 키 리스트
        """
        keys_str = os.getenv(env_var_name, '')
        if not keys_str:
            print(f"Warning: {env_var_name} 환경 변수가 설정되지 않았습니다.")
            return []
        return [key.strip() for key in keys_str.split(',')]

    def get_next_key(self) -> str:
        """
        다음 API 키를 순환하며 반환
        :return: API 키 문자열
        """
        if not self.api_keys:
            return ""

        with self.lock:
            key = self.api_keys[self.current_index]
            key_ending = key[-8:]  # 마지막 8자리 추출
            current_index = self.current_index  # 현재 인덱스 저장
            self.current_index = (self.current_index + 1) % len(self.api_keys)
            # API 키 사용 정보 로깅
            logging.info(f"[KeyRotator] [{self.provider_name}] API_KEY_USED - key_ending: {key_ending}, index: {current_index}")
            return key

    def get_current_index(self) -> int:
        """
        현재 사용 중인 API 키의 인덱스 반환
        :return: 현재 키 인덱스
        """
        return self.current_index

    def log_key_count(self):
        """환경 변수 카운트 로깅"""
        logging.info(f"[KeyRotator] [{self.provider_name}] 환경 변수 카운트: {len(self.api_keys)}개")
