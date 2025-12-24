# -*- coding: utf-8 -*-
"""
Anthropic 호환 API 라우트

/v1/messages 등 Anthropic 스타일 엔드포인트를 정의합니다.
"""

import json
import logging
import uuid
from datetime import datetime
from flask import Blueprint, request, Response, stream_with_context, current_app

from src.handlers.chat import ChatHandler

logger = logging.getLogger(__name__)

# Blueprint 생성
anthropic_bp = Blueprint('anthropic', __name__, url_prefix='/v1')


def _convert_anthropic_to_openai_messages(anthropic_request: dict) -> list:
    """
    Anthropic 메시지 형식을 OpenAI 메시지 형식으로 변환합니다.
    
    Anthropic은 system을 별도 파라미터로 받지만, OpenAI는 messages 배열에 포함합니다.
    """
    messages = []
    
    # system 메시지 처리 (Anthropic은 별도 파라미터)
    system = anthropic_request.get('system')
    if system:
        messages.append({'role': 'system', 'content': system})
    
    # 일반 메시지 변환
    for msg in anthropic_request.get('messages', []):
        role = msg.get('role')
        content = msg.get('content')
        
        # content가 리스트인 경우 (멀티모달) 텍스트만 추출
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    text_parts.append(block.get('text', ''))
            content = '\n'.join(text_parts) if text_parts else ''
        
        messages.append({'role': role, 'content': content})
    
    return messages


def _generate_message_id() -> str:
    """Anthropic 형식의 메시지 ID를 생성합니다."""
    return f"msg_{uuid.uuid4().hex[:24]}"


def _create_anthropic_response(openai_response: dict, model: str) -> dict:
    """
    OpenAI 응답을 Anthropic 형식으로 변환합니다.
    """
    content_text = ""
    
    if 'choices' in openai_response and openai_response['choices']:
        message = openai_response['choices'][0].get('message', {})
        content_text = message.get('content', '')
    
    # usage 정보 추출 (없으면 기본값)
    usage = openai_response.get('usage', {})
    input_tokens = usage.get('prompt_tokens', 0)
    output_tokens = usage.get('completion_tokens', 0)
    
    return {
        "id": _generate_message_id(),
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": content_text}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens
        }
    }


def _generate_streaming_response(openai_stream, model: str):
    """
    OpenAI 스트리밍 응답을 Anthropic SSE 형식으로 변환합니다.
    """
    message_id = _generate_message_id()
    
    # message_start 이벤트
    message_start = {
        "type": "message_start",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": model,
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }
    }
    yield f"event: message_start\ndata: {json.dumps(message_start)}\n\n"
    
    # content_block_start 이벤트
    content_block_start = {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "text", "text": ""}
    }
    yield f"event: content_block_start\ndata: {json.dumps(content_block_start)}\n\n"
    
    # OpenAI 스트림에서 텍스트 추출 및 delta 이벤트 생성
    try:
        for chunk in openai_stream.iter_lines():
            if not chunk:
                continue
            
            decoded = chunk.decode('utf-8').strip()
            
            # SSE 코멘트 무시
            if decoded.startswith(':'):
                continue
            
            # data: 접두사 제거
            if decoded.startswith('data: '):
                decoded = decoded[6:]
            
            # 스트림 종료
            if decoded == '[DONE]':
                break
            
            try:
                data = json.loads(decoded)
                if 'choices' in data and data['choices']:
                    delta = data['choices'][0].get('delta', {})
                    text_content = delta.get('content', '')
                    
                    if text_content:
                        content_delta = {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": text_content}
                        }
                        yield f"event: content_block_delta\ndata: {json.dumps(content_delta)}\n\n"
                    
                    # 종료 이유 확인
                    finish_reason = data['choices'][0].get('finish_reason')
                    if finish_reason:
                        break
            except json.JSONDecodeError:
                continue
    finally:
        openai_stream.close()
    
    # content_block_stop 이벤트
    content_block_stop = {"type": "content_block_stop", "index": 0}
    yield f"event: content_block_stop\ndata: {json.dumps(content_block_stop)}\n\n"
    
    # message_delta 이벤트
    message_delta = {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
        "usage": {"output_tokens": 0}
    }
    yield f"event: message_delta\ndata: {json.dumps(message_delta)}\n\n"
    
    # message_stop 이벤트
    yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"


@anthropic_bp.route('/messages', methods=['POST'])
def create_message():
    """
    메시지 생성 요청을 처리합니다.
    
    Anthropic의 /v1/messages 엔드포인트를 모방합니다.
    요청을 내부 OpenAI 형식으로 변환하여 처리하고,
    응답을 Anthropic 형식으로 반환합니다.
    """
    api_config = current_app.config['api_config']
    chat_handler = ChatHandler(api_config)

    req = request.get_json(force=True)
    requested_model = req.get('model')
    
    # 모델 필수 검증
    if not requested_model:
        error_body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "model is required"
            }
        }
        return Response(
            json.dumps(error_body), 
            status=400, 
            mimetype='application/json'
        )
    
    # messages 필수 검증
    if not req.get('messages'):
        error_body = {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "messages is required"
            }
        }
        return Response(
            json.dumps(error_body), 
            status=400, 
            mimetype='application/json'
        )

    stream = req.get('stream', False)
    
    # Anthropic 메시지를 OpenAI 형식으로 변환
    openai_messages = _convert_anthropic_to_openai_messages(req)

    # OpenAI 형식 요청 구성
    proxied_req = {
        "model": requested_model,
        "messages": openai_messages,
        "stream": stream
    }

    # API 요청 처리
    resp = chat_handler.handle_chat_request(proxied_req)
    if resp is None:
        error_body = {
            "type": "error",
            "error": {
                "type": "api_error",
                "message": "API request failed"
            }
        }
        return Response(
            json.dumps(error_body), 
            status=500, 
            mimetype='application/json'
        )

    # Anthropic 형식으로 응답 변환
    if stream:
        return Response(
            stream_with_context(_generate_streaming_response(resp, requested_model)),
            mimetype='text/event-stream'
        )
    else:
        try:
            openai_response = resp.json()
            anthropic_response = _create_anthropic_response(openai_response, requested_model)
            return Response(
                json.dumps(anthropic_response),
                status=200,
                mimetype='application/json'
            )
        except Exception as e:
            logger.error(f"응답 변환 실패: {e}")
            error_body = {
                "type": "error",
                "error": {
                    "type": "api_error",
                    "message": f"Response conversion failed: {str(e)}"
                }
            }
            return Response(
                json.dumps(error_body),
                status=500,
                mimetype='application/json'
            )
