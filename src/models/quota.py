# -*- coding: utf-8 -*-
"""
쿼터 모델 정의

계정별 쿼터 정보를 저장하는 데이터 구조입니다.
"""

from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime


@dataclass
class QuotaInfo:
    """单个模型的 쿼터 정보"""
    remaining_fraction: float  # 0.0 ~ 1.0
    reset_time: Optional[str]   # ISO 형식 时间 문자열
    
    @property
    def percentage(self) -> int:
        """퍼센트로 변환 (0-100)"""
        return int(self.remaining_fraction * 100)
    
    @property
    def status(self) -> str:
        """상태 문자열 반환"""
        if self.remaining_fraction >= 0.7:
            return "🟢"
        elif self.remaining_fraction >= 0.4:
            return "🟡"
        elif self.remaining_fraction >= 0.1:
            return "🟠"
        else:
            return "🔴"


@dataclass
class AccountQuota:
    """계정별 쿼터 정보"""
    email: str
    claude: QuotaInfo
    gemini_pro: QuotaInfo
    gemini_flash: QuotaInfo


class QuotaModel:
    """쿼터 응답 생성"""
    
    @staticmethod
    def create_error_response(message: str) -> dict:
        """에러 응답 생성"""
        return {
            "error": {
                "message": message,
                "type": "invalid_request_error"
            }
        }
    
    @staticmethod
    def format_cli_output(quotas: list) -> str:
        """CLI 출력 포맷"""
        lines = []
        for quota in quotas:
            lines.append(f"━━ {quota.email} ━━")
            lines.append(f"├─ [Claude]      {quota.claude.status} {quota.claude.percentage}%")
            lines.append(f"├─ [Gemini Pro]  {quota.gemini_pro.status} {quota.gemini_pro.percentage}%")
            lines.append(f"└─ [Gemini Flash] {quota.gemini_flash.status} {quota.gemini_flash.percentage}%")
            lines.append("")
        return "\n".join(lines)