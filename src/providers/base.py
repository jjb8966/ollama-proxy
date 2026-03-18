# -*- coding: utf-8 -*-
"""
API 클라이언트 베이스 모듈

모든 API 클라이언트의 공통 기능을 정의하는 추상 베이스 클래스입니다.
"""

import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

import requests

from src.core.errors import ErrorHandler


class BaseApiClient(ABC):
    """
    API 클라이언트 추상 베이스 클래스
    
    모든 제공업체별 API 클라이언트가 상속해야 하는 기본 클래스입니다.
    공통 에러 처리, 재시도 로직, 로깅 기능을 제공합니다.
    """
    
    # API 요청 타임아웃 설정 (연결 타임아웃, 읽기 타임아웃)
    REQUEST_TIMEOUT = (50, 300)
    
    def __init__(self, provider_name: str):
        """
        Args:
            provider_name: 제공업체 이름 (로깅용)
        """
        self.provider_name = provider_name
    
    @abstractmethod
    def _get_api_key(self) -> Optional[str]:
        """
        API 키를 가져옵니다.
        
        각 구현체에서 키 순환, OAuth 등 방식에 맞게 구현해야 합니다.
        
        Returns:
            API 키 문자열, 없으면 None
        """
        pass
    
    @abstractmethod
    def _on_auth_failure(self) -> bool:
        """
        인증 실패(401) 시 호출됩니다.
        
        토큰 갱신 등의 복구 로직을 구현합니다.
        
        Returns:
            복구 성공 여부 (True면 재시도)
        """
        pass

    def _get_key_log_context(self, api_key: str) -> Dict[str, str]:
        """키 관련 비민감 로그 컨텍스트를 반환합니다."""
        return {}

    def _mark_key_failure(self, api_key: str, is_rate_limit: bool = False, retry_after: Optional[int] = None) -> None:
        """키 실패를 기록합니다. 기본 구현은 no-op 입니다."""
        return None
    
    def post_request(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        stream: bool = False,
        max_retries: int = 10
    ) -> Optional[requests.Response]:
        """
        API POST 요청을 수행합니다.
        
        실패 시 자동으로 재시도하며, 인증 실패 시 _on_auth_failure를 호출합니다.
        
        Args:
            url: 요청 URL
            payload: 요청 본문 (JSON)
            headers: 요청 헤더
            stream: 스트리밍 응답 여부
            max_retries: 최대 재시도 횟수
            
        Returns:
            성공 시 Response 객체, 실패 시 None
        """
        try_count = 0
        auth_retry_done = False
        
        while try_count < max_retries:
            api_key = self._get_api_key()
            if not api_key:
                logging.error(f"[{self.provider_name}] API 키를 가져올 수 없습니다.")
                return None

            key_context = self._get_key_log_context(api_key)
            context_suffix = ""
            if key_context:
                context_suffix = " | " + " | ".join(
                    f"{key}={value}" for key, value in key_context.items()
                )
            
            headers['Authorization'] = f'Bearer {api_key}'
            
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    stream=stream,
                    timeout=self.REQUEST_TIMEOUT
                )
                
                # HTTP 상태 및 헤더 로깅
                logging.info(
                    f"[HTTP] 📥 응답 | status={resp.status_code} | provider={self.provider_name}{context_suffix}"
                )
                
                # Rate Limit 관련 헤더 추적
                if resp.status_code == 429:
                    retry_after = resp.headers.get('Retry-After', 'N/A')
                    x_ratelimit_reset = resp.headers.get('X-RateLimit-Reset', 'N/A')
                    x_ratelimit_remaining = resp.headers.get('X-RateLimit-Remaining', 'N/A')
                    retry_after_int = int(retry_after) if str(retry_after).isdigit() else None
                    self._mark_key_failure(api_key, is_rate_limit=True, retry_after=retry_after_int)
                    logging.warning(
                        f"[HTTP] 🚦 Rate Limit | provider={self.provider_name} | "
                        f"retry_after={retry_after} | reset={x_ratelimit_reset} | "
                        f"remaining={x_ratelimit_remaining}{context_suffix}"
                    )
                    logging.debug(f"[HTTP] Rate Limit 헤더: {dict(resp.headers)}")
                
                # 5xx 서버 오류 로깅
                if 500 <= resp.status_code < 600:
                    logging.error(
                        f"[HTTP] ❌ 서버 오류 | status={resp.status_code} | "
                        f"provider={self.provider_name}"
                    )
                
                # 401 인증 실패 처리
                if resp.status_code == 401 and not auth_retry_done:
                    self._mark_key_failure(api_key)
                    logging.warning(f"[{self.provider_name}] 401 Unauthorized - 인증 복구 시도")
                    if self._on_auth_failure():
                        auth_retry_done = True
                        continue  # try_count 증가 없이 재시도
                
                resp.raise_for_status()
                return resp
                
            except requests.exceptions.RequestException as e:
                self._log_request_error(url, api_key, e, try_count, max_retries)
                time.sleep(1)
                try_count += 1
        
        return None
    
    def _log_request_error(
        self,
        url: str,
        api_key: str,
        error: Exception,
        try_count: int,
        max_retries: int
    ) -> None:
        """API 요청 실패를 로깅합니다."""
        masked_key = ErrorHandler.mask_api_key(api_key)
        key_context = self._get_key_log_context(api_key)
        context_suffix = ""
        if key_context:
            context_suffix = " | " + " | ".join(
                f"{key}={value}" for key, value in key_context.items()
            )
        
        # 응답 본문 추출
        response_body = ''
        if hasattr(error, 'response') and error.response is not None:
            try:
                response_body = error.response.text[:500]  # 최대 500자
            except Exception:
                response_body = 'Unable to read response body'
        
        # 에러 메시지 생성
        error_msg = ErrorHandler.handle_api_error(
            provider=self.provider_name,
            error=error,
            api_key=api_key
        )
        
        logging.error(
            f"[{self.provider_name}] API 요청 실패 - "
            f"URL: {url}, 에러: {str(error)}, 키: {masked_key}, "
            f"응답: {response_body}, 재시도: {try_count + 1}/{max_retries}{context_suffix}"
        )
        print(error_msg)  # 콘솔 출력 유지
