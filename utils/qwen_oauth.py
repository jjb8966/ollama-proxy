"""
Qwen OAuth Token Manager

~/.qwen/oauth_creds.json 파일에서 토큰을 로드하고,
필요 시 refresh_token을 사용해 access_token을 갱신합니다.
"""

import json
import os
import logging
import requests
import time
from pathlib import Path
from threading import Lock


class QwenOAuthManager:
    """Qwen OAuth 토큰 관리 클래스"""
    
    CREDENTIALS_PATH = os.path.expanduser("~/.qwen/oauth_creds.json")
    REFRESH_ENDPOINT = "https://portal.qwen.ai/api/v1/oauth/token"
    
    def __init__(self):
        self.provider = "Qwen"
        self._lock = Lock()
        self._access_token = None
        self._refresh_token = None
        self._expires_at = None
        self._load_credentials()
    
    def _load_credentials(self):
        """oauth_creds.json 파일에서 토큰 로드"""
        try:
            if os.path.exists(self.CREDENTIALS_PATH):
                with open(self.CREDENTIALS_PATH, 'r') as f:
                    creds = json.load(f)
                    self._access_token = creds.get('access_token')
                    self._refresh_token = creds.get('refresh_token')
                    self._expires_at = creds.get('expires_at')
                    logging.info(f"[QwenOAuth] 토큰 로드 성공 - 파일: {self.CREDENTIALS_PATH}")
            else:
                logging.warning(f"[QwenOAuth] 토큰 파일이 존재하지 않습니다: {self.CREDENTIALS_PATH}")
        except Exception as e:
            logging.error(f"[QwenOAuth] 토큰 로드 실패: {e}")
    
    def _save_credentials(self):
        """갱신된 토큰을 파일에 저장"""
        try:
            creds = {
                'access_token': self._access_token,
                'refresh_token': self._refresh_token,
                'expires_at': self._expires_at
            }
            # 디렉토리가 없으면 생성
            os.makedirs(os.path.dirname(self.CREDENTIALS_PATH), exist_ok=True)
            with open(self.CREDENTIALS_PATH, 'w') as f:
                json.dump(creds, f, indent=2)
            logging.info("[QwenOAuth] 토큰 저장 완료")
        except Exception as e:
            logging.error(f"[QwenOAuth] 토큰 저장 실패: {e}")
    
    def get_access_token(self) -> str:
        """현재 access_token 반환"""
        with self._lock:
            return self._access_token
    
    def refresh_access_token(self) -> bool:
        """
        refresh_token을 사용하여 access_token 갱신
        
        Returns:
            bool: 갱신 성공 여부
        """
        with self._lock:
            if not self._refresh_token:
                logging.error("[QwenOAuth] refresh_token이 없어 갱신할 수 없습니다.")
                return False
            
            try:
                logging.info("[QwenOAuth] access_token 갱신 시도 중...")
                
                # Qwen OAuth 토큰 갱신 요청
                response = requests.post(
                    self.REFRESH_ENDPOINT,
                    json={
                        'grant_type': 'refresh_token',
                        'refresh_token': self._refresh_token
                    },
                    headers={'Content-Type': 'application/json'},
                    timeout=30
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self._access_token = data.get('access_token', self._access_token)
                    # refresh_token도 갱신될 수 있음
                    if data.get('refresh_token'):
                        self._refresh_token = data.get('refresh_token')
                    if data.get('expires_at'):
                        self._expires_at = data.get('expires_at')
                    elif data.get('expires_in'):
                        self._expires_at = int(time.time()) + data.get('expires_in')
                    
                    self._save_credentials()
                    logging.info("[QwenOAuth] access_token 갱신 성공")
                    return True
                else:
                    logging.error(f"[QwenOAuth] 토큰 갱신 실패 - 상태: {response.status_code}, 응답: {response.text}")
                    return False
                    
            except Exception as e:
                logging.error(f"[QwenOAuth] 토큰 갱신 중 예외 발생: {e}")
                return False
    
    def is_token_valid(self) -> bool:
        """토큰이 유효한지 확인 (만료 30초 전 버퍼)"""
        if not self._access_token:
            return False
        if not self._expires_at:
            return True  # 만료 시간 없으면 유효하다고 가정
        return time.time() < (self._expires_at - 30)
    
    def log_key_count(self):
        """호환성을 위한 로깅 메서드"""
        if self._access_token:
            logging.info(f"[QwenOAuth] OAuth 토큰 로드됨")
        else:
            logging.warning(f"[QwenOAuth] OAuth 토큰 없음 - 파일 확인 필요: {self.CREDENTIALS_PATH}")
