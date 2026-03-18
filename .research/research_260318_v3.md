# Research 260318 v3

## 주제
Anthropic `/v1/messages` 경로에서 툴 사용 후 후속 응답이 끊기는 문제 분석

## 조사 범위
- `src/routes/anthropic.py`
- `src/handlers/anthropic.py`
- `src/handlers/chat.py`
- `src/core/errors.py`
- 최근 20분 Docker 로그

## 관찰 내용

### 1. 첫 번째 tool_use 응답 자체는 정상 종료됨
`ollama-proxy` 로그에서 아래 패턴이 반복적으로 확인됩니다.

- `Anthropic /v1/messages request`
- `Anthropic streaming response start`
- `[AnthropicStream] tool 블록 시작`
- `[AnthropicStream] finish_reason 수신 | raw=tool_calls | mapped=tool_use`
- `[AnthropicStream] [DONE] 수신`
- `[AnthropicStream] ✅ 종료`

즉, 모델이 tool call 을 반환하는 첫 스트림은 중간에 끊기는 것이 아니라 정상적으로 `tool_use` 종료 상태로 닫히고 있습니다.

### 2. 끊김은 tool_result 이후의 후속 요청에서 발생함
tool_use 직후 클라이언트가 tool result 를 포함한 다음 `/v1/messages` 요청을 다시 보내고 있습니다. 이 후속 요청들에서 `src.utils.tokenizer` 경고가 누적되다가 결국 아래 오류가 발생합니다.

- `요청의 추정 토큰 수(128132~128135)가 모델 ollama-cloud:kimi-k2.5의 최대 컨텍스트 윈도우(128000 tokens)를 초과`

로그 시퀀스상 tool 사용 횟수가 늘어날수록 메시지 전체 길이가 증가하고, 최종적으로 context window 초과로 이어집니다.

### 3. context 초과 시 반환 타입이 Anthropic 스트리밍 계약과 맞지 않음
`src/handlers/chat.py:178-183` 에서 context 초과가 나면 `ErrorHandler.create_error_response(...)` 를 반환합니다. 이 함수는 Ollama 형식 dict 를 만듭니다.

`src/core/errors.py`:
- `{"model": ..., "message": {"role": "assistant", "content": "오류 발생: ..."}, "done": True, "error": ...}`

문제는 `src/routes/anthropic.py:75-96` 의 분기입니다.

- 스트리밍 응답은 `inspect.isgenerator(resp) or hasattr(resp, 'iter_lines')` 일 때만 SSE 로 처리합니다.
- context 초과 시 `resp` 는 dict 이므로 스트리밍 분기에 들어가지 않습니다.
- 이후 `handle_non_streaming_response(resp, requested_model)` 로 진입합니다.
- 이 함수는 OpenAI 호환 `choices[0].message` 구조를 기대하지만, 실제 입력은 Ollama 에러 dict 입니다.
- 결과적으로 route 는 `Anthropic non-streaming response success` 로그를 남기고, stream 요청이었음에도 `application/json` 200 응답을 돌려줍니다.

이는 Anthropic 스트리밍 클라이언트 입장에서 "tool 사용 후 갑자기 스트림이 끊긴 것처럼" 보이게 만드는 가장 유력한 원인입니다.

### 4. 현재 증상과 직접 관련 없는 부수 이슈

#### Antigravity 503
`antigravity:anti-claude-opus-4-6-thinking` 요청은 별도로 capacity exhausted 로 503 이 발생하고 있습니다. 이는 tool_use 후 끊김의 주원인과는 다른 축입니다.

#### Gunicorn worker timeout
한 차례 `WORKER TIMEOUT` 이 있었고, 이는 upstream POST 대기 중 발생했습니다. 이것도 별도 안정성 이슈이지만, 이번 `kimi-k2.5` tool_use 재현 로그에서는 context 초과 경로가 더 직접적입니다.

### 5. 메시지 정규화 자체는 현재 증상과 직접 충돌하지 않음
`src/handlers/anthropic.py` 의 `_normalize_messages` 는 다음을 보장하도록 최근 테스트가 추가되어 있습니다.

- assistant text + tool_use 를 하나의 assistant message 로 유지
- user 의 tool_result 를 `tool` role 로 변환
- tool_result 이후 user text 보존

`tests/test_anthropic_handler.py` 는 해당 케이스를 통과합니다. 따라서 현재 로그와 합치면 "tool 결과 메시지 구조가 잘못되어 끊김"보다는 "후속 요청이 커져 context 초과 후 에러 응답 계약이 깨짐" 쪽이 더 타당합니다.

## 결론
현재 가장 가능성이 높은 직접 원인은 다음 두 가지의 조합입니다.

1. tool_use 이후 누적된 대화 길이로 인해 후속 `/v1/messages` 요청이 context window 를 초과함
2. 그 초과 오류를 Anthropic route 가 스트리밍 호환 에러로 변환하지 못하고 일반 JSON 200 응답으로 반환함

즉, 사용자가 체감하는 "툴 사용 후 응답 끊김"은 tool stream 변환 자체보다는 **tool 이후 후속 요청 실패 + 잘못된 에러 응답 형태** 문제로 해석하는 것이 가장 정확합니다.

## 수정 방향 초안
- `ChatHandler.handle_chat_request()` 의 반환 타입을 성공 응답과 오류 응답으로 명확히 분리
- Anthropic route 에서 context 초과/사전 검증 실패를 Anthropic 호환 에러 응답으로 변환
- `stream=True` 요청이라도 사전 검증 실패는 명시적 HTTP 에러 + Anthropic error body 로 반환
- 회귀 테스트 추가:
  - stream 요청 + context 초과 시 JSON 200 이 아닌 Anthropic error 응답 확인
  - tool_use 이후 누적 메시지로 재현되는 경로 검증
