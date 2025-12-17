import requests
import time
import logging
from .error_handlers import ErrorHandler

class ApiClient:
    def __init__(self, key_rotator):
        self.key_rotator = key_rotator

    def post_request(self, url, payload, headers, stream=False, max_retries=10):
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
                # API 요청 실패 로깅 추가
                # API 키 마스킹 (6자리 표시 + *** + 마지막 4자리)
                masked_key = 'None'
                if api_key:
                    if len(api_key) > 10:
                        masked_key = api_key[:6] + '***' + api_key[-4:]
                    else:
                        masked_key = '***'  # 짧은 키 처리
                
                # 응답 본문 추출 (에러 상세 정보 확인용)
                response_body = ''
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        response_body = e.response.text
                    except:
                        response_body = 'Unable to read response body'
                
                logging.error(
                    f"API 요청 실패 - URL: {url}, "
                    f"에러: {str(e)}, "
                    f"키: {masked_key}, "
                    f"응답: {response_body}, "
                    f"재시도: {try_count+1}/{max_retries}"
                )
                print(error_msg)  # 기존 출력 유지
                time.sleep(1)
                try_count += 1
        return None
