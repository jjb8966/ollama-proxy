import json
import unittest

from src.handlers.response import ResponseHandler


class _DummyStreamingResponse:
    def __init__(self, lines):
        self._lines = [
            line.encode("utf-8") if isinstance(line, str) else line for line in lines
        ]
        self.closed = False

    def iter_lines(self):
        for line in self._lines:
            yield line

    def close(self):
        self.closed = True


class _DummyJsonResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class ResponseHandlerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = ResponseHandler()

    def test_non_streaming_uses_reasoning_when_content_is_empty(self) -> None:
        response = _DummyJsonResponse(
            {
                "model": "minimax-m2.7",
                "choices": [{"message": {"content": "", "reasoning": "ok"}}],
            }
        )

        result = self.handler.handle_non_streaming_response(
            response, "ollama-cloud:minimax-m2.7"
        )

        self.assertEqual(result["message"]["content"], "ok")

    def test_streaming_uses_reasoning_content_when_content_is_missing(self) -> None:
        response = _DummyStreamingResponse(
            [
                'data: {"choices":[{"delta":{"reasoning_content":"ok"},"finish_reason":null}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "data: [DONE]",
            ]
        )

        chunks = list(
            self.handler.handle_streaming_response(
                response, "ollama-cloud:minimax-m2.7"
            )
        )
        joined = "".join(chunks)

        self.assertIn('"content": "ok"', joined)
        self.assertTrue(response.closed)
