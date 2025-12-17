# -*- coding: utf-8 -*-
"""
응답 핸들러 모듈

OpenAI 호환 API 응답을 Ollama 형식으로 변환합니다.
스트리밍 및 비스트리밍 응답을 모두 지원합니다.
"""

import json
import logging
import time
from datetime import datetime
from typing import Generator, Optional, Dict, Any, Union

from requests import Response

from src.core.errors import ErrorHandler


logger = logging.getLogger(__name__)


class ResponseHandler:
    """
    API 응답 처리 클래스
    
    OpenAI 형식의 응답을 Ollama 형식으로 변환합니다.
    스트리밍 응답과 비스트리밍 응답을 모두 처리합니다.
    """

    @staticmethod
    def _build_base_chunk(model: str) -> Dict[str, Any]:
        """기본 Ollama 청크 구조를 생성합니다."""
        return {
            "model": model,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    @staticmethod
    def _parse_stream_line(line: bytes) -> Union[Dict, str, None]:
        """
        스트림에서 한 줄을 파싱합니다.
        
        SSE(Server-Sent Events) 형식을 처리합니다:
        - 빈 줄: 무시
        - ":"로 시작: SSE 코멘트 (keep-alive 등), 무시
        - "data: ": 데이터 페이로드, JSON 파싱
        - "[DONE]": 스트림 종료 신호
        
        Args:
            line: 바이트 문자열
            
        Returns:
            파싱된 JSON 딕셔너리, "[DONE]" 문자열, 또는 None
        """
        if not line:
            return None

        decoded = line.decode('utf-8').strip()
        
        # 빈 줄 무시
        if not decoded:
            return None
        
        # SSE 코멘트 무시 (예: ": OPENROUTER PROCESSING")
        # SSE 표준에서 콜론으로 시작하는 줄은 코멘트로, 클라이언트가 무시해야 함
        if decoded.startswith(":"):
            return None

        # SSE "data: " 접두사 제거
        if decoded.startswith("data: "):
            decoded = decoded[6:]  # len("data: ") == 6

        # 스트림 종료 신호
        if decoded == "[DONE]":
            return "[DONE]"

        try:
            return json.loads(decoded)
        except json.JSONDecodeError:
            # SSE 코멘트가 아닌 알 수 없는 형식은 경고 로그
            logger.warning(f"스트림에서 잘못된 JSON 수신: {decoded[:100]}")
            return None

    def _extract_chunk_content(self, chunk: Dict) -> tuple:
        """
        파싱된 청크에서 텍스트 내용과 종료 이유를 추출합니다.
        
        Gemini Thinking 모드에서 <thought>...</thought> 태그는 필터링합니다.
        
        Returns:
            (텍스트 내용, 종료 이유) 튜플
        """
        text_content = ""
        finish_reason = None
        
        if isinstance(chunk, dict) and 'choices' in chunk and chunk['choices']:
            choice = chunk['choices'][0]
            delta = choice.get('delta', {})
            text_content = delta.get('content', '')
            finish_reason = choice.get('finish_reason')
            
            # 모든 응답 로그 출력
            if text_content:
                # <thought> 태그가 있는 경우에만 필터링
                if '<thought>' in text_content or '</thought>' in text_content or self._in_thought_tag:
                    logger.info("[Thinking Mode] thought 태그 감지 - 필터링 수행")
                    text_content = self._filter_thought_tags(text_content)
        
        return text_content, finish_reason
    
    def _filter_thought_tags(self, text: str) -> str:
        """
        텍스트에서 <thought>...</thought> 태그 내용을 필터링합니다.
        
        스트리밍 응답에서는 태그가 여러 청크에 걸쳐 나뉘어 올 수 있으므로,
        인스턴스 변수로 상태를 추적합니다.
        """
        result = []
        i = 0
        while i < len(text):
            # </thought> 태그 종료 감지
            if self._in_thought_tag:
                end_tag = "</thought>"
                if text[i:].startswith(end_tag):
                    self._in_thought_tag = False
                    i += len(end_tag)
                    continue
                i += 1
                continue
            
            # <thought> 태그 시작 감지
            start_tag = "<thought>"
            if text[i:].startswith(start_tag):
                self._in_thought_tag = True
                i += len(start_tag)
                continue
            
            result.append(text[i])
            i += 1
        
        return ''.join(result)

    def _create_content_chunk(self, model: str, text: str) -> str:
        """컨텐츠 청크 JSON 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        chunk.update({
            "message": {"role": "assistant", "content": text},
            "done": False
        })
        return json.dumps(chunk) + "\n"

    def _create_final_chunk(self, model: str, start_time: float) -> str:
        """최종 청크 JSON 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        duration_ns = int((time.time() - start_time) * 1e9)
        chunk.update({
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": duration_ns,
            "eval_duration": duration_ns
        })
        return json.dumps(chunk) + "\n"

    def _create_error_chunk(self, model: str, error: Exception) -> str:
        """오류 청크 JSON 문자열을 생성합니다."""
        error_response = ErrorHandler.create_error_response(model, str(error))
        return json.dumps(error_response) + "\n"

    def handle_streaming_response(
        self, 
        resp: Response, 
        requested_model: str
    ) -> Generator[str, None, None]:
        """
        스트리밍 응답을 처리하는 제너레이터입니다.
        
        OpenAI SSE 형식의 스트림을 Ollama NDJSON 형식으로 변환합니다.
        
        Args:
            resp: requests Response 객체 (스트리밍)
            requested_model: 요청된 모델 이름
            
        Yields:
            Ollama 형식의 JSON 청크 문자열
        """
        start_time = time.time()
        response_closed = False
        
        # Gemini Thinking 태그 필터링 상태 초기화
        self._in_thought_tag = False

        try:
            for line in resp.iter_lines():
                parsed = self._parse_stream_line(line)

                if parsed is None:
                    continue
                if parsed == "[DONE]":
                    break

                text_content, finish_reason = self._extract_chunk_content(parsed)

                if text_content:
                    yield self._create_content_chunk(requested_model, text_content)

                if finish_reason == "stop":
                    yield self._create_final_chunk(requested_model, start_time)
                    break

        except Exception as e:
            logger.error(f"스트림 처리 중 예외 발생: {e}", exc_info=True)
            yield self._create_error_chunk(requested_model, e)
        finally:
            if resp and not response_closed:
                resp.close()
                response_closed = True

    def handle_non_streaming_response(
        self, 
        resp: Response, 
        requested_model: str
    ) -> Dict[str, Any]:
        """
        비스트리밍 응답을 처리합니다.
        
        OpenAI 형식의 JSON 응답을 Ollama 형식으로 변환합니다.
        
        Args:
            resp: requests Response 객체
            requested_model: 요청된 모델 이름
            
        Returns:
            Ollama 형식의 응답 딕셔너리
        """
        try:
            data = resp.json()
            
            # 응답에서 텍스트 추출
            text_content = ''
            if 'choices' in data and data['choices']:
                message = data['choices'][0].get('message', {})
                text_content = message.get('content', '')
            
            # 응답에서 모델 이름 추출 (없으면 요청 모델 사용)
            response_model = data.get('model', requested_model)
            
            # Ollama 형식 응답 생성
            response = self._build_base_chunk(response_model)
            response.update({
                "message": {"role": "assistant", "content": text_content},
                "done": True
            })
            return response

        except json.JSONDecodeError as e:
            logger.error(f"API 응답 JSON 디코딩 실패: {e}", exc_info=True)
            return ErrorHandler.create_error_response(
                requested_model, 
                "Failed to decode API response"
            )
        except Exception as e:
            logger.error(f"API 응답 처리 중 오류: {e}", exc_info=True)
            return ErrorHandler.create_error_response(requested_model, str(e))
