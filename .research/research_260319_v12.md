# Antigravity 경로 호출 실패 분석

작성일: 2026-03-19
대상: `ollama-proxy`가 `../antigravity-proxy` 모델 호출 시 지연되거나 실패하는 문제

## 조사 범위

- `ollama-proxy`
  - `models.json`
  - `src/handlers/chat.py`
  - `src/providers/base.py`
  - `src/routes/openai.py`
  - `src/routes/ollama.py`
  - `config.py`
- `antigravity-proxy`
  - `app.py`
  - `client.py`
  - `docker-compose.yml`
- 실행 로그
  - `docker logs ollama-proxy`
  - `docker logs antigravity-proxy`

## 현재 호출 흐름

1. `ollama-proxy`는 `src/handlers/chat.py`에서 `antigravity:<model>` 접두사를 감지하면 prefix를 제거한 뒤 `ANTIGRAVITY_PROXY_URL + /chat/completions`로 전달합니다.
2. 인증은 `src/providers/base.py`의 공통 `BaseApiClient.post_request()`가 `Authorization: Bearer <key>` 형태로 추가합니다.
3. `antigravity-proxy`는 `app.py`에서 `model in AVAILABLE_MODELS`를 검사한 뒤 `client.chat()`으로 넘깁니다.
4. `antigravity-proxy/client.py`는 자체적으로 계정 순환, 429 처리, capacity backoff, 총 120초 예산 기반 재시도를 수행합니다.

## 확인된 사실

### 1. `ollama-proxy`가 노출하는 antigravity 모델 목록과 실제 upstream 지원 목록이 다릅니다

`ollama-proxy/models.json`에는 다음 plain antigravity 모델이 포함되어 있습니다.

- `antigravity:claude-opus-4-6-thinking`
- `antigravity:claude-sonnet-4-6`
- `antigravity:gemini-3-flash`
- `antigravity:gemini-3.1-pro-high`
- `antigravity:gemini-3.1-pro-low`

하지만 `antigravity-proxy/client.py`의 `PUBLIC_MODEL_CONFIG`에는 위 plain 이름이 없고, 실제 공개 모델은 아래처럼 `anti-*` 또는 `gcli-*`입니다.

- `anti-claude-opus-4-6-thinking`
- `anti-claude-sonnet-4-6`
- `anti-gemini-3-flash`
- `anti-gemini-3.1-pro-high`
- `anti-gemini-3.1-pro-low`
- `gcli-gemini-3-flash-preview`
- `gcli-gemini-3-pro-preview`
- `gcli-gemini-3.1-pro-preview`

즉, `ollama-proxy`는 upstream이 이해하지 못하는 ID를 그대로 광고하고 있습니다.

### 2. 이 모델 불일치는 실제 400 에러로 재현됩니다

`ollama-proxy` 로그에서 다음 에러가 반복 확인됐습니다.

- `Unknown model: claude-sonnet-4-6`
- 응답 본문에는 `Available: ['anti-claude-opus-4-6-thinking', 'anti-claude-sonnet-4-6', ...]`가 포함됨

의미:

- 사용자가 `ollama-proxy`가 노출한 `antigravity:claude-sonnet-4-6`을 선택해도
- `ollama-proxy`는 prefix만 제거해서 `claude-sonnet-4-6`으로 upstream에 전달하고
- `antigravity-proxy`는 이를 미지원 모델로 400 처리합니다.

따라서 모델 카탈로그와 라우팅 규칙이 서로 어긋나 있습니다.

### 3. 지원되는 antigravity 모델도 `ollama-proxy`에서 체감상 멈춘 것처럼 보일 수 있습니다

`antigravity-proxy/client.py`는 이미 자체 재시도 로직을 갖고 있습니다.

- `REQUEST_TIMEOUT = (50, 300)`
- `MAX_RETRIES = 5`
- `CAPACITY_TOTAL_BUDGET_SECONDS = 120`

특히 `MODEL_CAPACITY_EXHAUSTED` 계열은 내부에서 여러 계정을 돌며 오래 버틴 뒤, 최종적으로 503을 반환합니다.

실제 로그:

- `antigravity-proxy`가 `gcli-gemini-3-pro-preview` 요청에 대해 `capacity 예산 초과(120s) | ... -> 503 반환`
- 직후 `ollama-proxy`는 그 503을 받아 `503 Server Error`로 취급
- 이후 같은 요청을 다시 재시도해서 나중에 200을 받음

