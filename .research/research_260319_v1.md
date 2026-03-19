# 연구 보고서: context 및 max_tokens 로직 교체

**작성일:** 2026-03-19
**참고 프로젝트:** `~/ref/opencode`

---

## 1. 요청 배경

현재 `ollama cloud minimax` 호출 실패 원인을 확인하는 과정에서, 프로젝트 내부의 `context` 및 `max_tokens` 처리 로직이 부분 구현 상태이며 실제 업스트림 요청 구조와 맞지 않는 점이 확인되었습니다. 사용자는 기존 로직을 전부 제거하고 `~/ref/opencode` 구현 방향을 참고해 다시 만들 것을 요청했습니다.

---

## 2. 현재 프로젝트 상태

### 2.1 현재 context 관련 구현 위치

- `src/utils/tokenizer.py`
  - `models.json`에서 `context_length`를 읽음
  - `messages`만 대상으로 토큰 수를 대략 추정함
  - `check_context_length(model_name, messages, max_tokens)` 제공
- `src/handlers/chat.py`
  - `handle_chat_request()` 초반에 `check_context_length()` 호출
  - 검증 실패 시 `ProxyRequestError` 반환

### 2.2 현재 구현의 문제점

1. 입력 토큰 추정이 요청 전체를 반영하지 않습니다.
   - 실제 업스트림에는 `messages`, `tools`, `tool_choice`가 함께 전달됩니다.
   - 현재 추정은 `messages`만 계산합니다.

2. `max_tokens` 검증이 부정확합니다.
   - 현재는 `max_tokens > context_length`만 검사합니다.
   - 실제로는 `입력 토큰 + 출력 예약 토큰` 관점으로 봐야 합니다.

3. 표준 provider 경로에서 `max_tokens` 자체가 업스트림으로 전달되지 않습니다.
   - `src/handlers/chat.py`의 표준 provider payload에는 `max_tokens`가 빠져 있습니다.
   - 따라서 로컬 검증과 실제 업스트림 요청의 조건이 불일치합니다.

4. 현재 로직은 계획 문서 기준으로도 미완성입니다.
   - `.plan/plan_260318.md`에는 관련 항목이 아직 `Pending` 상태로 남아 있습니다.

5. 모델 메타데이터가 불완전합니다.
   - `models.json`에는 현재 `context_length`만 있습니다.
   - 모델별 출력 한도 정보는 저장하지 않습니다.

### 2.3 현재 모델 메타데이터 저장 상태

현재 `models.json`은 아래 형태입니다.

```json
{
  "name": "ollama-cloud:minimax-m2.5",
  "model": "ollama-cloud:minimax-m2.5",
  "context_length": 128000
}
```

확인 결과:

- 저장 중인 정보
  - `context_length`
- 저장하지 않는 정보
  - `max_output_tokens`
  - 모델 입력 한도
  - provider별 출력 상한

즉, 현재는 모델별 `context`는 일부 저장하고 있지만, 모델별 `max token` 정보는 저장하지 않습니다.

---

## 3. `~/ref/opencode` 참고 구현 분석

### 3.1 모델 메타데이터 구조

`~/ref/opencode/packages/opencode/src/provider/models.ts`

레퍼런스는 모델 메타데이터를 `limit` 구조로 저장합니다.

```ts
limit: {
  context: number,
  input?: number,
  output: number
}
```

핵심은 다음입니다.

- `context`와 `output`을 분리해서 저장합니다.
- 출력 상한이 모델 메타데이터의 일부입니다.
- 런타임 로직은 이 값을 직접 사용합니다.

### 3.2 출력 토큰 상한 적용 방식

`~/ref/opencode/packages/opencode/src/provider/transform.ts`

```ts
export function maxOutputTokens(model: Provider.Model): number {
  return Math.min(model.limit.output, OUTPUT_TOKEN_MAX) || OUTPUT_TOKEN_MAX
}
```

핵심은 다음입니다.

- 모델이 허용하는 출력 상한을 메타데이터에서 가져옵니다.
- 전역 상한과 모델 상한 중 더 작은 값을 사용합니다.
- 요청마다 계산해서 실제 API 요청에 내려보냅니다.

### 3.3 컨텍스트 초과 처리 방식

`~/ref/opencode/packages/opencode/src/provider/error.ts`

레퍼런스는 다음 원칙을 가집니다.

- 사전 차단보다도 우선, 업스트림의 실제 컨텍스트 초과 오류를 신뢰합니다.
- provider별 다양한 초과 메시지를 정규식으로 `context_overflow`로 정규화합니다.
- 특정 provider가 조용히 overflow를 받아들이는 경우를 별도로 주석으로 경고합니다.

이 프로젝트에 바로 옮길 수 있는 핵심 원칙은 다음입니다.

1. 모델 메타데이터에 `context`와 `output`을 분리 저장할 것
2. 요청 payload에 실제 `max_tokens`를 전달할 것
3. 로컬 사전 검증은 정밀 토큰 추정 대신, 명백히 잘못된 요청만 차단할 것
4. 업스트림의 context overflow 오류를 별도 타입으로 정규화할 것
5. `400` 중에서도 overflow 계열은 재시도하지 않도록 할 것

---

## 4. 교체 구현에 필요한 변경점

### 4.1 제거 대상

- `src/utils/tokenizer.py` 전체
- `src/handlers/chat.py`의 `check_context_length()` 호출
- 기존 `context_length` 기반 조기 차단 로직

### 4.2 신규 구현 방향

1. 모델 메타데이터 구조 재설계
   - `models.json`에 최소한 아래 두 값 저장
   - `context_length`
   - `max_output_tokens`

2. 모델 한도 로더 추가
   - `src/utils/model_limits.py` 신규
   - 모델별 `context_length`, `max_output_tokens` 조회
   - provider alias 포함 조회

3. 요청 payload 구성 개선
   - 표준 provider 경로에 `max_tokens` 실제 전달
   - 요청에 `max_tokens`가 없으면 모델 기본 출력 한도 사용 여부를 명확히 결정

4. 요청 검증 로직 재작성
   - 정밀 토큰 추정 기반 차단은 제거
   - 아래만 검증
     - `max_tokens`가 1 이상 정수인지
     - `max_tokens`가 모델의 `max_output_tokens`를 넘지 않는지
   - `context`는 로컬 추정 차단 대신 업스트림 오류 정규화에 맡김

5. 업스트림 오류 정규화 추가
   - `prompt too long`
   - `context window exceeds limit`
   - `context_length_exceeded`
   - `maximum context length`
   - `input token count exceeds`
   - 위 패턴을 `context_length_exceeded` 계열로 통합

6. 재시도 정책 개선
   - context overflow 계열 `400`은 재시도하지 않음
   - 모든 키를 돌며 같은 잘못된 요청을 반복하지 않음

---

## 5. 결론

현재 프로젝트는:

- 모델별 `context` 정보는 저장하고 있습니다.
- 모델별 `max token` 정보는 저장하지 않습니다.
- 기존 로직은 요청 전체를 반영하지 못하고, `ollama-cloud` 경로와도 일치하지 않습니다.

따라서 교체 구현은 아래 원칙을 따라야 합니다.

1. 부정확한 토큰 추정 기반 조기 차단 제거
2. 모델 메타데이터에 `context`와 `output` 한도 분리 저장
3. 실제 요청에 `max_tokens` 전달
4. overflow 오류를 provider 독립적으로 정규화
5. overflow 오류는 재시도하지 않음

