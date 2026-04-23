# -*- coding: utf-8 -*-
"""
Thought 태그 필터 유틸리티

Gemini Thinking 모드의 <thought>...</thought> 태그를 필터링합니다.
스트리밍 응답에서는 태그가 여러 청크에 걸쳐 나뉘어 올 수 있으므로,
클래스 인스턴스로 상태를 추적합니다.
"""
from typing import List


class ThoughtTagFilter:
    """<thought>...</thought> 태그 내용을 필터링하는 상태 기반 필터."""

    def __init__(self) -> None:
        self._in_thought_tag: bool = False

    @property
    def in_thought_tag(self) -> bool:
        """현재 thought 태그 내부에 있는지 여부를 반환합니다."""
        return self._in_thought_tag

    def reset(self) -> None:
        """필터 상태를 초기화합니다."""
        self._in_thought_tag = False

    def filter(self, text: str) -> str:
        """텍스트에서 <thought>...</thought> 태그 내용을 제거합니다.

        Args:
            text: 필터링할 텍스트

        Returns:
            thought 태그가 제거된 텍스트
        """
        result: List[str] = []
        i = 0
        while i < len(text):
            if self._in_thought_tag:
                end_tag = "</thought>"
                if text[i:].startswith(end_tag):
                    self._in_thought_tag = False
                    i += len(end_tag)
                    continue
                i += 1
                continue

            start_tag = "<thought>"
            if text[i:].startswith(start_tag):
                self._in_thought_tag = True
                i += len(start_tag)
                continue

            result.append(text[i])
            i += 1

        return "".join(result)