### 4. `ollama-proxy`가 upstream 프록시의 구조화된 에러를 다시 재시도합니다

`src/providers/base.py`의 `BaseApiClient.post_request()`는 다음 동작을 합니다.

- 503을 서버 오류로 기록
- `resp.raise_for_status()` 예외 발생
- `except requests.exceptions.RequestException`에서 sleep 후 재시도
- 최대 10회 반복

문제는 `antigravity-proxy`가 이미 "충분히" 재시도한 뒤 구조화된 OpenAI 형식 에러를 내려준다는 점입니다.

즉, 현재 구조는 아래처럼 중복 재시도됩니다.

1. `antigravity-proxy` 내부 재시도
2. `ollama-proxy` 외부 재시도

이 중복 때문에 호출자가 보기에는:

- 응답이 지나치게 늦게 오거나
- 클라이언트 타임아웃보다 늦게 응답이 와서 실패처럼 보이거나
- 실제 upstream 503 원인이 사용자에게 즉시 전달되지 않습니다.

### 5. 인증 주석도 현재 구현과 어긋나 있습니다

`ollama-proxy/config.py`에는 다음 주석이 있습니다.

- `Antigravity는 별도 프록시 컨테이너 (인증 불필요, dummy 키 사용)`

하지만 `antigravity-proxy/app.py`와 `docker-compose.yml`은 `API_TOKEN` 기반 인증을 명시적으로 지원합니다.

이번 장애의 직접 원인은 아니지만, 설정을 잘못 이해하게 만드는 오래된 설명입니다.

## 근본 원인 정리

근본 원인은 두 가지입니다.

1. 모델 식별자 드리프트
   - `ollama-proxy`가 upstream에 없는 antigravity 모델 ID를 노출하고 있습니다.
   - 일부 요청은 처음부터 400으로 실패합니다.

2. 프록시 위에 또 프록시를 얹은 상태에서의 재시도 정책 충돌
   - `antigravity-proxy`는 이미 재시도, 계정 순환, capacity backoff를 수행합니다.
   - `ollama-proxy`가 이를 다시 재시도하면서 지연과 체감 실패를 키우고 있습니다.

## 수정 방향

### 우선순위 1. 모델명 정합성 복구

다음 둘 중 하나가 필요합니다.

- `ollama-proxy`에서 antigravity alias를 upstream 실제 모델명으로 정규화
- 또는 `models.json`에서 upstream 미지원 plain antigravity 모델을 제거

호환성을 생각하면 alias 정규화가 더 안전합니다.

예상 매핑:

- `claude-opus-4-6-thinking` -> `anti-claude-opus-4-6-thinking`
- `claude-sonnet-4-6` -> `anti-claude-sonnet-4-6`
- `gemini-3-flash` -> `anti-gemini-3-flash`
- `gemini-3.1-pro-high` -> `anti-gemini-3.1-pro-high`
- `gemini-3.1-pro-low` -> `anti-gemini-3.1-pro-low`

### 우선순위 2. antigravity upstream 에러 즉시 전달

`antigravity-proxy`가 내려준 구조화된 400/429/503은 `ollama-proxy`가 다시 재시도하지 말고 즉시 전달해야 합니다.

특히 아래 케이스는 passthrough 대상입니다.

- `400 Unknown model`
- `429` upstream rate limit
- `503 model_capacity_exhausted`

이 수정이 들어가면 호출자는 "멈춤" 대신 실제 원인을 바로 받게 됩니다.

### 우선순위 3. 문서와 설정 설명 정리

- `config.py`의 antigravity 관련 주석 수정
- 필요하면 README나 운영 설정에 "antigravity는 자체 재시도 프록시"라는 점을 명시

## 결론

이번 문제는 `antigravity-proxy` 자체가 동작하지 않는 문제가 아니라, `ollama-proxy`가 그 upstream 특성을 잘못 가정하고 있다는 문제입니다.

- 모델 목록은 upstream과 불일치합니다.
- 에러 처리도 upstream 프록시 특성에 맞지 않게 다시 재시도합니다.

따라서 수정은 `ollama-proxy` 쪽에서 해야 합니다.
