# 2026-03-17 Research: `ollama-cloud:minimax-m2.5` tool-call 응답 끊김 분석

## 문제 정리

- 사용자 제보: `ollama-cloud:minimax-m2.5` 사용 시 응답이 중간에 끊기며, tool 관련 처리 이상이 의심됨.
- 조사 범위:
  - Ollama 호환 엔드포인트 `/api/chat`
  - OpenAI 호환 엔드포인트 `/v1/chat/completions`
  - 공통 프록시 라우팅 `ChatHandler`
  - OpenAI SSE -> Ollama NDJSON 변환 `ResponseHandler`

## 코드 경로와 현재 동작

### 1. 모델 라우팅

파일: `src/handlers/chat.py`

- `ollama-cloud:*` 및 `ollama:*` prefix는 `StandardApiClient`를 통해 `https://ollama.com/v1/chat/completions`로 전달됨.
- 요청 payload에는 `messages`, `model`, `stream`이 기본 포함됨.
- `tools`, `tool_choice`도 `handle_chat_request()`에서는 포함하도록 이미 구현되어 있음.

### 2. OpenAI 호환 라우트

파일: `src/routes/openai.py`

- `/v1/chat/completions`는 사용자 요청을 `proxied_req`로 재구성한 뒤 `ChatHandler.handle_chat_request()`에 전달함.
- 현재 `proxied_req`에는 `tools`, `tool_choice`가 누락되어 있음.
- 결과적으로 OpenAI 클라이언트가 도구 정의를 보내도 백엔드 제공업체에는 전달되지 않음.
- 이 문제는 tool 사용 자체를 무력화하거나, 클라이언트 기대와 실제 모델 동작을 어긋나게 만들 수 있음.

### 3. Ollama 스트리밍 응답 변환

파일: `src/handlers/response.py`

- `handle_streaming_response()`는 OpenAI 스타일 SSE를 읽고 Ollama NDJSON로 변환함.
- `_extract_chunk_content()`는 현재 `(text_content, finish_reason)`만 반환함.
- `delta.tool_calls`는 완전히 무시됨.
- 종료 조건은 `finish_reason == "stop"`만 처리함.
- 따라서 `finish_reason == "tool_calls"`인 경우:
  - tool call 정보가 Ollama 응답에 포함되지 않음
  - final chunk가 생성되지 않음
  - upstream 연결 종료 시점에만 스트림이 닫혀 클라이언트 입장에서는 응답이 비정상 종료되거나 중간에 끊긴 것처럼 보일 수 있음

### 4. Ollama 비스트리밍 응답 변환

파일: `src/handlers/response.py`

- `handle_non_streaming_response()`는 `choices[0].message.content`만 읽음.
- `message.tool_calls`는 무시됨.
- tool 호출이 본문 대신 `tool_calls`로 반환되는 모델에서는 Ollama 형식 응답이 손실됨.

### 5. Google 전용 Ollama 스트림 경로

파일: `src/routes/ollama.py`

- `inspect.isgenerator(resp)` 분기에서 Google provider 전용 변환기를 따로 구현함.
- 이 경로도 `delta.content`와 `finish_reason == "stop"`만 처리하고 `delta.tool_calls`를 무시함.
- 현재 사용자 제보 대상은 `ollama-cloud`이므로 직접 원인은 아니지만, 동일한 버그 패턴이 존재함.

## 관찰된 결함

### 결함 A. `tool_calls` 종료 처리 누락

- `finish_reason == "tool_calls"`는 정상적인 한 턴 종료 상태인데 final chunk 생성이 안 됨.
- Ollama 클라이언트는 `done: true`를 받지 못해 응답이 끊긴 것처럼 해석할 수 있음.

### 결함 B. `delta.tool_calls` 매핑 누락

- OpenAI 호환 응답의 핵심 데이터가 `message.tool_calls`로 번역되지 않음.
- 툴 호출 모델의 동작이 사실상 손실됨.

### 결함 C. `/v1/chat/completions`에서 tool 정의 유실

- OpenAI SDK 계열 클라이언트가 tools를 보내도 프록시 단계에서 누락됨.
- 모델/클라이언트 간 계약이 깨짐.

## 기대 동작

### Ollama 호환 응답

- 스트리밍 청크와 비스트리밍 응답 모두 `message.tool_calls`를 유지해야 함.
- `finish_reason == "tool_calls"`도 정상 종료로 간주해 `done: true` final chunk를 생성해야 함.
- 텍스트와 tool_calls가 함께 존재할 수도 있으므로 둘 다 보존해야 함.

### OpenAI 호환 프록시

- 클라이언트가 보낸 `tools`, `tool_choice`를 백엔드 제공업체로 그대로 전달해야 함.

## 수정 후보

### 후보 1. `ResponseHandler` 확장

- `_extract_chunk_content()`를 일반화해 텍스트, tool_calls, finish_reason을 함께 반환
- OpenAI tool_calls를 Ollama message.tool_calls 형태로 변환
- `stop`, `tool_calls`, `length` 등 종료 이유를 final chunk 생성 트리거로 인정

장점:
- `ollama-cloud`, `openrouter`, `cohere`, `nvidia-nim` 등 `ResponseHandler`를 타는 모든 표준 제공업체에 동일하게 적용 가능

주의:
- Ollama 형식의 `tool_calls` 스키마를 일관되게 유지해야 함

### 후보 2. `openai.py` 프록시 요청 보완

- `tools`, `tool_choice`를 `proxied_req`에 추가

장점:
- OpenAI SDK 기반 클라이언트에서도 실제 도구 호출 가능

### 후보 3. Google 전용 스트림 변환기 동기화

- 현재 사용자 문제와 직접 경로는 아니지만 동일한 손실 버그가 있음
- `ResponseHandler`와 동일한 규칙으로 맞추는 편이 안전함

## 작업 시 주의사항

- 현재 작업 트리에 사용자 수정이 존재함:
  - `README.md`
  - `config.py`
  - `docker-compose.yml`
  - `models.json`
  - `run-dev.sh`
  - `src/handlers/chat.py`
- `src/handlers/chat.py`는 이미 `ollama-cloud` provider 추가 작업이 반영되어 있으므로 덮어쓰지 말고 최소 수정 원칙 적용 필요

## 결론

사용자 제보와 가장 직접적으로 연결되는 원인은 `ResponseHandler`의 tool-call 무시 및 종료 누락이다. 여기에 `/v1/chat/completions`의 `tools` 전달 누락까지 함께 수정해야, Ollama 호환 경로와 OpenAI 호환 경로 모두에서 `minimax-m2.5`의 tool 사용이 일관되게 동작한다.
