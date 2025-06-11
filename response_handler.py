import json
import logging
import time
from datetime import datetime

from requests import Response  # requests.Response 타입 힌트를 위해 추가

from utils.error_handlers import ErrorHandler

logger = logging.getLogger(__name__)


class ResponseHandler:
    """
    API 응답을 처리하는 클래스 (스트리밍 및 비스트리밍).
    """

    def __init__(self):
        # 로거 초기화 (기존 코드와 동일하지만, 클래스 레벨 로거가 더 일반적입니다)
        # self.logger = logging.getLogger(__name__) # __init__ 밖으로 이동 가능
        pass  # 생성자에서 특별히 할 일이 없으면 pass 사용 가능

    # --- 스트리밍 응답 처리 관련 헬퍼 메서드 ---

    def _build_base_chunk(self, model: str) -> dict:
        """기본 Ollama 청크 구조를 생성합니다."""
        return {
            "model": model,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    def _parse_stream_line(self, line: bytes) -> dict | str | None:
        """스트림에서 한 줄을 파싱합니다."""
        if not line:
            return None

        s = line.decode('utf-8').strip()

        # 문자열이 "data: " 로 시작하는지 확인합니다. (Server-Sent Events 같은 스트리밍 형식에서 자주 사용됨)
        if s.startswith("data: "):
            # 만약 "data: " 로 시작한다면, 해당 접두사("data: ") 부분을 제거합니다.
            # 예를 들어 "data: {\"key\": \"value\"}" -> "{\"key\": \"value\"}"
            s = s[len("data: "):]

        # 문자열이 정확히 "[DONE]" 인지 확인합니다. (스트림의 종료를 나타내는 특별한 신호일 수 있음)
        if s == "[DONE]":
            return "[DONE]"

        # try 블록: 아래 코드 실행 중 발생할 수 있는 오류(Exception)를 처리하기 위해 사용합니다.
        try:
            # 문자열 s를 JSON 형식으로 구문 분석(parse)하여 파이썬 객체(주로 딕셔너리 또는 리스트)로 변환합니다.
            # 예를 들어 '{"id": 1, "name": "test"}' -> {"id": 1, "name": "test"}
            # 성공적으로 변환된 파이썬 객체를 반환합니다.
            return json.loads(s)
        # except 블록: try 블록 안에서 json.JSONDecodeError (JSON 구문 분석 오류)가 발생했을 경우 실행됩니다.
        except json.JSONDecodeError:
            # 만약 문자열 s가 유효한 JSON 형식이 아니라서 오류가 발생하면,
            # 경고(warning) 수준의 로그 메시지를 기록합니다. 로그에는 잘못된 JSON 문자열 s의 내용이 포함됩니다.
            logger.warning(f"스트림에서 잘못된 JSON 수신: {s}")
            # 잘못된 JSON 데이터(청크)는 처리할 수 없으므로, None을 반환하여 이 청크를 무시하도록 합니다.
            return None  # 잘못된 청크는 무시

    def _process_parsed_chunk(self, chunk: dict) -> tuple[str, str | None]:
        """파싱된 청크에서 텍스트 내용과 종료 이유를 추출합니다."""
        text_content = ""
        finish_reason = None
        if isinstance(chunk, dict) and 'choices' in chunk and chunk['choices']:
            choice = chunk['choices'][0]
            delta = choice.get('delta', {})
            text_content = delta.get('content', '')
            finish_reason = choice.get('finish_reason')
        return text_content, finish_reason

    def _create_content_chunk_str(self, model: str, text_content: str) -> str:
        """컨텐츠 Ollama 청크 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        chunk.update({
            "message": {"role": "assistant", "content": text_content},
            "done": False
        })
        return json.dumps(chunk) + "\n"

    def _create_final_chunk_str(self, model: str, start_time: float) -> str:
        """마지막 Ollama 청크 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        duration = int((time.time() - start_time) * 1e9)
        chunk.update({
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": duration,
            "eval_duration": duration  # 원본 코드와 동일하게 total_duration 사용
        })
        return json.dumps(chunk) + "\n"

    def _create_error_chunk_str(self, model: str, error: Exception) -> str:
        """오류 Ollama 청크 문자열을 생성합니다."""
        error_response = ErrorHandler.create_error_response(model, str(error))
        return json.dumps(error_response) + "\n"

    # --- 비스트리밍 응답 처리 관련 헬퍼 메서드 ---

    def _extract_non_streaming_data(self, data: dict) -> tuple[str, str | None]:
        """비스트리밍 응답 데이터에서 텍스트 내용과 모델 이름을 추출합니다."""
        text_content = ''
        response_model = None
        if 'choices' in data and data['choices']:
            message = data['choices'][0].get('message', {})
            text_content = message.get('content', '')
        if 'model' in data:
            response_model = data['model']
        return text_content, response_model

    def _create_non_streaming_response(self, model: str, text_content: str) -> dict:
        """비스트리밍 Ollama 응답 객체를 생성합니다."""
        response = self._build_base_chunk(model)
        response.update({
            "message": {"role": "assistant", "content": text_content},
            "done": True
        })
        return response

    # --- 공개 메서드 ---
    def handle_streaming_response(self, resp: Response, requested_model: str):
        """스트리밍 응답을 처리하는 제너레이터를 반환합니다."""
        start_time = time.time()
        response_model = requested_model
        response_closed = False

        try:
            for line in resp.iter_lines():
                parsed_data = self._parse_stream_line(line)

                if parsed_data is None:  # 빈 줄 또는 파싱 오류
                    continue
                if parsed_data == "[DONE]":  # 종료 신호
                    break

                # 유효한 JSON 청크 처리
                text_content, finish_reason = self._process_parsed_chunk(parsed_data)

                if text_content:
                    yield self._create_content_chunk_str(response_model, text_content)

                if finish_reason == "stop":
                    yield self._create_final_chunk_str(response_model, start_time)
                    # "stop" 이후에는 더 이상 청크가 오지 않는다고 가정
                    break  # 명시적으로 루프 종료

        except Exception as e:
            logger.error(f"스트림 처리 중 예외 발생: {e}", exc_info=True)
            yield self._create_error_chunk_str(response_model, e)
        finally:
            if resp and not response_closed:
                resp.close()
                response_closed = True

    def handle_non_streaming_response(self, resp: Response, requested_model: str) -> dict:
        """비스트리밍 응답을 처리합니다."""
        try:
            data = resp.json()
            text_content, response_model_from_data = self._extract_non_streaming_data(data)
            # 응답에 모델 정보가 있으면 사용, 없으면 요청된 모델 사용
            response_model = response_model_from_data or requested_model
            return self._create_non_streaming_response(response_model, text_content)

        except json.JSONDecodeError as e:
            logger.error(f"API 응답 JSON 디코딩 실패: {e}", exc_info=True)
            # 요청 모델 기반으로 오류 응답 생성 시도
            return self._create_error_chunk_str(requested_model, Exception("Failed to decode API response"))
        except Exception as e:
            logger.error(f"API 응답 처리 중 오류 발생: {e}", exc_info=True)
            # 요청 모델 기반으로 오류 응답 생성 시도
            return self._create_error_chunk_str(requested_model, e)
