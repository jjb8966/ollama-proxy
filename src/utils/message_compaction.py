# -*- coding: utf-8 -*-
"""
메시지 자동 compaction 유틸리티

업스트림 context overflow 발생 시 대화 히스토리를 점진적으로 줄여 재시도합니다.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any, Dict, List, Optional, Tuple

TRUNCATION_SUFFIX = "\n\n[... truncated by ollama-proxy compaction ...]"
COMPACTION_NOTICE = (
    "[ollama-proxy] Earlier conversation history was automatically compacted "
    "because the request exceeded the model context window."
)

MIN_TAIL_MESSAGES = max(2, int(os.environ.get("COMPACTION_MIN_TAIL_MESSAGES", "6")))
TOOL_OUTPUT_TRUNCATE_CHARS = max(
    500, int(os.environ.get("COMPACTION_TOOL_TRUNCATE_CHARS", "8000"))
)
TOOL_OUTPUT_KEEP_CHARS = max(
    200, int(os.environ.get("COMPACTION_TOOL_KEEP_CHARS", "1200"))
)
CONTENT_TRUNCATE_CHARS = max(
    1000, int(os.environ.get("COMPACTION_CONTENT_TRUNCATE_CHARS", "6000"))
)


def estimate_request_tokens(req: Dict[str, Any]) -> int:
    messages = req.get("messages", [])
    total_chars = 0

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        total_chars += _estimate_message_chars(msg)

    tools = req.get("tools")
    if isinstance(tools, list):
        total_chars += len(json.dumps(tools, ensure_ascii=False, default=str))
    tool_choice = req.get("tool_choice")
    if tool_choice is not None:
        total_chars += len(json.dumps(tool_choice, ensure_ascii=False, default=str))

    return max(1, int(total_chars / 3.5))


def _estimate_message_chars(message: Dict[str, Any]) -> int:
    total_chars = 0
    content = message.get("content", "")
    if isinstance(content, str):
        total_chars += len(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                total_chars += len(str(block.get("text", "")))
            elif block.get("type") == "image_url":
                total_chars += 340
            else:
                total_chars += len(json.dumps(block, ensure_ascii=False, default=str))
    elif isinstance(content, dict):
        total_chars += len(json.dumps(content, ensure_ascii=False, default=str))

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        total_chars += len(json.dumps(tool_calls, ensure_ascii=False, default=str))

    return total_chars


def _truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    keep = max(0, max_chars - len(TRUNCATION_SUFFIX))
    return value[:keep] + TRUNCATION_SUFFIX


def _truncate_message_content(content: Any, max_chars: int) -> Any:
    if isinstance(content, str):
        return _truncate_text(content, max_chars)
    if not isinstance(content, list):
        return content

    truncated_blocks: List[Any] = []
    for block in content:
        if not isinstance(block, dict):
            truncated_blocks.append(block)
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = str(block.get("text", ""))
            truncated_blocks.append(
                {
                    **block,
                    "text": _truncate_text(text, max_chars),
                }
            )
        elif block_type in {"tool_result", "tool_use"}:
            text = str(block.get("content", block.get("text", "")))
            key = "content" if "content" in block else "text"
            truncated_blocks.append({**block, key: _truncate_text(text, max_chars)})
        else:
            serialized = json.dumps(block, ensure_ascii=False, default=str)
            if len(serialized) > max_chars:
                truncated_blocks.append(
                    {
                        "type": "text",
                        "text": _truncate_text(serialized, max_chars),
                    }
                )
            else:
                truncated_blocks.append(block)
    return truncated_blocks


def _truncate_tool_outputs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    changed = False
    compacted: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            compacted.append(message)
            continue

        role = str(message.get("role", ""))
        next_message = copy.deepcopy(message)

        if role == "tool":
            content = next_message.get("content", "")
            if isinstance(content, str) and len(content) > TOOL_OUTPUT_TRUNCATE_CHARS:
                next_message["content"] = _truncate_text(
                    content, TOOL_OUTPUT_KEEP_CHARS
                )
                changed = True
            elif isinstance(content, list):
                new_content = _truncate_message_content(content, TOOL_OUTPUT_KEEP_CHARS)
                if new_content != content:
                    next_message["content"] = new_content
                    changed = True
        elif role in {"user", "assistant"}:
            content = next_message.get("content")
            if isinstance(content, str) and len(content) > TOOL_OUTPUT_TRUNCATE_CHARS:
                next_message["content"] = _truncate_text(
                    content, TOOL_OUTPUT_KEEP_CHARS
                )
                changed = True
            elif isinstance(content, list):
                new_content = _truncate_message_content(content, TOOL_OUTPUT_KEEP_CHARS)
                if new_content != content:
                    next_message["content"] = new_content
                    changed = True

        compacted.append(next_message)

    if not changed:
        return messages
    return compacted


def _count_system_prefix(messages: List[Dict[str, Any]]) -> int:
    count = 0
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "system":
            count += 1
            continue
        break
    return count


def _drop_oldest_messages(
    messages: List[Dict[str, Any]],
    *,
    drop_count: int,
) -> Optional[List[Dict[str, Any]]]:
    if drop_count <= 0:
        return None

    system_prefix = _count_system_prefix(messages)
    tail_start = max(system_prefix, len(messages) - MIN_TAIL_MESSAGES)
    droppable_end = tail_start
    if droppable_end <= system_prefix:
        return None

    drop_end = min(system_prefix + drop_count, droppable_end)
    if drop_end <= system_prefix:
        return None

    compacted = [*messages[:system_prefix], *messages[drop_end:]]
    if len(compacted) >= len(messages):
        return None
    return compacted


def _truncate_all_non_system(messages: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    changed = False
    compacted: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            compacted.append(message)
            continue

        next_message = copy.deepcopy(message)
        if next_message.get("role") != "system":
            content = next_message.get("content")
            if isinstance(content, str):
                truncated = _truncate_text(content, CONTENT_TRUNCATE_CHARS)
                if truncated != content:
                    next_message["content"] = truncated
                    changed = True
            elif isinstance(content, list):
                truncated = _truncate_message_content(content, CONTENT_TRUNCATE_CHARS)
                if truncated != content:
                    next_message["content"] = truncated
                    changed = True

        compacted.append(next_message)

    if not changed:
        return None
    return compacted


def _keep_minimal_tail(messages: List[Dict[str, Any]]) -> Optional[List[Dict[str, Any]]]:
    system_messages = [
        copy.deepcopy(message)
        for message in messages
        if isinstance(message, dict) and message.get("role") == "system"
    ]
    tail = [
        copy.deepcopy(message)
        for message in messages[-2:]
        if isinstance(message, dict)
    ]
    if not tail:
        return None

    compacted = [*system_messages]
    if system_messages or len(messages) > len(tail):
        compacted.append({"role": "system", "content": COMPACTION_NOTICE})
    compacted.extend(tail)

    for message in compacted:
        if message.get("role") == "system" and message.get("content") == COMPACTION_NOTICE:
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _truncate_text(content, CONTENT_TRUNCATE_CHARS)
        elif isinstance(content, list):
            message["content"] = _truncate_message_content(
                content, CONTENT_TRUNCATE_CHARS
            )

    if _messages_fingerprint(compacted) == _messages_fingerprint(messages):
        return None
    return compacted


def _messages_fingerprint(messages: List[Dict[str, Any]]) -> str:
    return json.dumps(messages, ensure_ascii=False, sort_keys=True, default=str)


def apply_compaction_round(
    messages: List[Dict[str, Any]],
    round_index: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    한 단계 compaction을 적용합니다.

    Returns:
        (messages, changed)
    """
    if not isinstance(messages, list) or not messages:
        return messages, False

    original_fp = _messages_fingerprint(messages)

    if round_index <= 0:
        candidate = _truncate_tool_outputs(messages)
    elif round_index == 1:
        drop_count = max(1, (len(messages) - MIN_TAIL_MESSAGES) // 3)
        candidate = _drop_oldest_messages(messages, drop_count=drop_count) or messages
    elif round_index == 2:
        drop_count = max(2, (len(messages) - MIN_TAIL_MESSAGES) // 2)
        candidate = _drop_oldest_messages(messages, drop_count=drop_count) or messages
    elif round_index == 3:
        candidate = _truncate_all_non_system(messages) or messages
    else:
        candidate = _keep_minimal_tail(messages) or messages

    changed = _messages_fingerprint(candidate) != original_fp
    return candidate, changed


def build_compacted_request(
    req: Dict[str, Any],
    round_index: int,
) -> Optional[Dict[str, Any]]:
    messages = req.get("messages")
    if not isinstance(messages, list) or not messages:
        return None

    compacted_messages, changed = apply_compaction_round(messages, round_index)
    if not changed:
        return None

    compacted_req = copy.deepcopy(req)
    compacted_req["messages"] = compacted_messages
    compacted_req["_compaction_round"] = round_index + 1
    return compacted_req
