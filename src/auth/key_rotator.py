# -*- coding: utf-8 -*-
"""
API 키 순환 관리 모듈

멀티 프로세스 환경에서 안전하게 API 키를 순환하며 사용할 수 있도록 합니다.
파일 기반 락을 사용하여 프로세스 간 동기화를 보장합니다.
"""

import os
import logging
import fcntl
from threading import Lock


class FileLock:
    """
    파일 기반 락 컨텍스트 매니저
    
    멀티 프로세스 환경에서 임계 영역을 보호하기 위해 사용합니다.
    """
    
    def __init__(self, filename: str):
        self.filename = filename
        self.file = None

    def __enter__(self):
        self.file = open(self.filename, 'w')
        fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


class KeyRotator:
    """
    API 키 순환 관리 클래스
    
    환경 변수에서 쉼표로 구분된 API 키 목록을 로드하고,
    요청마다 라운드 로빈 방식으로 다음 키를 반환합니다.
    
    멀티 프로세스 환경(gunicorn 등)에서 안전하게 동작합니다.
    
    Attributes:
        provider: 제공업체 이름 (로깅용)
        api_keys: API 키 목록
    """
    
    def __init__(self, provider_name: str, env_var_name: str):
        """
        Args:
            provider_name: 제공업체 이름 (예: Google, OpenRouter)
            env_var_name: API 키가 저장된 환경 변수 이름 (예: GOOGLE_API_KEYS)
        """
        self.provider = provider_name
        self.api_keys = self._load_api_keys(env_var_name)
        self._lock = Lock()  # 스레드 간 동기화용

    def _load_api_keys(self, env_var_name: str) -> list:
        """
        환경 변수에서 API 키 목록을 로드합니다.
        
        키는 쉼표(,)로 구분되어 있어야 합니다.
        """
        keys_str = os.getenv(env_var_name, '')
        if not keys_str:
            logging.warning(f"[KeyRotator] {env_var_name} 환경 변수가 설정되지 않았습니다.")
            return []
        return [key.strip() for key in keys_str.split(',') if key.strip()]

    def get_next_key(self) -> str:
        """
        다음 API 키를 순환하며 반환합니다.
        
        파일 기반 인덱스를 사용하여 멀티 프로세스 환경에서도
        모든 키가 균등하게 사용되도록 합니다.
        
        Returns:
            다음 순서의 API 키, 키가 없으면 빈 문자열
        """
        if not self.api_keys:
            return ""

        # 프로세스 간 공유를 위한 파일 경로
        lock_file = f"/tmp/key_rotator_{self.provider}.lock"
        index_file = f"/tmp/key_rotator_{self.provider}.index"

        new_index = 0
        
        # 스레드 락 + 파일 락으로 이중 보호
        with self._lock:
            with FileLock(lock_file):
                # 현재 인덱스 읽기
                current_index = self._read_index(index_file)
                new_index = (current_index + 1) % len(self.api_keys)
                
                # 새 인덱스 저장
                self._write_index(index_file, new_index)

        key = self.api_keys[new_index]
        key_suffix = key[-8:] if len(key) >= 8 else "***"
        
        logging.info(
            f"[KeyRotator] [{self.provider}] API_KEY_USED - "
            f"key_ending: {key_suffix}, index: {new_index}, pid: {os.getpid()}"
        )
        return key
    
    def _read_index(self, index_file: str) -> int:
        """인덱스 파일에서 현재 인덱스를 읽습니다."""
        if not os.path.exists(index_file):
            return -1
        try:
            with open(index_file, 'r') as f:
                content = f.read().strip()
                return int(content) if content else -1
        except (ValueError, IOError) as e:
            logging.error(f"[KeyRotator] 인덱스 파일 읽기 실패: {e}")
            return -1
    
    def _write_index(self, index_file: str, index: int) -> None:
        """인덱스 파일에 새 인덱스를 저장합니다."""
        try:
            with open(index_file, 'w') as f:
                f.write(str(index))
        except IOError as e:
            logging.error(f"[KeyRotator] 인덱스 파일 쓰기 실패: {e}")

    def log_key_count(self) -> None:
        """로드된 API 키 개수를 로깅합니다."""
        logging.info(f"[KeyRotator] [{self.provider}] API 키 수: {len(self.api_keys)}개")
