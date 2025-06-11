import requests
import time
from .error_handlers import ErrorHandler

class ApiClient:
    def __init__(self, key_rotator):
        self.key_rotator = key_rotator

    def post_request(self, url, payload, headers, stream=False, max_retries=100):
        """
        API POST 요청을 처리하고 응답을 반환합니다.
        :param url: 요청 URL
        :param payload: 요청 본문
        :param headers: 요청 헤더
        :param stream: 스트리밍 여부
        :param max_retries: 최대 재시도 횟수
        :return: 응답 객체 (성공 시), None (실패 시)
        """
        try_count = 0
        while try_count < max_retries:
            try:
                # 키 순환
                api_key = self.key_rotator.get_next_key()
                headers['Authorization'] = f'Bearer {api_key}'
                
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=stream,
                    timeout=(50, 300)
                )
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                # 오류 처리 및 키 순환
                error_msg = ErrorHandler.handle_api_error(
                    provider=self.key_rotator.provider,
                    error=e,
                    api_key=api_key
                )
                print(error_msg)
                time.sleep(1)
                try_count += 1
        return None
