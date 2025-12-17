# -*- coding: utf-8 -*-
"""
Qwen API 클라이언트 모듈

OAuth 토큰을 사용하는 Qwen API 전용 클라이언트입니다.
401 에러 발생 시 자동으로 토큰을 갱신합니다.
"""

import logging
from typing import Optional

from .base import BaseApiClient
from src.auth.qwen_oauth import QwenOAuthManager


class QwenApiClient(BaseApiClient):
    """
    Qwen OAuth API 클라이언트
    
    QwenOAuthManager를 통해 OAuth 토큰으로 인증하는 클라이언트입니다.
    401 에러 발생 시 refresh_token으로 access_token을 자동 갱신합니다.
    """
    
    def __init__(self, oauth_manager: QwenOAuthManager):
        """
        Args:
            oauth_manager: Qwen OAuth 토큰 관리자 인스턴스
        """
        super().__init__("Qwen")
        self.oauth_manager = oauth_manager
    
    def _get_api_key(self) -> Optional[str]:
        """현재 access_token을 반환합니다."""
        token = self.oauth_manager.get_access_token()
        if token:
            # 토큰 마지막 8자리만 로깅
            token_suffix = token[-8:] if len(token) >= 8 else "***"
            logging.info(f"[QwenApiClient] 토큰 사용 - key_ending: {token_suffix}")
        return token
    
    def _on_auth_failure(self) -> bool:
        """
        인증 실패 시 토큰 갱신을 시도합니다.
        
        Returns:
            갱신 성공 시 True (재시도 진행), 실패 시 False
        """
        logging.warning("[QwenApiClient] 401 Unauthorized - 토큰 갱신 시도")
        
        if self.oauth_manager.refresh_access_token():
            logging.info("[QwenApiClient] 토큰 갱신 성공 - 재시도 진행")
            return True
        else:
            logging.error("[QwenApiClient] 토큰 갱신 실패")
            return False
