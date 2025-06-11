import os
import logging
import fcntl
from threading import Lock

class FileLock:
    def __init__(self, filename):
        self.filename = filename
        self.file = None

    def __enter__(self):
        self.file = open(self.filename, 'w')
        fcntl.flock(self.file.fileno(), fcntl.LOCK_EX)

    def __exit__(self, exc_type, exc_val, exc_tb):
        fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()

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
        self.lock = Lock()  # for thread safety within the same process

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

        # We'll use a file to store the current index, shared among processes.
        lock_file = f"/tmp/key_rotator_{self.provider_name}.lock"
        index_file = f"/tmp/key_rotator_{self.provider_name}.index"

        new_index = 0
        # First, we use the thread lock to protect against concurrent threads in the same process.
        with self.lock:
            # Then use a file lock to protect against concurrent processes.
            with FileLock(lock_file):
                # Read the current index from the index_file
                if os.path.exists(index_file):
                    try:
                        with open(index_file, 'r') as f:
                            content = f.read().strip()
                            if content:
                                current_index = int(content)
                            else:
                                current_index = -1
                    except Exception as e:
                        logging.error(f"[KeyRotator] Failed to read index file {index_file}: {e}")
                        current_index = -1
                else:
                    current_index = -1

                new_index = (current_index + 1) % len(self.api_keys)

                # Write the new index back
                try:
                    with open(index_file, 'w') as f:
                        f.write(str(new_index))
                except Exception as e:
                    logging.error(f"[KeyRotator] Failed to write index file {index_file}: {e}")

        key = self.api_keys[new_index]
        key_ending = key[-8:]  # 마지막 8자리 추출
        # API 키 사용 정보 로깅 (프로세스 ID 포함)
        logging.info(f"[KeyRotator] [{self.provider_name}] API_KEY_USED - key_ending: {key_ending}, index: {new_index}, pid: {os.getpid()}")
        return key

    def get_current_index(self) -> int:
        """
        현재 사용 중인 API 키의 인덱스 반환
        :return: 현재 키 인덱스
        """
        # Note: This method now returns the last index used by the current process in the current thread? 
        # But we don't track it. We can remove this method or change it to return the shared index?
        # However, the shared index is stored in a file and we don't want to read it without a lock.
        # Since this method is not used in the logs, we return -1 to indicate it's not supported anymore.
        return -1

    def log_key_count(self):
        """환경 변수 카운트 로깅"""
        logging.info(f"[KeyRotator] [{self.provider_name}] 환경 변수 카운트: {len(self.api_keys)}개")
