# -*- coding: utf-8 -*-
"""
표준 API 클라이언트 모듈

KeyRotator를 사용하는 일반적인 API 제공업체 클라이언트입니다.
Google, OpenRouter, Cohere 등 대부분의 제공업체에서 사용됩니다.
"""

from typing import Optional

from .base import BaseApiClient
from src.auth.key_rotator import KeyRotator


class StandardApiClient(BaseApiClient):
    """
    표준 API 클라이언트
    
    KeyRotator를 통해 API 키를 순환하며 사용하는 클라이언트입니다.
    대부분의 OpenAI 호환 API 제공업체에서 사용됩니다.
    """
    
    def __init__(self, key_rotator: KeyRotator):
        """
        Args:
            key_rotator: API 키 순환 관리자 인스턴스
        """
        super().__init__(key_rotator.provider)
        self.key_rotator = key_rotator
    
    def _get_api_key(self) -> Optional[str]:
        """다음 순서의 API 키를 반환합니다."""
        return self.key_rotator.get_next_key()
    
    def _on_auth_failure(self) -> bool:
        """
        인증 실패 시 호출됩니다.
        
        표준 클라이언트는 키 순환으로 자동 복구되므로,
        별도의 복구 로직 없이 다음 키로 재시도합니다.
        
        Returns:
            항상 False (자동 복구 없음, 다음 키로 재시도)
        """
        return False  # 키 순환은 get_next_key에서 자동으로 처리됨
