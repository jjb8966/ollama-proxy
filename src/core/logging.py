# -*- coding: utf-8 -*-
"""
로깅 설정 모듈

애플리케이션 전체에서 일관된 로깅 형식과 설정을 제공합니다.
"""

import logging
import os


def setup_logging() -> logging.Logger:
    """
    통합 로깅 시스템 설정
    
    환경 변수 LOG_LEVEL로 로그 레벨을 조정할 수 있습니다.
    기본값은 INFO입니다.
    
    Returns:
        설정된 로거 인스턴스
    """
    # 환경 변수에서 로그 레벨 가져오기 (기본: INFO)
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    # 로깅 기본 설정
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()  # 콘솔 출력
        ]
    )
    
    # 외부 라이브러리 로그 레벨 조정 (너무 상세한 로그 억제)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)


# 모듈 임포트 시 로거 초기화
logger = setup_logging()
