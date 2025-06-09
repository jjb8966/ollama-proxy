import logging
import time

import requests

from config import ApiConfig


class ChatHandler:
    def __init__(self):
        self.api_config = ApiConfig()

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
        api_key = api_config['api_key']
        api_key_index = api_config['api_key_index']

        payload = {
            "messages": messages,
            "model": model,
            "stream": stream
        }

        end_point = base_url + "/chat/completions"

        try_count = 0
        while try_count < 100:
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': 'Bearer ' + api_key  # 가져온 키로 헤더 설정
                }

                logging.info(
                    f"API 요청 시도: {end_point} (Key: ...{api_key[-10:]}, Index:{api_key_index})")  # 어떤 키를 사용하는지 로깅 (선택 사항)

                resp = requests.post(end_point, headers=headers, json=payload, stream=stream, timeout=(50, 300))

                # HTTP 오류 발생 시 예외 발생
                resp.raise_for_status()

                # (OpenRouter) Rate limit exceeded 예외 발생
                if b'Rate limit exceeded' in resp.content:
                    raise requests.exceptions.RequestException

                logging.info("API 요청 성공")  # 성공 로깅 (선택 사항)
                return resp  # 성공 시 응답 반환 및 루프 종료

            except requests.exceptions.RequestException as e:
                # 요청 실패 시 오류 로깅 (어떤 키에서 실패했는지 포함)
                logging.warning(f"API 요청 실패 (Key: ...{api_key[:6]}, Index:{api_key_index})): {e}. 다음 키로 재시도합니다.")

                time.sleep(1)  # 1초 대기

                api_key, api_key_index = self.api_config.get_next_api_key(base_url)  # 다음 키 가져오기
                try_count += 1

                continue

        logging.error("모든 API 키 사용 실패")  # 모든 키 실패 시 오류 로깅
        return None
