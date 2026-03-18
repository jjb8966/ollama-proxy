# -*- coding: utf-8 -*-
"""
API 키 순환 관리 모듈

멀티 프로세스 환경에서 안전하게 API 키를 순환하며 사용할 수 있도록 합니다.
파일 기반 락을 사용하여 프로세스 간 동기화를 보장합니다.
쿼터 기반 선택 및 Rate Limit 핸들링을 지원합니다.
"""

import os
import logging
import fcntl
import time
from threading import Lock
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class KeyHealth:
    """개별 키의 상태 정보"""
    key_hash: str                    # 키 식별용 해시
    usage_count: int = 0             # 사용 횟수
    failure_count: int = 0           # 실패 횟수
    last_used: float = 0             # 마지막 사용 시각 (timestamp)
    last_failure: Optional[float] = None  # 마지막 실패 시각
    is_rate_limited: bool = False    # Rate Limit 상태
    rate_limit_until: Optional[float] = None  # Rate Limit 복귀 예정 시각
    
    @property
    def health_score(self) -> float:
        """건강도 점수 (0.0 ~ 1.0)"""
        if self.is_rate_limited:
            return 0.0
        
        # 기본 점수 1.0에서 실패율과 사용 횟수로 감점
        total = self.usage_count + self.failure_count
        if total == 0:
            return 1.0
        
        failure_rate = self.failure_count / total
        score = 1.0 - failure_rate
        
        # 최근 사용 않았으면 가점
        if time.time() - self.last_used > 300:  # 5분 이상 경과
            score = min(1.0, score + 0.1)
        
        return max(0.0, min(1.0, score))
    
    @property
    def is_available(self) -> bool:
        """사용 가능한지 여부"""
        if self.is_rate_limited:
            # Rate Limit 복귀 시간 확인
            if self.rate_limit_until and time.time() < self.rate_limit_until:
                return False
            # Rate Limit 복귀 시간 지났으면 상태 초기화
            self.is_rate_limited = False
            self.rate_limit_until = None
        return True
    
    def mark_used(self) -> None:
        """사용 표시"""
        self.usage_count += 1
        self.last_used = time.time()
    
    def mark_failure(self, is_rate_limit: bool = False, retry_after: Optional[int] = None) -> None:
        """실패 표시"""
        self.failure_count += 1
        self.last_failure = time.time()
        
        if is_rate_limit:
            self.is_rate_limited = True
            if retry_after:
                self.rate_limit_until = time.time() + retry_after
            else:
                self.rate_limit_until = time.time() + 60  # 기본 60초
    
    def reset(self) -> None:
        """상태 초기화"""
        self.failure_count = 0
        self.is_rate_limited = False
        self.rate_limit_until = None
        self.last_failure = None


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
    쿼터 기반 선택 및 Rate Limit 핸들링을 지원합니다.
    
    Attributes:
        provider: 제공업체 이름 (로깅용)
        api_keys: API 키 목록
        key_health: 키별 상태 정보 딕셔너리
    """
    
    # Tier thresholds (쿼터 백분율)
    TIER_1_THRESHOLD = 0.7   # 70% 이상
    TIER_2_THRESHOLD = 0.4   # 40% 이상
    TIER_3_THRESHOLD = 0.1   # 10% 이상
    
    def __init__(self, provider_name: str, env_var_name: str):
        """
        Args:
            provider_name: 제공업체 이름 (예: Google, OpenRouter)
            env_var_name: API 키가 저장된 환경 변수 이름 (예: GOOGLE_API_KEYS)
        """
        self.provider = provider_name
        self.api_keys = self._load_api_keys(env_var_name)
        self._lock = Lock()  # 스레드 간 동기화용
        
        # 키별 상태 추적
        self.key_health: Dict[int, KeyHealth] = {}
        self._init_key_health()
    
    def _init_key_health(self) -> None:
        """키 상태 정보를 초기화합니다."""
        for i in range(len(self.api_keys)):
            if i not in self.key_health:
                self.key_health[i] = KeyHealth(key_hash=f"key_{i}")
    
    def _hash_key(self, key: str) -> str:
        """키의 해시를 생성합니다."""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()[:8]

    def _load_api_keys(self, env_var_name: str) -> list:
        """
        환경 변수에서 API 키 목록을 로드합니다.

        지원 포맷:
        - 콤마(,) 구분: KEY1,KEY2,KEY3
        - 개행 구분(멀티라인):
          KEY1\nKEY2\nKEY3

        위 2가 혼합되어 있어도 모두 처리합니다.
        """
        keys_str = os.getenv(env_var_name, '')
        if not keys_str:
            logging.warning(f"[KeyRotator] {env_var_name} 환경 변수가 설정되지 않았습니다.")
            return []

        normalized = keys_str.replace(',', '\n')
        return [key.strip() for key in normalized.splitlines() if key.strip()]

    def get_next_key(self, quota_fraction: Optional[float] = None) -> str:
        """
        다음 API 키를 순환하며 반환합니다.
        
        쿼터 정보를 제공하면 쿼터-aware 선택을 수행합니다.
        파일 기반 인덱스를 사용하여 멀티 프로세스 환경에서도
        모든 키가 균등하게 사용되도록 합니다.
        
        Args:
            quota_fraction: 현재 키의 쿼터 잔량 (0.0 ~ 1.0), None이면 Round-Robin
            
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
                
                # 쿼터-aware 선택 또는 Round-Robin
                if quota_fraction is not None:
                    new_index = self._select_quota_aware_index(current_index, quota_fraction)
                else:
                    new_index = (current_index + 1) % len(self.api_keys)
                
                # 새 인덱스 저장
                self._write_index(index_file, new_index)
                
                # 키 사용 표시
                if new_index in self.key_health:
                    self.key_health[new_index].mark_used()
                else:
                    self.key_health[new_index] = KeyHealth(key_hash=self._hash_key(self.api_keys[new_index]))
                    self.key_health[new_index].mark_used()

        key = self.api_keys[new_index]
        return key
    
    def _select_quota_aware_index(self, current_index: int, quota_fraction: float) -> int:
        """
        쿼터 정보를 기반으로 사용할 키를 선택합니다.
        
        Args:
            current_index: 현재 인덱스
            quota_fraction: 현재 키의 쿼터 잔량
            
        Returns:
            선택된 키 인덱스
        """
        # Tier 결정
        if quota_fraction >= self.TIER_1_THRESHOLD:
            tier = 1
        elif quota_fraction >= self.TIER_2_THRESHOLD:
            tier = 2
        elif quota_fraction >= self.TIER_3_THRESHOLD:
            tier = 3
        else:
            tier = 4  # Fallback
        
        # 사용 가능한 키 중에서 점수最高的 선택
        candidates = []
        for i, health in self.key_health.items():
            if not health.is_available:
                continue
            
            # Tier 기반 필터링
            if tier <= 3:
                # 특정 Tier 이상만 허용
                key_quota = self._estimate_key_quota(i, tier)
                if key_quota < getattr(self, f'TIER_{tier}_THRESHOLD'):
                    continue
            
            score = self._calculate_key_score(i, health)
            candidates.append((i, score))
        
        if candidates:
            # 점수 가장 높은 키 선택
            candidates.sort(key=lambda x: x[1], reverse=True)
            selected = candidates[0][0]
            logging.debug(
                f"[KeyRotator] [{self.provider}] 쿼터-aware 선택: "
                f"index={selected}, tier={tier}, score={candidates[0][1]:.2f}"
            )
            return selected
        
        # 사용 가능한 키가 없으면 Round-Robin (마지막 사용 키之后再试)
        return (current_index + 1) % len(self.api_keys)
    
    def _estimate_key_quota(self, key_index: int, min_tier: int) -> float:
        """
        키의 쿼터 잔량을 추정합니다.
        
        실제 구현에서는 QuotaService 연동 필요.
        현재는 키 인덱스 기반 더미 값 반환.
        
        TODO: QuotaService 연동 시 다음과 같이 수정:
        1. from src.services.quota_service import get_quota_service
        2. service = get_quota_service()
        3. quota = service.get_quota()
        4. 해당 key_index에 해당하는 계정의 쿼터 정보 조회
        """
        # 더미 구현: 인덱스마다 다른 쿼터량 시뮬레이션
        base = 0.9 - (key_index * 0.15)
        return max(0.0, base)
    
    def _calculate_key_score(self, key_index: int, health: KeyHealth) -> float:
        """
        키의 점수를 계산합니다.
        
        점수 = 건강도 + 최근 사용惩罚 + 랜덤 (경쟁 방지)
        """
        import random
        
        # 건강도 점수
        health_score = health.health_score
        
        # 최근 사용惩罚 (최근에 사용한 키는 점수 낮춤)
        time_since_use = time.time() - health.last_used
        recent_penalty = 0.0
        if time_since_use < 60:  # 1분 이내 사용
            recent_penalty = 0.3
        elif time_since_use < 300:  # 5분 이내 사용
            recent_penalty = 0.1
        
        # 랜덤 (경쟁 방지)
        random_factor = random.uniform(0, 0.1)
        
        score = health_score - recent_penalty + random_factor
        return max(0.0, score)
    
    def mark_key_failure(self, key: str, is_rate_limit: bool = False, retry_after: Optional[int] = None) -> None:
        """
        키의 실패를 기록합니다.
        
        Args:
            key: 실패한 키
            is_rate_limit: Rate Limit 여부
            retry_after: 재시도까지의 초
        """
        with self._lock:
            for i, k in enumerate(self.api_keys):
                if k == key:
                    if i in self.key_health:
                        self.key_health[i].mark_failure(is_rate_limit, retry_after)
                    
                    if is_rate_limit:
                        logging.warning(
                            f"[KeyRotator] [{self.provider}] Rate Limit 감지 | "
                            f"key_index={i} | retry_after={retry_after}"
                        )
                    else:
                        logging.warning(
                            f"[KeyRotator] [{self.provider}] 키 실패 기록 | key_index={i}"
                        )
                    break
    
    def get_available_key_count(self) -> int:
        """사용 가능한 키 개수를 반환합니다."""
        return sum(1 for h in self.key_health.values() if h.is_available)
    
    def get_key_status(self) -> List[Dict]:
        """모든 키의 상태 정보를 반환합니다."""
        with self._lock:
            status = []
            for i, key in enumerate(self.api_keys):
                health = self.key_health.get(i)
                if health:
                    # 복구 시간 계산
                    retry_after = None
                    if health.is_rate_limited and health.rate_limit_until:
                        remaining = int(health.rate_limit_until - time.time())
                        if remaining > 0:
                            retry_after = remaining
                    
                    status.append({
                        "index": i,
                        "key_hash": self._hash_key(key),
                        "status": "rate_limited" if health.is_rate_limited else "available",
                        "usage_count": health.usage_count,
                        "failure_count": health.failure_count,
                        "health_score": health.health_score,
                        "retry_after_sec": retry_after
                    })
            return status
    
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
