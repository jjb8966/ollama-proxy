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
from typing import Generator, Optional, Dict, Any, Union, List, Tuple

import requests
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
    def _parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
        """OpenAI 호환 arguments를 Ollama 형식의 dict로 정규화합니다."""
        if isinstance(arguments, dict):
            return arguments

        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return {}
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return {"input": arguments}
            if isinstance(parsed, dict):
                return parsed
            return {"input": parsed}

        if arguments is None:
            return {}

        return {"input": arguments}

    def _normalize_tool_calls(self, tool_calls: Any) -> List[Dict[str, Any]]:
        """OpenAI 호환 tool_calls를 Ollama message.tool_calls 형식으로 변환합니다."""
        normalized: List[Dict[str, Any]] = []
        if not isinstance(tool_calls, list):
            return normalized

        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                continue

            function_info = tool_call.get("function", {})
            if not isinstance(function_info, dict):
                function_info = {}

            tool_entry: Dict[str, Any] = {
                "function": {
                    "name": str(function_info.get("name", "")),
                    "arguments": self._parse_tool_arguments(
                        function_info.get("arguments")
                    ),
                }
            }

            description = function_info.get("description")
            if description is not None:
                tool_entry["function"]["description"] = str(description)

            if tool_entry["function"]["name"]:
                normalized.append(tool_entry)

        return normalized

    @staticmethod
    def _extract_text_from_content_value(content: Any) -> str:
        if isinstance(content, str):
            return content

        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                for key in (
                    "content",
                    "text",
                    "value",
                    "reasoning_content",
                    "reasoning",
                ):
                    value = item.get(key)
                    if isinstance(value, str) and value:
                        parts.append(value)
                        break
            return "".join(parts)

        if isinstance(content, dict):
            for key in ("content", "text", "value", "reasoning_content", "reasoning"):
                value = content.get(key)
                if isinstance(value, str) and value:
                    return value

        return ""

    def _extract_text_from_message_like(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""

        for key in ("content", "text", "reasoning_content", "reasoning"):
            extracted = self._extract_text_from_content_value(payload.get(key))
            if extracted:
                return extracted

        return ""

    def _merge_stream_tool_calls(
        self, buffers: Dict[int, Dict[str, str]], delta_tool_calls: Any
    ) -> None:
        """스트리밍 tool_call 조각을 인덱스별로 누적합니다."""
        if not isinstance(delta_tool_calls, list):
            return

        for index, tool_call in enumerate(delta_tool_calls):
            if not isinstance(tool_call, dict):
                continue

            state = buffers.setdefault(
                index, {"name": "", "arguments": "", "description": ""}
            )
            function_info = tool_call.get("function", {})
            if not isinstance(function_info, dict):
                function_info = {}

            name = function_info.get("name")
            if name:
                state["name"] = str(name)

            description = function_info.get("description")
            if description:
                state["description"] = str(description)

            arguments = function_info.get("arguments")
            if isinstance(arguments, str):
                state["arguments"] += arguments
            elif arguments is not None:
                state["arguments"] += json.dumps(arguments, ensure_ascii=False)

    def _build_stream_tool_calls(
        self, buffers: Dict[int, Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """누적된 스트리밍 tool_call 상태를 Ollama 형식으로 변환합니다."""
        tool_calls: List[Dict[str, Any]] = []
        for index in sorted(buffers.keys()):
            state = buffers[index]
            name = state.get("name", "")
            if not name:
                continue

            tool_entry: Dict[str, Any] = {
                "function": {
                    "name": name,
                    "arguments": self._parse_tool_arguments(state.get("arguments", "")),
                }
            }
            if state.get("description"):
                tool_entry["function"]["description"] = state["description"]
            tool_calls.append(tool_entry)
        return tool_calls

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

        decoded = line.decode("utf-8").strip()

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

    def _extract_chunk_content(
        self, chunk: Dict[str, Any]
    ) -> Tuple[str, List[Dict[str, Any]], Optional[str]]:
        """
        파싱된 청크에서 텍스트 내용과 종료 이유를 추출합니다.

        Gemini Thinking 모드에서 <thought>...</thought> 태그는 필터링합니다.

        Returns:
            (텍스트 내용, tool_calls, 종료 이유) 튜플
        """
        text_content = ""
        tool_calls: List[Dict[str, Any]] = []
        finish_reason = None

        if isinstance(chunk, dict) and "choices" in chunk and chunk["choices"]:
            choice = chunk["choices"][0]
            delta = choice.get("delta", {})
            text_content = self._extract_text_from_message_like(delta)
            tool_calls = delta.get("tool_calls", [])
            finish_reason = choice.get("finish_reason")

            # 모든 응답 로그 출력
            if text_content:
                # <thought> 태그가 있는 경우에만 필터링
                if (
                    "<thought>" in text_content
                    or "</thought>" in text_content
                    or self._in_thought_tag
                ):
                    logger.info("[Thinking Mode] thought 태그 감지 - 필터링 수행")
                    text_content = self._filter_thought_tags(text_content)

        return text_content, tool_calls, finish_reason

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

        return "".join(result)

    def _create_content_chunk(self, model: str, text: str) -> str:
        """컨텐츠 청크 JSON 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        chunk.update({"message": {"role": "assistant", "content": text}, "done": False})
        return json.dumps(chunk) + "\n"

    def _create_tool_call_chunk(
        self, model: str, tool_calls: List[Dict[str, Any]]
    ) -> str:
        """툴 호출 청크 JSON 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        chunk.update(
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": tool_calls,
                },
                "done": False,
            }
        )
        return json.dumps(chunk) + "\n"

    def _create_final_chunk(
        self, model: str, start_time: float, done_reason: Optional[str] = None
    ) -> str:
        """최종 청크 JSON 문자열을 생성합니다."""
        chunk = self._build_base_chunk(model)
        duration_ns = int((time.time() - start_time) * 1e9)
        chunk.update(
            {
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "total_duration": duration_ns,
                "eval_duration": duration_ns,
            }
        )
        if done_reason:
            chunk["done_reason"] = done_reason
        return json.dumps(chunk) + "\n"

    def _create_error_chunk(self, model: str, error: Exception) -> str:
        """오류 청크 JSON 문자열을 생성합니다."""
        error_response = ErrorHandler.create_error_response(model, str(error))
        return json.dumps(error_response) + "\n"

    def handle_streaming_response(
        self, resp: Response, requested_model: str, max_tokens: Optional[int] = None
    ) -> Generator[str, None, None]:
        """
        스트리밍 응답을 처리하는 제너레이터입니다.

        OpenAI SSE 형식의 스트림을 Ollama NDJSON 형식으로 변환합니다.

        Args:
            resp: requests Response 객체 (스트리밍)
            requested_model: 요청된 모델 이름
            max_tokens: 요청에서 지정한 최대 토큰 수

        Yields:
            Ollama 형식의 JSON 청크 문자열
        """
        start_time = time.time()
        first_chunk_time: Optional[float] = None
        last_chunk_time = start_time
        response_closed = False
        stream_finished = False
        pending_tool_call_buffers: Dict[int, Dict[str, str]] = {}

        # Gemini Thinking 태그 필터링 상태 초기화
        self._in_thought_tag = False

        # 스트림 시작 로그
        logger.info(
            f"[Stream] 📤 시작 | model={requested_model} | max_tokens={max_tokens}"
        )

        try:
            for line in resp.iter_lines():
                now = time.time()

                # 청크 수신 상태 추적 - 5초간 수신 없음 경고
                if now - last_chunk_time > 5.0:
                    logger.warning(
                        f"[Stream] ⚠️ {now - last_chunk_time:.1f}초간 청크 수신 없음 | "
                        f"model={requested_model} | elapsed={now - start_time:.1f}초"
                    )
                last_chunk_time = now

                # 첫 번째 청크 수신 시간 기록
                if first_chunk_time is None and line:
                    first_chunk_time = now
                    first_chunk_latency = first_chunk_time - start_time
                    logger.info(
                        f"[Stream] ⏱️ 첫 청크 | model={requested_model} | "
                        f"latency={first_chunk_latency:.3f}초"
                    )

                parsed = self._parse_stream_line(line)

                if parsed is None:
                    continue
                if parsed == "[DONE]":
                    if pending_tool_call_buffers:
                        yield self._create_tool_call_chunk(
                            requested_model,
                            self._build_stream_tool_calls(pending_tool_call_buffers),
                        )
                    if not stream_finished:
                        yield self._create_final_chunk(requested_model, start_time)
                        stream_finished = True
                    break

                text_content, delta_tool_calls, finish_reason = (
                    self._extract_chunk_content(parsed)
                )
                self._merge_stream_tool_calls(
                    pending_tool_call_buffers, delta_tool_calls
                )

                if text_content:
                    yield self._create_content_chunk(requested_model, text_content)

                # finish_reason 상세 분석 및 로깅
                if finish_reason == "length":
                    logger.warning(
                        f"[Finish] ⚠️ LENGTH 종료 | model={requested_model} | "
                        f"max_tokens={max_tokens} |_reason: max_tokens 도달 또는 context 초과 가능성"
                    )
                elif finish_reason == "stop":
                    logger.info(f"[Finish] ✅ STOP 종료 | model={requested_model}")
                elif finish_reason == "tool_calls":
                    logger.info(
                        f"[Finish] 🔧 TOOL_CALLS 종료 | model={requested_model}"
                    )

                if finish_reason in ("stop", "tool_calls", "length"):
                    if pending_tool_call_buffers:
                        yield self._create_tool_call_chunk(
                            requested_model,
                            self._build_stream_tool_calls(pending_tool_call_buffers),
                        )
                        pending_tool_call_buffers.clear()
                    yield self._create_final_chunk(
                        requested_model, start_time, finish_reason
                    )
                    stream_finished = True
                    break

            if not stream_finished:
                if pending_tool_call_buffers:
                    yield self._create_tool_call_chunk(
                        requested_model,
                        self._build_stream_tool_calls(pending_tool_call_buffers),
                    )
                yield self._create_final_chunk(requested_model, start_time)

            # 스트림 종료 로그
            total_duration = time.time() - start_time
            logger.info(
                f"[Stream] ✅ 종료 | model={requested_model} | "
                f"duration={total_duration:.3f}초"
            )

        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(
                f"[Exception] ❌ {type(e).__name__} | model={requested_model} | "
                f"elapsed={elapsed:.3f}초 | message={str(e)}",
                exc_info=True,
            )

            # 예외 유형별 상세 로깅
            if isinstance(e, requests.exceptions.Timeout):
                logger.error(f"[Exception] ⏱️ 타임아웃 - upstream 응답 지연 가능성")
            elif isinstance(e, requests.exceptions.ConnectionError):
                logger.error(f"[Exception] 🔌 연결 오류 - 네트워크 또는 upstream 문제")

            yield self._create_error_chunk(requested_model, e)
        finally:
            if resp and not response_closed:
                resp.close()
                response_closed = True

    def handle_non_streaming_response(
        self, resp: Response, requested_model: str
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
            text_content = ""
            tool_calls: List[Dict[str, Any]] = []
            if "choices" in data and data["choices"]:
                message = data["choices"][0].get("message", {})
                text_content = self._extract_text_from_message_like(message)
                tool_calls = self._normalize_tool_calls(message.get("tool_calls", []))

            # 응답에서 모델 이름 추출 (없으면 요청 모델 사용)
            response_model = data.get("model", requested_model)

            # Gemini Thinking 태그 필터링
            self._in_thought_tag = False
            if text_content and (
                "<thought>" in text_content or "</thought>" in text_content
            ):
                logger.info(
                    "[Thinking Mode] 비스트리밍 응답에서 thought 태그 감지 - 필터링 수행"
                )
                text_content = self._filter_thought_tags(text_content)

            # Ollama 형식 응답 생성
            response = self._build_base_chunk(response_model)
            message: Dict[str, Any] = {
                "role": "assistant",
                "content": text_content.strip(),
            }
            if tool_calls:
                message["tool_calls"] = tool_calls

            response.update({"message": message, "done": True})
            return response

        except json.JSONDecodeError as e:
            logger.error(f"API 응답 JSON 디코딩 실패: {e}", exc_info=True)
            return ErrorHandler.create_error_response(
                requested_model, "Failed to decode API response"
            )
        except Exception as e:
            logger.error(f"API 응답 처리 중 오류: {e}", exc_info=True)
            return ErrorHandler.create_error_response(requested_model, str(e))
