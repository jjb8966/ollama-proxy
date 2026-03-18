# -*- coding: utf-8 -*-
"""
쿼터 서비스

Antigravity 프록시에서 쿼터 정보를 조회합니다.
현재는 더미 구현 (실제 API 추가 시 수정 예정).
"""

import logging
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from src.models.quota import AccountQuota, QuotaInfo


logger = logging.getLogger(__name__)


class QuotaService:
    """
    쿼터 조회 서비스
    
    Antigravity 프록시에서 쿼터 정보를 조회하고 캐싱합니다.
    """
    
    # 캐시 TTL (초)
    CACHE_TTL = 300
    
    def __init__(self):
        self._cache: Optional[Dict] = None
        self._cache_time: float = 0
    
    def _is_cache_valid(self) -> bool:
        """캐시 유효성 검사"""
        if self._cache is None:
            return False
        return (time.time() - self._cache_time) < self.CACHE_TTL
    
    def get_quota(self, force_refresh: bool = False) -> List[AccountQuota]:
        """
        쿼터 정보를 조회합니다.
        
        Args:
            force_refresh: 강제 새로고침 여부
            
        Returns:
            계정별 쿼터 정보 리스트
        """
        if not force_refresh and self._is_cache_valid():
            logger.debug("쿼터 캐시 사용")
            return self._cache
        
        # 실제 구현 시 Antigravity 프록시 API 호출
        # 현재는 더미 데이터 반환
        return self._get_dummy_quota()
    
    def _get_dummy_quota(self) -> List[AccountQuota]:
        """더미 쿼터 데이터 반환 (개발/테스트용)"""
        logger.warning("[Quota] 더미 데이터 반환 - 실제 API 연동 필요")
        
        # TODO: antigravity-proxy에 GET /v1/quota API 추가 후 실제 연동
        # 현재는 시뮬레이션을 위한 랜덤 값 사용
        import random
        random.seed(int(time.time() / 60))  # 1분마다 변경
        
        dummy_quotas = [
            AccountQuota(
                email="account1@example.com",
                claude=QuotaInfo(
                    remaining_fraction=random.uniform(0.3, 0.95),
                    reset_time=(datetime.now() + timedelta(hours=2)).isoformat()
                ),
                gemini_pro=QuotaInfo(
                    remaining_fraction=random.uniform(0.1, 0.8),
                    reset_time=(datetime.now() + timedelta(hours=1)).isoformat()
                ),
                gemini_flash=QuotaInfo(
                    remaining_fraction=random.uniform(0.5, 0.99),
                    reset_time=(datetime.now() + timedelta(hours=2)).isoformat()
                )
            ),
            AccountQuota(
                email="account2@example.com",
                claude=QuotaInfo(
                    remaining_fraction=random.uniform(0.4, 0.9),
                    reset_time=(datetime.now() + timedelta(hours=3)).isoformat()
                ),
                gemini_pro=QuotaInfo(
                    remaining_fraction=random.uniform(0.2, 0.7),
                    reset_time=(datetime.now() + timedelta(hours=2)).isoformat()
                ),
                gemini_flash=QuotaInfo(
                    remaining_fraction=random.uniform(0.6, 0.95),
                    reset_time=(datetime.now() + timedelta(hours=3)).isoformat()
                )
            )
        ]
        
        self._cache = dummy_quotas
        self._cache_time = time.time()
        
        return dummy_quotas
    
    def _fetch_from_antigravity(self) -> List[AccountQuota]:
        """
        Antigravity 프록시에서 실제 쿼터 정보를 조회합니다.
        
        TODO: antigravity-proxy에 다음 API가 구현되어야 함:
        GET /v1/quota -> {"accounts": [{"email": "...", "antigravity": {...}}]}
        
        Returns:
            계정별 쿼터 정보 리스트
        """
        import os
        import requests
        
        antigravity_url = os.getenv('ANTIGRAVITY_PROXY_URL', 'http://antigravity-proxy:5010/v1')
        quota_url = f"{antigravity_url}/quota"
        
        try:
            resp = requests.get(quota_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            quotas = []
            for account_data in data.get('accounts', []):
                email = account_data.get('email', 'unknown')
                ag_data = account_data.get('antigravity', {})
                
                quotas.append(AccountQuota(
                    email=email,
                    claude=self._parse_quota_info(ag_data.get('claude')),
                    gemini_pro=self._parse_quota_info(ag_data.get('gemini-pro')),
                    gemini_flash=self._parse_quota_info(ag_data.get('gemini-flash'))
                ))
            
            return quotas
            
        except Exception as e:
            logger.error(f"[Quota] Antigravity 쿼터 조회 실패: {e}")
            # 실패 시 더미 데이터 반환
            return self._get_dummy_quota()
    
    def _parse_quota_info(self, data: dict) -> 'QuotaInfo':
        """API 응답에서 QuotaInfo 객체 생성"""
        if not data:
            return QuotaInfo(remaining_fraction=0.0, reset_time=None)
        return QuotaInfo(
            remaining_fraction=data.get('remainingFraction', 0.0),
            reset_time=data.get('resetTime')
        )
    
    def get_account_for_model(self, model_provider: str) -> Optional[AccountQuota]:
        """
        특정 모델 제공업체에 사용할 최적 계정을 반환합니다.
        
        Args:
            model_provider: 모델 제공업체 (claude, gemini-pro, gemini-flash)
            
        Returns:
            최적 계정 또는 None
        """
        quotas = self.get_quota()
        
        if not quotas:
            return None
        
        # Tier 기반 선택 (70% -> 40% -> 10% -> any)
        tier_thresholds = [0.7, 0.4, 0.1, 0.0]
        
        for threshold in tier_thresholds:
            candidates = []
            for quota in quotas:
                quota_info = self._get_quota_for_provider(quota, model_provider)
                if quota_info and quota_info.remaining_fraction >= threshold:
                    candidates.append((quota, quota_info))
            
            if candidates:
                # 남은 쿼터가 많은 순으로 정렬
                candidates.sort(key=lambda x: x[1].remaining_fraction, reverse=True)
                return candidates[0][0]
        
        return None
    
    def _get_quota_for_provider(self, quota: AccountQuota, provider: str) -> Optional[QuotaInfo]:
        """provider에 해당하는 QuotaInfo 반환"""
        provider_map = {
            "claude": quota.claude,
            "gemini-pro": quota.gemini_pro,
            "gemini-flash": quota.gemini_flash,
        }
        return provider_map.get(provider)


# 전역 인스턴스
_quota_service: Optional[QuotaService] = None


def get_quota_service() -> QuotaService:
    """쿼터 서비스 인스턴스 반환"""
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService()
    return _quota_service