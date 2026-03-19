# -*- coding: utf-8 -*-
"""
Ollama 호환 API 라우트

/api/chat, /api/tags, /api/version 등 Ollama 스타일 엔드포인트를 정의합니다.
"""

import inspect
import json
import logging
import os
from flask import Blueprint, request, Response, stream_with_context, current_app

from src.core.errors import ProxyRequestError
from src.handlers.chat import ChatHandler
from src.handlers.response import ResponseHandler


logger = logging.getLogger(__name__)
response_handler = ResponseHandler()

# Blueprint 생성
ollama_bp = Blueprint("ollama", __name__)


def _load_models() -> list:
    """models.json 파일에서 모델 목록을 로드합니다."""
    models_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "models.json"
    )
    try:
        with open(models_path, "r") as f:
            data = json.load(f)
            return data.get("models", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"models.json 로드 실패, 기본 목록 사용: {e}")
        return []


@ollama_bp.route("/", methods=["GET"])
@ollama_bp.route("/api/version", methods=["GET"])
def get_version():
    """
    버전 정보를 반환합니다.

    Ollama의 /api/version 및 루트 경로(/)를 모방합니다.
    """
    logger.info("버전 정보 요청 수신")
    version_response = {"version": "0.1.0-openai-proxy"}
    return Response(
        json.dumps(version_response), status=200, mimetype="application/json"
    )


@ollama_bp.route("/api/tags", methods=["GET"])
def get_tags():
    """
    사용 가능한 모델 목록을 반환합니다.

    Ollama의 /api/tags 엔드포인트를 모방합니다.
    models.json 파일에서 모델 목록을 로드합니다.
    """
    models = _load_models()

    # models.json이 없으면 기본 목록 반환
    if not models:
        models = [
            {
                "name": "google:gemini-3.1-flash-lite-preview",
                "model": "google:gemini-3.1-flash-lite-preview",
            },
            {"name": "google:gemini-2.5-flash", "model": "google:gemini-2.5-flash"},
            {
                "name": "openrouter:mistralai/devstral-2512:free",
                "model": "openrouter:mistralai/devstral-2512:free",
            },
            {"name": "cohere:command-a-03-2025", "model": "cohere:command-a-03-2025"},
            {"name": "qwen:qwen3-coder-plus", "model": "qwen:qwen3-coder-plus"},
        ]

    response = {"models": models}
    return Response(json.dumps(response), status=200, mimetype="application/json")


