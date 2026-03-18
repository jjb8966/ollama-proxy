# -*- coding: utf-8 -*-
"""
쿼터 조회 API 라우트

/v1/quota 엔드포인트를 정의합니다.
"""

import json
import logging
from flask import Blueprint, Response

from src.services.quota_service import get_quota_service


logger = logging.getLogger(__name__)

# Blueprint 생성
quota_bp = Blueprint('quota', __name__, url_prefix='/v1')


@quota_bp.route('/quota', methods=['GET'])
def get_quota():
    """
    계정별 쿼터 상태를 반환합니다.
    
    캐시된 쿼터 정보를 반환합니다 (TTL: 300초).
    """
    try:
        service = get_quota_service()
        quotas = service.get_quota()
        
        # 응답 형식으로 변환
        accounts = []
        for quota in quotas:
            accounts.append({
                "email": quota.email,
                "antigravity": {
                    "claude": {
                        "remainingFraction": quota.claude.remaining_fraction,
                        "resetTime": quota.claude.reset_time
                    },
                    "gemini-pro": {
                        "remainingFraction": quota.gemini_pro.remaining_fraction,
                        "resetTime": quota.gemini_pro.reset_time
                    },
                    "gemini-flash": {
                        "remainingFraction": quota.gemini_flash.remaining_fraction,
                        "resetTime": quota.gemini_flash.reset_time
                    }
                }
            })
        
        response = {"accounts": accounts}
        return Response(
            json.dumps(response),
            status=200,
            mimetype='application/json'
        )
    
    except Exception as e:
        logger.error(f"쿼터 조회 실패: {e}")
        error_response = {
            "error": {
                "message": str(e),
                "type": "server_error"
            }
        }
        return Response(
            json.dumps(error_response),
            status=500,
            mimetype='application/json'
        )


@quota_bp.route('/quota/refresh', methods=['GET'])
def refresh_quota():
    """
    쿼터 정보를 강제 새로고침합니다.
    
    캐시를 무시하고 Antigravity 프록시에서 다시 조회합니다.
    """
    try:
        service = get_quota_service()
        quotas = service.get_quota(force_refresh=True)
        
        response = {
            "status": "success",
            "accounts": [
                {
                    "email": q.email,
                    "antigravity": {
                        "claude": {"remainingFraction": q.claude.remaining_fraction},
                        "gemini-pro": {"remainingFraction": q.gemini_pro.remaining_fraction},
                        "gemini-flash": {"remainingFraction": q.gemini_flash.remaining_fraction}
                    }
                }
                for q in quotas
            ]
        }
        return Response(
            json.dumps(response),
            status=200,
            mimetype='application/json'
        )
    
    except Exception as e:
        logger.error(f"쿼터 새로고침 실패: {e}")
        error_response = {
            "error": {
                "message": str(e),
                "type": "server_error"
            }
        }
        return Response(
            json.dumps(error_response),
            status=500,
            mimetype='application/json'
        )