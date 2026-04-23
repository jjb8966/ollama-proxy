# -*- coding: utf-8 -*-
"""
텍스트 추출 및 도구 인자 파싱 유틸리티

여러 프로바이더 핸들러에서 중복 사용되는 텍스트 추출 로직을 공통화합니다.
"""
from typing import Any, Dict, List, Tuple


CONTENT_TEXT_KEYS: Tuple[str, ...] = (
    "content", "text", "value", "reasoning_content", "reasoning",
)

ANTHROPIC_TEXT_KEYS: Tuple[str, ...] = (
    "text", "value", "content",
)


def extract_text_from_content_value(
    content: Any, keys: Tuple[str, ...] = CONTENT_TEXT_KEYS
) -> str:
    """content 값에서 텍스트를 추출합니다.

    Args:
        content: str, list, dict 또는 기타 타입의 content 값
        keys: 검색할 키 이름 튜플 (순서대로 탐색)

    Returns:
        추출된 텍스트 문자열
    """
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
            for key in keys:
                value = item.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
                    break
        return "".join(parts)

    if isinstance(content, dict):
        for key in keys:
            value = content.get(key)
            if isinstance(value, str) and value:
                return value

    return ""


def parse_tool_arguments(arguments: Any) -> Dict[str, Any]:
    """OpenAI 호환 arguments를 Ollama 형식의 dict로 정규화합니다.

    Args:
        arguments: dict, str, None 또는 기타 타입의 도구 인자

    Returns:
        정규화된 딕셔너리
    """
    if isinstance(arguments, dict):
        return arguments

    if isinstance(arguments, str):
        stripped = arguments.strip()
        if not stripped:
            return {}
        try:
            import json
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            return {"input": arguments}
        if isinstance(parsed, dict):
            return parsed
        return {"input": parsed}

    if arguments is None:
        return {}

    return {"input": arguments}
