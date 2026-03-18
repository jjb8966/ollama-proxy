# -*- coding: utf-8 -*-
"""
토큰 추정 유틸리티

메시지 내용을 기반으로 토큰 수를 추정합니다.
tiktoken을 사용할 수 있으면 사용하고, 없다면 간단한 추정 알고리즘을 사용합니다.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# tiktoken 사용 가능 여부 확인
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    logger.warning("tiktoken 패키지가 없습니다. 간단한 추정 알고리즘을 사용합니다.")


class TokenEstimator:
    """
    토큰 수 추정기
    
    tiktoken을 사용할 수 있으면 사용하고, 없다면 문자 수 기반 추정 알고리즘을 사용합니다.
    """
    
    # 클로바 토큰화 사용 시_chars_per_token 비율
    # 영어: 약 4자/토큰, 한국어: 약 2자/토큰 (평균 3자/토큰으로 가정)
    DEFAULT_CHARS_PER_TOKEN = 3.0
    
    def __init__(self, encoding: str = "cl100k_base"):
        """
        Args:
            encoding: 토큰화 인코딩 이름 (tiktoken 사용 시)
        """
        self.encoding = encoding
        self._enc = None
        
        if TIKTOKEN_AVAILABLE:
            try:
                self._enc = tiktoken.get_encoding(encoding)
            except Exception as e:
                logger.warning(f"토큰 인코딩 로드 실패: {e}")
                self._enc = None
    
    def estimate_tokens(self, text: str) -> int:
        """
        텍스트의 토큰 수를 추정합니다.
        
        Args:
            text: 추정할 텍스트
            
        Returns:
            추정 토큰 수
        """
        if self._enc is not None:
            try:
                return len(self._enc.encode(text))
            except Exception as e:
                logger.warning(f"tiktoken 인코딩 실패: {e}")
        
        # 폴백: 문자 수 기반 추정
        return self._estimate_by_chars(text)
    
    def _estimate_by_chars(self, text: str) -> int:
        """
        문자 수 기반으로 토큰 수를 추정합니다.
        
        Args:
            text: 추정할 텍스트
            
        Returns:
            추정 토큰 수
        """
        # 공백 제외 문자 수 계산
        char_count = len(text.replace(" ", ""))
        estimated = int(char_count / self.DEFAULT_CHARS_PER_TOKEN)
        return max(1, estimated)
    
    def estimate_messages_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """
        메시지列表의 총 토큰 수를 추정합니다.
        
        각 메시지에 역할, 이름, 콘텐츠가 포함됨을 감안하여
        오버헤드를 추가估算합니다.
        
        Args:
            messages: OpenAI 형식의 메시지列表
            
        Returns:
            추정 총 토큰 수
        """
        total_tokens = 0
        
        # 메시지당 기본 오버헤드 (역할, 이름 등의 메타데이터)
        MESSAGE_OVERHEAD = 4
        
        for message in messages:
            if not isinstance(message, dict):
                continue
            
            # 역할
            total_tokens += MESSAGE_OVERHEAD
            
            # 이름 필드
            if "name" in message:
                total_tokens += self.estimate_tokens(message["name"]) + 1
            
            # 콘텐츠
            content = message.get("content", "")
            
            if isinstance(content, str):
                total_tokens += self.estimate_tokens(content)
            elif isinstance(content, list):
                # 이미지 등의 복합 콘텐츠
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            total_tokens += self.estimate_tokens(item.get("text", ""))
                        elif item.get("type") == "image_url":
                            # 이미지는 대략 1000 토큰으로 추정
                            total_tokens += 1000
                    elif isinstance(item, str):
                        total_tokens += self.estimate_tokens(item)
            
            # 도구 역할 메시지의 경우
            if message.get("role") == "tool":
                total_tokens += self.estimate_tokens(str(message.get("content", "")))
        
        return total_tokens


def load_models_context_lengths() -> Dict[str, int]:
    """
    models.json에서 모델별 context length를 로드합니다.
    
    Returns:
        {모델명: context_length} 딕셔너리
    """
    import json
    import os
    
    models_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'models.json'
    )
    
    context_lengths = {}
    
    try:
        with open(models_path, 'r') as f:
            data = json.load(f)
            for model in data.get('models', []):
                name = model.get('name', '')
                context_length = model.get('context_length')
                if name and context_length:
                    context_lengths[name] = context_length
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"models.json 로드 실패: {e}")
    
    return context_lengths


# 전역 인스턴스
_token_estimator: Optional[TokenEstimator] = None
_models_context_lengths: Dict[str, int] = {}


def get_token_estimator() -> TokenEstimator:
    """토큰 추정기 인스턴스를 반환합니다."""
    global _token_estimator
    if _token_estimator is None:
        _token_estimator = TokenEstimator()
    return _token_estimator


def get_model_context_length(model_name: str) -> Optional[int]:
    """
    모델의 context length를 반환합니다.
    
    Args:
        model_name: 전체 모델 이름 (예: "nvidia-nim:minimaxai/minimax-m2.5")
        
    Returns:
        context_length 또는 None
    """
    global _models_context_lengths
    
    if not _models_context_lengths:
        _models_context_lengths = load_models_context_lengths()
    
    # 정확한 매칭 시도
    if model_name in _models_context_lengths:
        return _models_context_lengths[model_name]
    
    # 접두사 매칭 시도 (provider:model 형식)
    for key in _models_context_lengths:
        if model_name.startswith(key.split(':')[0] + ':'):
            return _models_context_lengths[key]
    
    return None


def check_context_length(
    model_name: str,
    messages: List[Dict[str, Any]],
    max_tokens: Optional[int] = None
) -> tuple:
    """
    요청의 컨텍스트 길이를 검증합니다.
    
    Args:
        model_name: 모델 이름
        messages: 메시지列表
        max_tokens: 요청한 최대 토큰 수
        
    Returns:
        (유효성여부, 에러메시지) 튜플
        - (True, None): 유효함
        - (False, 에러메시지): 초과或其他 문제
    """
    context_length = get_model_context_length(model_name)
    
    # context_length가 없으면 검증 스킵
    if context_length is None:
        return True, None
    
    # 토큰 추정
    estimator = get_token_estimator()
    estimated_tokens = estimator.estimate_messages_tokens(messages)
    
    # 90% 임계값 초과 시 경고
    threshold = int(context_length * 0.9)
    if estimated_tokens > threshold:
        logger.warning(
            f"[Context] ⚠️ 경고: 추정 토큰 수({estimated_tokens})가 "
            f"context window({context_length})의 90%를 초과합니다"
        )
    
    # 컨텍스트 초과
    if estimated_tokens > context_length:
        error_msg = (
            f"[Context Window Exceeded] 요청의 추정 토큰 수({estimated_tokens})가 "
            f"모델 {model_name}의 최대 컨텍스트 윈도우({context_length} tokens)를 초과합니다."
        )
        return False, error_msg
    
    # max_tokens가 context window를 초과하는지 검증
    if max_tokens is not None and max_tokens > context_length:
        error_msg = (
            f"[Max Tokens Exceeded] 요청한 max_tokens({max_tokens})가 "
            f"모델 {model_name}의 최대 컨텍스트 윈도우({context_length} tokens)를 초과합니다."
        )
        return False, error_msg
    
    return True, None