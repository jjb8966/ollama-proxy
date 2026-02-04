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


def normalize_messages_for_perplexity(messages: List[Dict]) -> List[Dict]:
    """
    Perplexity API용 메시지를 정규화합니다.
    
    Perplexity API는 연속된 같은 role의 메시지를 허용하지 않으므로,
    이를 하나로 병합합니다.
    
    Args:
        messages: 원본 메시지 리스트
        
    Returns:
        정규화된 메시지 리스트
    """
    if not messages:
        return messages
    
    normalized = []
    system_messages = []
    
    # system 메시지 분리 (맨 앞에 연속된 것만)
    for msg in messages:
        if msg.get('role') == 'system':
            system_messages.append(msg)
        else:
            break
    
    # system 메시지 병합
    if system_messages:
        combined_system = '\n\n'.join([m.get('content', '') for m in system_messages])
        normalized.append({'role': 'system', 'content': combined_system})
    
    # 나머지 메시지 처리
    remaining = messages[len(system_messages):]
    
    for msg in remaining:
        role = msg.get('role')
        content = msg.get('content', '')
        
        # content가 리스트인 경우 (이미지 등) 텍스트만 추출
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text_parts.append(part.get('text', ''))
            content = '\n'.join(text_parts) if text_parts else str(content)
        
        if not normalized:
            normalized.append({'role': role, 'content': content})
        elif normalized[-1]['role'] == role:
            # 연속된 같은 role - 병합
            prev_content = normalized[-1]['content']
            normalized[-1]['content'] = f"{prev_content}\n\n{content}"
        else:
            normalized.append({'role': role, 'content': content})
    
    return normalized


class ChatHandler:
    """
    채팅 요청 핸들러
    
    모델 prefix에 따라 적절한 API 제공업체로 요청을 라우팅합니다.
    이미지 처리, 메시지 정규화 등의 전처리도 수행합니다.
    """
    
    # 제공업체별 prefix와 base_url 매핑
    PROVIDER_CONFIG = {
        'google': {
            'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
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
        'perplexity': {
            'base_url': 'https://api.perplexity.ai',
            'client_attr': 'perplexity_client'
        }
    }
    
    def __init__(self, api_config):
        """
        Args:
            api_config: ApiConfig 인스턴스 (각 제공업체의 rotator 포함)
        """
        self.api_config = api_config
        
        # 각 제공업체별 클라이언트 생성
        self.google_client = StandardApiClient(api_config.google_rotator)
        self.openrouter_client = StandardApiClient(api_config.openrouter_rotator)
        self.akash_client = StandardApiClient(api_config.akash_rotator)
        self.cohere_client = StandardApiClient(api_config.cohere_rotator)
        self.codestral_client = StandardApiClient(api_config.codestral_rotator)
        self.qwen_client = QwenApiClient(api_config.qwen_oauth_manager)
        self.perplexity_client = StandardApiClient(api_config.perplexity_rotator)

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

    def _sanitize_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        빈 content 메시지를 제거합니다.
        
        일부 클라이언트가 content 없이 assistant 메시지를 보내는 경우를 방지합니다.
        """
        sanitized = []
        for msg in messages:
            content = msg.get('content', None)
            if content is None:
                continue
            if isinstance(content, str) and not content.strip():
                continue
            if isinstance(content, list):
                has_text = any(
                    isinstance(part, dict)
                    and part.get('type') == 'text'
                    and str(part.get('text', '')).strip()
                    for part in content
                )
                has_image = any(
                    isinstance(part, dict)
                    and part.get('type') == 'image_url'
                    and part.get('image_url', {}).get('url')
                    for part in content
                )
                if not (has_text or has_image):
                    continue
            sanitized.append(msg)
        return sanitized

    def handle_chat_request(self, req: Dict[str, Any]) -> Optional[requests.Response]:
        """
        채팅 요청을 처리합니다.
        
        Args:
            req: 요청 데이터 (model, messages, stream 포함)
            
        Returns:
            API 응답 객체, 실패 시 None
        """
        messages = req.get('messages')
        stream = req.get('stream', True)
        requested_model = req.get('model')
        debug_proxy = os.getenv("DEBUG_PROXY", "false").lower() == "true"

        # 이미지 처리
        if messages:
            self._process_image_content(messages)
            messages = self._sanitize_messages(messages)
        else:
            logging.warning("요청에 messages가 없습니다.")
            return None

        # 모델 파싱 및 제공업체 결정
        provider, model, base_url = self._parse_model(requested_model)
        
        if not base_url:
            logging.error(f"지원되지 않는 모델: {requested_model}")
            return None

        if debug_proxy:
            msg_summaries = []
            for msg in messages:
                content = msg.get('content', None)
                if isinstance(content, str):
                    ctype = "str"
                    clen = len(content)
                elif isinstance(content, list):
                    ctype = "list"
                    clen = len(content)
                elif content is None:
                    ctype = "none"
                    clen = 0
                else:
                    ctype = type(content).__name__
                    clen = 1
                msg_summaries.append({
                    "role": msg.get("role"),
                    "content_type": ctype,
                    "content_len": clen
                })
            logging.info(
                "[DEBUG_PROXY] 요청 모델=%s provider=%s stream=%s messages=%s",
                requested_model,
                provider,
                stream,
                msg_summaries
            )

        # Perplexity 메시지 정규화
        if provider == 'perplexity':
            messages = normalize_messages_for_perplexity(messages)

        # 요청 페이로드 구성
        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }
        
        # Google 모델에 Thinking 모드 활성화
        # thinking_budget: 1~24576 (사고 토큰 예산)
        # 응답에서 <thought> 태그는 ResponseHandler에서 필터링
        if provider == 'google':
            payload["extra_body"] = {
                "google": {
                    "thinking_config": {
                        "include_thoughts": True,
                        "thinking_budget": 24576  # 최대 추론 토큰
                    }
                }
            }

        endpoint = f"{base_url}/chat/completions"
        headers = {'Content-Type': 'application/json'}

        # API 요청 실행
        client = self._get_client(provider)
        return client.post_request(
            url=endpoint,
            payload=payload,
            headers=headers,
            stream=stream
        )
