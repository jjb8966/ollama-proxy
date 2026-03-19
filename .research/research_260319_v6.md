## max context 초과 시 compact 안내 메시지 반환 변경

### 요청 배경
- 기존 구현은 요청 payload가 모델 context 임계값을 넘으면 내부 compact 모델을 호출해 요약 결과를 최종 응답으로 반환했다.
- 사용자는 이 동작을 원하지 않고, compact 실행 대신 "max context를 넘었으니 compact 하라"는 메시지만 내려보내도록 변경을 요청했다.

### 현재 구조 확인
- `src/handlers/chat.py`
  - `_maybe_compact_request()` 가 threshold 초과 시 `_build_compaction_request()` 로 내부 모델 요청을 만들고 `handle_chat_request()` 를 재호출한다.
  - 즉 현재는 실제 provider 호출이 발생한다.
- `src/routes/openai.py`
  - `handle_chat_request()` 가 `dict` 를 반환하면 그대로 JSON `200` 응답으로 내려간다.
  - `stream=True` 일 때 generator를 반환하면 SSE 스트림으로 내려간다.
- `src/routes/ollama.py`
  - `dict` 의 OpenAI 형식 `choices[0].message.content` 는 Ollama 형식 응답으로 변환된다.
  - `stream=True` generator는 OpenAI SSE 형식을 기대한다.

### 변경 설계
1. 내부 compact 요청 생성 로직 제거
2. threshold 초과 시 안내 메시지 응답 생성
3. 비스트리밍
   - OpenAI 호환 `dict` 응답 반환
4. 스트리밍
   - OpenAI SSE 형식 generator 반환
   - 첫 chunk에 안내 메시지 content
   - 마지막에 `[DONE]`

### 메시지 내용
- 요약 결과가 아니라, 요청이 context 임계값을 초과했으므로 compact 후 다시 시도하라는 안내만 포함
- 디버깅에 필요한 수치:
  - 요청 모델
  - 추정 토큰 수
  - context 길이
  - compact 임계값

### 영향 범위
- `src/handlers/chat.py`
- `tests/test_chat_handler_limits.py`
