import logging
import os

def setup_logging():
    """
    통합 로깅 시스템 설정
    로그 레벨, 포맷, 핸들러를 초기화합니다.
    """
    log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
    numeric_level = getattr(logging, log_level, logging.INFO)
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler()  # 콘솔 출력만 유지
        ]
    )
    
    # 특정 모듈에 대한 로그 레벨 조정
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    
    return logging.getLogger(__name__)

# 애플리케이션 시작 시 로깅 초기화
logger = setup_logging()
