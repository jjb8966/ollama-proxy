import logging

from utils.api_client import ApiClient


class ChatHandler:
    def __init__(self, api_config):
        self.api_config = api_config
        # 각 제공업체별 ApiClient 인스턴스 생성
        self.google_client = ApiClient(self.api_config.google_rotator)
        self.openrouter_client = ApiClient(self.api_config.openrouter_rotator)
        self.akash_client = ApiClient(self.api_config.akash_rotator)
        self.cohere_client = ApiClient(self.api_config.cohere_rotator)
        self.codestral_client = ApiClient(self.api_config.codestral_rotator)

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
