# 연구 보고서: 80% 초과 시 compact 응답 전환

**작성일:** 2026-03-19
**관련 요청:** max context 80% 초과 시 `antigravity:anti-gemini-3.1-pro-high`를 사용한 compact 응답 반환

---

## 1. 목표

기존에는 `max_tokens` 상한만 로컬에서 검증하고, 실제 입력 context 초과는 업스트림 overflow 응답을 정규화해 반환했습니다.

이번 변경 목표는 다음과 같습니다.

1. 요청 페이로드가 대상 모델 `max context`의 80%를 초과하면 원 모델 호출을 중단
2. `antigravity:anti-gemini-3.1-pro-high` 모델로 compact 요약 요청 수행
3. compact 결과를 최종 응답으로 그대로 반환

---

## 2. 현재 구조 분석

### 2.1 요청 진입점

- OpenAI: `src/routes/openai.py`
- Ollama: `src/routes/ollama.py`
- Anthropic: `src/routes/anthropic.py`

세 경로 모두 결국 `ChatHandler.handle_chat_request()`를 호출합니다.

즉, compact 전환은 `ChatHandler`에서 처리하는 것이 가장 일관적입니다.

### 2.2 현재 에러 처리

- `src/handlers/chat.py`
  - `max_tokens`만 사전 검증
- `src/providers/base.py`
  - 업스트림 `context overflow` 응답을 감지해 `ProxyRequestError`로 정규화

현재는 초과 시 실패를 반환할 뿐, 자동 요약으로 전환하지는 않습니다.

---

## 3. 구현 설계

### 3.1 compact 트리거 기준

- 기준 모델: 원래 요청된 `requested_model`
- 기준 한도: `models.json`의 `context_length`
- 기준 비율: `80%`

`messages`, `tools`, `tool_choice`, `max_tokens`를 포함한 요청 본문을 JSON 직렬화하고, 이를 기반으로 추정 토큰 수를 계산합니다.

정밀 provider 토크나이저는 현재 프로젝트에 없으므로, compact 트리거는 근사치 기반으로 구현합니다.
이번 로직은 "실패 차단"이 아니라 "사전 요약 유도"이므로, 보수적인 근사 추정이 적합합니다.

### 3.2 compact 요청 모델

- 고정 모델: `antigravity:anti-gemini-3.1-pro-high`
- compact 요청은 내부 플래그로 재귀 compact를 막아야 함

### 3.3 compact 프롬프트 적용 방식

사용자가 제공한 프롬프트는 그대로 `system` 메시지에 넣습니다.

별도의 `user` 메시지에는 아래를 JSON으로 전달합니다.

- 원래 요청 모델
- 원래 요청의 추정 토큰 수
- 원래 모델 context length
- 원래 messages
- 원래 tools
- 원래 tool_choice

### 3.4 응답 반환 방식

compact 요청의 결과를 그대로 반환합니다.

이 방식의 장점:

- 원 요청이 `stream=True`이면 compact 모델도 스트리밍 가능
- OpenAI/Ollama/Anthropic 라우트별 기존 응답 변환 로직을 그대로 재사용 가능
- 별도 synthetic response 생성이 필요 없음

### 3.5 주의점

이 변경은 "원 요청을 계속 처리"하지 않습니다.
80% 초과 시에는 compact 응답이 최종 응답입니다.

---

## 4. 결론

구현 위치는 `ChatHandler`가 적절합니다.

필요 변경:

1. 요청 페이로드 추정 토큰 계산 함수 추가
2. 80% 초과 판단 함수 추가
3. compact 요청 생성 함수 추가
4. `ChatHandler.handle_chat_request()` 초반에 compact 분기 추가
5. compact 분기를 검증하는 테스트 추가