@ollama_bp.route("/api/chat", methods=["POST"])
def chat():
    """
    채팅 요청을 처리합니다.

    Ollama 형식의 요청을 받아 OpenAI 호환 API로 전달하고,
    응답을 Ollama 형식으로 변환하여 반환합니다.

    스트리밍/비스트리밍 모드를 모두 지원합니다.
    """
    api_config = current_app.config["api_config"]
    chat_handler = ChatHandler(api_config)
    req = request.get_json(force=True)
    requested_model = req.get("model")
    stream = req.get("stream", True)

    # API 요청 처리
    resp = chat_handler.handle_chat_request(req)
    if resp is None:
        error_response = {"error": "API request failed"}
        return Response(
            json.dumps(error_response), status=500, mimetype="application/json"
        )

    if isinstance(resp, ProxyRequestError):
        return Response(
            json.dumps(resp.to_ollama_response()),
            status=resp.status_code,
            mimetype="application/json",
        )

    if isinstance(resp, dict):
        text_content = ""
        tool_calls = []
        if "choices" in resp and resp["choices"]:
            message = resp["choices"][0].get("message", {})
            text_content = response_handler._extract_text_from_message_like(message)
            tool_calls = response_handler._normalize_tool_calls(
                message.get("tool_calls", [])
            )
        import datetime

        message = {"role": "assistant", "content": text_content}
        if tool_calls:
            message["tool_calls"] = tool_calls
        ollama_response = {
            "model": requested_model,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "message": message,
            "done": True,
        }
        return Response(json.dumps(ollama_response), mimetype="application/json")

    if stream and inspect.isgenerator(resp):

        def google_stream_to_ollama():
            start_time = __import__("time").time()
            in_thought = False
            pending_tool_calls = {}
            stream_finished = False

            def normalize_tool_arguments(arguments):
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

            def build_tool_calls():
                tool_calls = []
                for index in sorted(pending_tool_calls.keys()):
                    state = pending_tool_calls[index]
                    name = state.get("name", "")
                    if not name:
                        continue
                    tool_calls.append(
                        {
                            "function": {
                                "name": name,
                                "arguments": normalize_tool_arguments(
                                    state.get("arguments", "")
                                ),
                            }
                        }
                    )
                return tool_calls

            for sse_line in resp:
                if not sse_line.strip():
                    continue
                if sse_line.startswith("data: [DONE]"):
                    tool_calls = build_tool_calls()
                    if tool_calls:
                        ollama_chunk = {
                            "model": requested_model,
                            "created_at": __import__("datetime")
                            .datetime.utcnow()
                            .isoformat()
                            + "Z",
                            "message": {
                                "role": "assistant",
                                "content": "",
                                "tool_calls": tool_calls,
                            },
                            "done": False,
                        }
                        yield json.dumps(ollama_chunk) + "\n"
                    duration_ns = int((__import__("time").time() - start_time) * 1e9)
                    final = {
                        "model": requested_model,
                        "created_at": __import__("datetime")
                        .datetime.utcnow()
                        .isoformat()
                        + "Z",
                        "message": {"role": "assistant", "content": ""},
                        "done": True,
                        "total_duration": duration_ns,
                        "eval_duration": duration_ns,
                    }
                    yield json.dumps(final) + "\n"
                    stream_finished = True
                    break
                if sse_line.startswith("data: "):
                    try:
                        chunk = json.loads(sse_line[6:])
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})
                        text = response_handler._extract_text_from_message_like(delta)
                        finish_reason = choices[0].get("finish_reason")

                        filtered = []
                        i = 0
                        while i < len(text):
                            if in_thought:
                                end = text.find("</thought>", i)
                                if end == -1:
                                    break
                                in_thought = False
                                i = end + len("</thought>")
                            else:
                                start = text.find("<thought>", i)
                                if start == -1:
                                    filtered.append(text[i:])
                                    break
                                filtered.append(text[i:start])
                                in_thought = True
                                i = start + len("<thought>")
                        text = "".join(filtered)

                        if text:
                            ollama_chunk = {
                                "model": requested_model,
                                "created_at": __import__("datetime")
                                .datetime.utcnow()
                                .isoformat()
                                + "Z",
                                "message": {"role": "assistant", "content": text},
                                "done": False,
                            }
                            yield json.dumps(ollama_chunk) + "\n"

                        for index, tool_call in enumerate(delta.get("tool_calls", [])):
                            if not isinstance(tool_call, dict):
                                continue
                            state = pending_tool_calls.setdefault(
                                index, {"name": "", "arguments": ""}
                            )
                            function_info = tool_call.get("function", {})
                            if not isinstance(function_info, dict):
                                function_info = {}
                            if function_info.get("name"):
                                state["name"] = str(function_info.get("name"))
                            if isinstance(function_info.get("arguments"), str):
                                state["arguments"] += function_info.get("arguments")
                            elif function_info.get("arguments") is not None:
                                state["arguments"] += json.dumps(
                                    function_info.get("arguments"), ensure_ascii=False
                                )

                        if finish_reason in ("stop", "tool_calls", "length"):
                            tool_calls = build_tool_calls()
                            if tool_calls:
                                ollama_chunk = {
                                    "model": requested_model,
                                    "created_at": __import__("datetime")
                                    .datetime.utcnow()
                                    .isoformat()
                                    + "Z",
                                    "message": {
                                        "role": "assistant",
                                        "content": "",
                                        "tool_calls": tool_calls,
                                    },
                                    "done": False,
                                }
                                yield json.dumps(ollama_chunk) + "\n"
                                pending_tool_calls.clear()
                            duration_ns = int(
                                (__import__("time").time() - start_time) * 1e9
                            )
                            final = {
                                "model": requested_model,
                                "created_at": __import__("datetime")
                                .datetime.utcnow()
                                .isoformat()
                                + "Z",
                                "message": {"role": "assistant", "content": ""},
                                "done": True,
                                "total_duration": duration_ns,
                                "eval_duration": duration_ns,
                                "done_reason": finish_reason,
                            }
                            yield json.dumps(final) + "\n"
                            stream_finished = True
                            break
                    except (json.JSONDecodeError, KeyError):
                        continue

            if not stream_finished:
                tool_calls = build_tool_calls()
                if tool_calls:
                    ollama_chunk = {
                        "model": requested_model,
                        "created_at": __import__("datetime")
                        .datetime.utcnow()
                        .isoformat()
                        + "Z",
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": tool_calls,
                        },
                        "done": False,
                    }
                    yield json.dumps(ollama_chunk) + "\n"
                duration_ns = int((__import__("time").time() - start_time) * 1e9)
                final = {
                    "model": requested_model,
                    "created_at": __import__("datetime").datetime.utcnow().isoformat()
                    + "Z",
                    "message": {"role": "assistant", "content": ""},
                    "done": True,
                    "total_duration": duration_ns,
                    "eval_duration": duration_ns,
                }
                yield json.dumps(final) + "\n"

        return Response(
            stream_with_context(google_stream_to_ollama()),
            mimetype="application/x-ndjson",
        )

    # 스트리밍/비스트리밍 응답 처리
    if stream:
        max_tokens = req.get("max_tokens")
        generator = response_handler.handle_streaming_response(
            resp, requested_model, max_tokens
        )
        return Response(stream_with_context(generator), mimetype="application/x-ndjson")
    else:
        ollama_response = response_handler.handle_non_streaming_response(
            resp, requested_model
        )
        return Response(json.dumps(ollama_response), mimetype="application/json")
