import logging

from utils.api_client import ApiClient


def normalize_messages_for_perplexity(messages):
    """
    Perplexity API용 메시지 정규화
    - 연속된 같은 role의 메시지를 하나로 병합
    - system 메시지는 맨 앞에 유지
    - user와 assistant가 번갈아 나오도록 보장
    """
    if not messages:
        return messages
    
    normalized = []
    system_messages = []
    
    # system 메시지 분리
    for msg in messages:
        if msg.get('role') == 'system':
            system_messages.append(msg)
        else:
            break
    
    # system 메시지 병합
    if system_messages:
        combined_system = '\n\n'.join([m.get('content', '') for m in system_messages])
        normalized.append({'role': 'system', 'content': combined_system})
    
    # 나머지 메시지 처리 (system 이후)
    remaining = messages[len(system_messages):]
    
    for msg in remaining:
        role = msg.get('role')
        content = msg.get('content', '')
        
        # content가 리스트인 경우 (이미지 등) 그대로 유지
        if isinstance(content, list):
            # 이미지가 포함된 경우 텍스트만 추출
            text_parts = []
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    text_parts.append(part.get('text', ''))
            content = '\n'.join(text_parts) if text_parts else str(content)
        
        if not normalized:
            # 첫 번째 메시지
            normalized.append({'role': role, 'content': content})
        elif normalized[-1]['role'] == role:
            # 연속된 같은 role - 병합
            prev_content = normalized[-1]['content']
            normalized[-1]['content'] = f"{prev_content}\n\n{content}"
        else:
            # 다른 role - 추가
            normalized.append({'role': role, 'content': content})
    
    # 마지막이 user가 아닌 경우 처리 (Perplexity는 마지막이 user여야 함)
    # 단, assistant로 끝나면 그대로 유지 (일부 경우 허용)
    
    return normalized


class ChatHandler:
    def __init__(self, api_config):
        self.api_config = api_config
        # 각 제공업체별 ApiClient 인스턴스 생성
        self.google_client = ApiClient(self.api_config.google_rotator)
        self.openrouter_client = ApiClient(self.api_config.openrouter_rotator)
        self.akash_client = ApiClient(self.api_config.akash_rotator)
        self.cohere_client = ApiClient(self.api_config.cohere_rotator)
        self.codestral_client = ApiClient(self.api_config.codestral_rotator)
        self.qwen_client = ApiClient(self.api_config.qwen_rotator)
        self.perplexity_client = ApiClient(self.api_config.perplexity_rotator)

    def _get_client(self, requested_model):
        """요청 모델에 따라 적절한 ApiClient 반환"""
        if requested_model.startswith("google:"):
            return self.google_client
        elif requested_model.startswith("openrouter:"):
            return self.openrouter_client
        elif requested_model.startswith("akash:"):
            return self.akash_client
        elif requested_model.startswith("cohere:"):
            return self.cohere_client
        elif requested_model.startswith("codestral:"):
            return self.codestral_client
        elif requested_model.startswith("qwen:"):
            return self.qwen_client
        elif requested_model.startswith("perplexity:"):
            return self.perplexity_client
        else:
            raise ValueError(f"지원되지 않는 모델: {requested_model}")

    def handle_chat_request(self, req):
        # '/api/chat' 요청을 처리하는 메서드
        messages = req.get('messages')
        stream = req.get('stream', True)
        requested_model = req.get('model')

        if messages:
            for message in messages:
                # cline 이미지 요청 처리 로직
                if message['role'] == 'user' and 'data:image' in message['content']:
                    split1 = message['content'].split('data:image')
                    split2 = split1[1].split('<environment_details>')

                    text_data = split1[0] + split2[1]
                    image_data = 'data:image' + split2[0]

                    text_content = {
                        'type': 'text',
                        'text': text_data
                    }

                    image_content = {
                        'type': 'image_url',
                        'image_url': {
                            'url': image_data
                        }
                    }

                    content = [text_content, image_content]
                    message['content'] = content
        else:
            logging.warning("No messages found in the request.")

        api_config = self.api_config.get_api_config(requested_model)
        model = api_config['model']
        base_url = api_config['base_url']

        # Perplexity 모델인 경우 메시지 정규화
        if requested_model.startswith("perplexity:"):
            messages = normalize_messages_for_perplexity(messages)

        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }

        end_point = base_url + "/chat/completions"
        headers = {'Content-Type': 'application/json'}

        # 적절한 ApiClient 선택
        client = self._get_client(requested_model)

        # API 요청 실행
        resp = client.post_request(
            url=end_point,
            payload=payload,
            headers=headers,
            stream=stream
        )

        return resp
