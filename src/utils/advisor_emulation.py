# -*- coding: utf-8 -*-
"""
Advisor 도구 에뮬레이션 유틸리티

Claude Code가 advisor 도구 호출을 요청했을 때 ADVISOR_MODEL로 별도 요청을 보내고
advisor_tool_result 블록을 반환합니다.
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional


DEFAULT_ADVISOR_MODEL = "cli-proxy-api-plus:gpt-5.5-high"


def resolve_advisor_model() -> str:
    """ADVISOR_MODEL 환경변수 또는 기본값 반환"""
    value = os.environ.get("ADVISOR_MODEL", DEFAULT_ADVISOR_MODEL)
    if not isinstance(value, str):
        return DEFAULT_ADVISOR_MODEL
    stripped = value.strip()
    return stripped or DEFAULT_ADVISOR_MODEL


def has_advisor_tool(req: Dict[str, Any]) -> bool:
    """tools 목록에 advisor 도구가 있는지 확인"""
    tools = req.get("tools")
    if not isinstance(tools, list):
        return False
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name", "")).strip().lower()
        if name == "advisor":
            return True
    return False


def is_advisor_forced_request(req: Dict[str, Any]) -> bool:
    """advisor 도구가 있고 tool_choice로 강제 호출된 요청인지 확인"""
    if not has_advisor_tool(req):
        return False
    tool_choice = req.get("tool_choice")
    if not isinstance(tool_choice, dict):
        return False
    if tool_choice.get("type") != "tool":
        return False
    name = str(tool_choice.get("name", "")).strip().lower()
    return name == "advisor"


def find_advisor_tool_use_id(messages: Any) -> str:
    """히스토리에서 마지막 advisor tool_use 블록의 id를 찾거나 새로 생성"""
    if not isinstance(messages, list):
        return f"srvtoolu_{uuid.uuid4().hex}"
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            if str(block.get("name", "")).strip().lower() != "advisor":
                continue
            tool_id = block.get("id")
            if isinstance(tool_id, str) and tool_id.strip():
                return tool_id.strip()
    return f"srvtoolu_{uuid.uuid4().hex}"


def advisor_tool_result_text(block: Dict[str, Any]) -> str:
    """advisor_tool_result 또는 advisor_tool_result_error 블록에서 텍스트 추출"""
    if not isinstance(block, dict):
        return ""
    block_type = str(block.get("type", "")).strip().lower()
    if block_type == "advisor_tool_result_error":
        content = block.get("content")
        if isinstance(content, dict):
            message = content.get("message") or content.get("text")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(content, str) and content.strip():
            return content.strip()
        return "[advisor error]"

    content = block.get("content")
    if isinstance(content, dict):
        if str(content.get("type", "")).strip().lower() == "advisor_result":
            text = content.get("text")
            if isinstance(text, str):
                return text
        text = content.get("text")
        if isinstance(text, str):
            return text
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def build_advisor_result_block(tool_use_id: str, text: str) -> Dict[str, Any]:
    """정상 advisor 응답 블록 생성"""
    return {
        "type": "advisor_tool_result",
        "tool_use_id": tool_use_id,
        "content": {
            "type": "advisor_result",
            "text": text or "",
        },
    }


def build_advisor_error_block(tool_use_id: str, message: str) -> Dict[str, Any]:
    """오류 advisor 응답 블록 생성"""
    return {
        "type": "advisor_tool_result_error",
        "tool_use_id": tool_use_id,
        "content": {
            "type": "advisor_error",
            "message": message or "advisor request failed",
        },
    }


def extract_openai_completion_text(resp: Any) -> str:
    """OpenAI 호환 응답(content)에서 텍스트만 추출"""
    if resp is None:
        return ""
    data = resp
    if not isinstance(data, dict) and hasattr(resp, "json"):
        try:
            data = resp.json()
        except Exception:
            return ""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return "\n".join(parts)
    return ""
