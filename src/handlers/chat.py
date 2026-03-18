# -*- coding: utf-8 -*-
"""
채팅 요청 핸들러 모듈

클라이언트의 채팅 요청을 처리하고 적절한 API 제공업체로 라우팅합니다.
"""

import logging
import os
from typing import Dict, Any, List, Optional

import requests

from src.providers.standard import StandardApiClient
from src.providers.qwen import QwenApiClient
from src.providers.google import GoogleApiClient
from src.utils.tokenizer import check_context_length
from src.core.errors import ErrorHandler


def _strip_quotes(value: str) -> str:
    """문자열 값에서 양쪽 따옴표를 제거합니다."""
    if not value:
        return value
    return value.strip('"\'')


class ChatHandler:
    """
    채팅 요청 핸들러
    
    모델 prefix에 따라 적절한 API 제공업체로 요청을 라우팅합니다.
    이미지 처리, 메시지 정규화 등의 전처리도 수행합니다.
    """
    
    # 제공업체별 prefix와 base_url 매핑
    PROVIDER_CONFIG = {
        'google': {
            'base_url': None,
            'client_attr': 'google_client'
        },
        'openrouter': {
            'base_url': 'https://openrouter.ai/api/v1',
            'client_attr': 'openrouter_client'
        },
        'akash': {
            'base_url': 'https://chatapi.akash.network/api/v1',
            'client_attr': 'akash_client'
        },
        'cohere': {
            'base_url': 'https://api.cohere.ai/compatibility/v1',
            'client_attr': 'cohere_client'
        },
        'codestral': {
            'base_url': 'https://codestral.mistral.ai/v1',
            'client_attr': 'codestral_client'
        },
        'qwen': {
            'base_url': 'https://portal.qwen.ai/v1',
            'client_attr': 'qwen_client'
        },
        'antigravity': {
            'base_url': _strip_quotes(os.getenv('ANTIGRAVITY_PROXY_URL', 'http://antigravity-proxy:5010/v1')),
            'client_attr': 'antigravity_client'
        },
        'nvidia-nim': {
            'base_url': _strip_quotes(os.getenv('NVIDIA_NIM_BASE_URL', 'https://integrate.api.nvidia.com/v1')),
            'client_attr': 'nvidia_nim_client'
        },
        'cli-proxy-api': {
            'base_url': _strip_quotes(os.getenv('CLI_PROXY_API_BASE_URL', 'http://localhost:8317/v1')),
            'client_attr': 'cli_proxy_api_client'
        },
        # Primary: ollama-cloud
        'ollama-cloud': {
            'base_url': _strip_quotes(os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1')),
            'client_attr': 'ollama_cloud_client'
        },
        # Backward-compatible alias
        'ollama': {
            'base_url': _strip_quotes(os.getenv('OLLAMA_BASE_URL', 'https://ollama.com/v1')),
            'client_attr': 'ollama_cloud_client'
        }
    }
    
    def __init__(self, api_config):
        """
        Args:
            api_config: ApiConfig 인스턴스 (각 제공업체의 rotator 포함)
        """
        self.api_config = api_config
        
        # 각 제공업체별 클라이언트 생성
        self.google_client = GoogleApiClient(api_config.google_rotator)
        self.openrouter_client = StandardApiClient(api_config.openrouter_rotator)
        self.akash_client = StandardApiClient(api_config.akash_rotator)
        self.cohere_client = StandardApiClient(api_config.cohere_rotator)
        self.codestral_client = StandardApiClient(api_config.codestral_rotator)
        self.qwen_client = QwenApiClient(api_config.qwen_oauth_manager)
        self.antigravity_client = StandardApiClient(api_config.antigravity_rotator)
        self.nvidia_nim_client = StandardApiClient(api_config.nvidia_nim_rotator)
        self.cli_proxy_api_client = StandardApiClient(api_config.cli_proxy_api_rotator)
        self.ollama_cloud_client = StandardApiClient(api_config.ollama_cloud_rotator)

    def _parse_model(self, requested_model: str) -> tuple:
        """
        모델 문자열에서 제공업체와 모델명을 추출합니다.
        
        Args:
            requested_model: "provider:model_name" 형식의 문자열
            
        Returns:
            (제공업체, 모델명, base_url) 튜플
        """
        for prefix, config in self.PROVIDER_CONFIG.items():
            if requested_model.startswith(f"{prefix}:"):
                model = requested_model.replace(f'{prefix}:', '')
                return prefix, model, config['base_url']
        
        # 매칭되는 제공업체가 없는 경우
        return None, requested_model, None

    def _get_client(self, provider: str):
        """제공업체에 해당하는 API 클라이언트를 반환합니다."""
        if provider not in self.PROVIDER_CONFIG:
            raise ValueError(f"지원되지 않는 제공업체: {provider}")
        
        client_attr = self.PROVIDER_CONFIG[provider]['client_attr']
        return getattr(self, client_attr)

    def _process_image_content(self, messages: List[Dict]) -> None:
        """
        메시지 내 이미지 데이터를 OpenAI 형식으로 변환합니다.
        
        Cline의 이미지 요청 형식을 OpenAI Vision API 형식으로 변환합니다.
        원본 messages 리스트를 직접 수정합니다.
        """
        if not messages:
            return
        
        for message in messages:
            if message['role'] != 'user':
                continue
            
            content = message.get('content', '')
            if not isinstance(content, str) or 'data:image' not in content:
                continue
            
            # 이미지 데이터 분리
            try:
                split1 = content.split('data:image')
                split2 = split1[1].split('<environment_details>')
                
                text_data = split1[0] + split2[1]
                image_data = 'data:image' + split2[0]
                
                # OpenAI Vision API 형식으로 변환
                message['content'] = [
                    {'type': 'text', 'text': text_data},
                    {'type': 'image_url', 'image_url': {'url': image_data}}
                ]
            except (IndexError, KeyError) as e:
                logging.warning(f"이미지 처리 실패: {e}")

    def handle_chat_request(self, req: Dict[str, Any]) -> Optional[requests.Response]:
        messages = req.get('messages')
        stream = req.get('stream', True)
        requested_model = req.get('model')
        thinking_level = req.get('thinking_level', 'minimal')
        max_tokens = req.get('max_tokens')

        if messages:
            self._process_image_content(messages)
        else:
            logging.warning("요청에 messages가 없습니다.")
            return None

        # Context Length 검증
        is_valid, error_msg = check_context_length(requested_model, messages, max_tokens)
        if not is_valid:
            logging.error(f"[Context] {error_msg}")
            # 에러 응답을 dict로 반환 (route에서 처리)
            return ErrorHandler.create_error_response(requested_model or "unknown", error_msg)

        provider, model, base_url = self._parse_model(requested_model)

        if not provider:
            logging.error(f"지원되지 않는 모델: {requested_model}")
            return None

        if provider == 'google':
            return self.google_client.post_request(
                model=model,
                messages=messages,
                thinking_level=thinking_level,
                stream=stream,
                max_tokens=req.get('max_tokens'),
                tools=req.get('tools'),
                tool_choice=req.get('tool_choice')
            )

        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }
        if req.get('tools') is not None:
            payload['tools'] = req.get('tools')
        if req.get('tool_choice') is not None:
            payload['tool_choice'] = req.get('tool_choice')

        endpoint = f"{base_url}/chat/completions"
        headers = {'Content-Type': 'application/json'}

        client = self._get_client(provider)
        return client.post_request(
            url=endpoint,
            payload=payload,
            headers=headers,
            stream=stream
        )
