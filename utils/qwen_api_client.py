"""
Qwen API Client

OAuth 토큰을 사용하여 Qwen API에 요청하고,
401 에러 시 토큰을 갱신 후 재시도합니다.
"""

import requests
import time
import logging
from .error_handlers import ErrorHandler


class QwenApiClient:
    """Qwen OAuth를 사용하는 API 클라이언트"""
    
    def __init__(self, oauth_manager):
        """
        Args:
            oauth_manager: QwenOAuthManager 인스턴스
        """
        self.oauth_manager = oauth_manager
    
    def post_request(self, url, payload, headers, stream=False, max_retries=10):
        """
        API POST 요청을 처리하고 응답을 반환합니다.
        401 에러 시 토큰을 갱신하고 재시도합니다.
        
        :param url: 요청 URL
        :param payload: 요청 본문
        :param headers: 요청 헤더
        :param stream: 스트리밍 여부
        :param max_retries: 최대 재시도 횟수
        :return: 응답 객체 (성공 시), None (실패 시)
        """
        try_count = 0
        token_refreshed = False
        
        while try_count < max_retries:
            try:
                # OAuth 토큰 사용
                api_key = self.oauth_manager.get_access_token()
                if not api_key:
                    logging.error("[QwenApiClient] access_token이 없습니다.")
                    return None
                
                headers['Authorization'] = f'Bearer {api_key}'
                
                # API 키 마스킹 로깅
                masked_key = self._mask_key(api_key)
                logging.info(f"[QwenApiClient] API 요청 - key_ending: {masked_key}")
                
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=stream,
                    timeout=(50, 300)
                )
                
                # 401 Unauthorized - 토큰 갱신 필요
                if resp.status_code == 401 and not token_refreshed:
                    logging.warning("[QwenApiClient] 401 Unauthorized - 토큰 갱신 시도")
                    if self.oauth_manager.refresh_access_token():
                        token_refreshed = True
                        continue  # 재시도 횟수 증가 없이 다시 시도
                    else:
                        logging.error("[QwenApiClient] 토큰 갱신 실패")
                
                resp.raise_for_status()
                return resp
                
            except requests.exceptions.RequestException as e:
                # 401 에러이고 아직 토큰 갱신을 안 했으면 갱신 시도
                if hasattr(e, 'response') and e.response is not None:
                    if e.response.status_code == 401 and not token_refreshed:
                        logging.warning("[QwenApiClient] 401 Unauthorized - 토큰 갱신 시도")
                        if self.oauth_manager.refresh_access_token():
                            token_refreshed = True
                            continue  # 재시도
                        else:
                            logging.error("[QwenApiClient] 토큰 갱신 실패")
                
                # 오류 처리 및 로깅
                error_msg = ErrorHandler.handle_api_error(
                    provider="Qwen",
                    error=e,
                    api_key=api_key if 'api_key' in dir() else None
                )
                
                masked_key = self._mask_key(api_key) if 'api_key' in dir() and api_key else 'None'
                
                # 응답 본문 추출
                response_body = ''
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        response_body = e.response.text
                    except:
                        response_body = 'Unable to read response body'
                
                logging.error(
                    f"[QwenApiClient] API 요청 실패 - URL: {url}, "
                    f"에러: {str(e)}, "
                    f"키: {masked_key}, "
                    f"응답: {response_body}, "
                    f"재시도: {try_count+1}/{max_retries}"
                )
                print(error_msg)
                time.sleep(1)
                try_count += 1
                
        return None
    
    def _mask_key(self, api_key):
        """API 키 마스킹"""
        if not api_key:
            return 'None'
        if len(api_key) > 10:
            return api_key[-8:]
        return '***'
