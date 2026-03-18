# -*- coding: utf-8 -*-
"""
API 키 상태 조회 라우트

/v1/keys/status 엔드포인트를 정의합니다.
각 제공업체의 API 키 건강도 및 사용 상태를 반환합니다.
"""

import json
import logging
from flask import Blueprint, Response, current_app


logger = logging.getLogger(__name__)

# Blueprint 생성
keys_bp = Blueprint('keys', __name__, url_prefix='/v1')


@keys_bp.route('/keys/status', methods=['GET'])
def get_keys_status():
    """
    제공업체별 API 키 상태를 반환합니다.
    """
    try:
        api_config = current_app.config.get('api_config')
        if not api_config:
            raise ValueError("api_config not found in current app context")
            
        # 추적할 제공업체의 KeyRotator 목록 추출
        rotators = [
            api_config.ollama_cloud_rotator,
            api_config.google_rotator,
            api_config.openrouter_rotator,
            api_config.akash_rotator,
            api_config.cohere_rotator,
            api_config.codestral_rotator,
            api_config.qwen_oauth_manager,
            api_config.antigravity_rotator,
            api_config.nvidia_nim_rotator,
            api_config.cli_proxy_api_rotator
        ]
        
        providers_status = []
        
        for rotator in rotators:
            # qwen_oauth_manager 등 get_key_status를 구현하지 않은 경우는 스킵 (KeyRotator 인스턴스인지 확인)
            if not hasattr(rotator, 'get_key_status') or not callable(rotator.get_key_status):
                continue
                
            provider_name = rotator.provider
            keys_info = rotator.get_key_status()
            
            total_keys = len(keys_info)
            if total_keys == 0:
                continue
                
            available_keys = sum(1 for k in keys_info if k.get("status") == "available")
            rate_limited_keys = total_keys - available_keys
            
            providers_status.append({
                "provider": provider_name,
                "total_keys": total_keys,
                "available_keys": available_keys,
                "rate_limited_keys": rate_limited_keys,
                "keys": keys_info
            })
            
        return Response(
            json.dumps({"providers": providers_status}),
            status=200,
            mimetype='application/json'
        )
        
    except Exception as e:
        logger.error(f"키 상태 조회 실패: {e}")
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