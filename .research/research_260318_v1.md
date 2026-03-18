# Ollama Proxy 조사 보고서 (2026-03-18)

## 조사 목적
- Claude Code 사용 중 응답이 중간에 끊기는 현상이 `tool` 자체 문제인지, 또는 `ollama-proxy`의 스트리밍/토큰 회전 문제인지 확인합니다.
- `ollama-proxy` 컨테이너 로그와 Anthropic 호환 스트리밍 코드 경로를 함께 점검합니다.

## 확인한 범위
- 컨테이너: `ollama-proxy`
- 로그 범위: 최근 24시간
- 코드 범위:
  - `src/routes/anthropic.py`
  - `src/handlers/anthropic.py`
  - `src/handlers/chat.py`
  - `src/providers/base.py`
  - `src/providers/standard.py`
  - `src/auth/key_rotator.py`
  - `src/handlers/response.py`

## 로그 관찰 결과

### 1. Tool 포함 요청은 프록시까지 정상 도달함
- Anthropic 호환 엔드포인트 로그에 `stream=True tools=30` 요청이 반복적으로 기록됩니다.
- 최근 24시간 기준 `tools=30` 요청 로그는 65건 확인되었습니다.
- `tools=1` 요청도 일부 보이지만, `tools=30` 요청이 대부분입니다.
- 따라서 "tool 목록이 있는 요청 자체가 프록시에 도달하지 못한다"는 증거는 없습니다.

### 2. 직접적으로 보이는 실패는 tool 에러가 아니라 upstream 401임
- `https://ollama.com/v1/chat/completions` 호출에서 `401 Unauthorized`가 5회 발생했습니다.
- 확인된 시각:
  - 2026-03-18 03:17:08
  - 2026-03-18 03:24:18
  - 2026-03-18 04:38:33
  - 2026-03-18 04:42:56
  - 2026-03-18 04:48:30
- 각 401 직후 다음 시도에서 다시 `200`이 기록됩니다.
- 즉, 프록시가 완전히 죽는 상황이 아니라 "일부 키가 실패한 뒤 다음 시도로 회복"되는 패턴입니다.

### 3. 401은 랜덤하게 여러 키에서 터지는 형태가 아니라, 소수의 특정 키에 집중됨
- 로그에 남은 마스킹 키는 아래 2개뿐입니다.
  - `eed67a..._sDk`
  - `1219d1...Wyy9`
- 최근 24시간의 모든 `OllamaCloud` 401 로그는 위 두 키에만 해당합니다.
- 분포:
  - `eed67a..._sDk`: 3회
  - `1219d1...Wyy9`: 2회
- 따라서 현재 증상은 "완전 무작위 실패"보다 "키 풀 중 일부 특정 토큰이 불량/만료/권한 문제"일 가능성이 높습니다.

### 4. tool 개수와 401의 직접 상관은 로그만으로 입증되지 않음
- 401이 발생한 요청도 모두 `tools=30`이긴 하지만, 정상 `200`인 요청도 대부분 `tools=30`입니다.
- 즉, "tools=30 이면 실패"라는 규칙성은 없습니다.
- 현재 로그만으로는 `tool` 때문이 아니라, `tool`을 포함한 일반 Anthropic 스트리밍 요청들 중 일부가 특정 키를 밟을 때 실패한다고 보는 편이 더 타당합니다.

## 코드 분석 결과

### 1. Anthropic 요청은 OpenAI 호환 `/chat/completions`로 전달됨
- `src/routes/anthropic.py`에서 `/v1/messages` 요청을 받습니다.
- `AnthropicHandler.build_proxy_request()`가 Anthropic 형식을 OpenAI 호환 형식으로 변환합니다.
- 이후 `ChatHandler.handle_chat_request()`가 provider prefix를 보고 `ollama-cloud`로 라우팅합니다.
- 최종 upstream endpoint는 `https://ollama.com/v1/chat/completions`입니다.

### 2. `tool`은 그대로 OpenAI 함수 호출 형식으로 변환되어 전달됨
- `src/handlers/anthropic.py`의 `_normalize_tools()`가 Anthropic tool 정의를 OpenAI `function` 형식으로 바꿉니다.
- `tool_choice`도 `_normalize_tool_choice()`에서 OpenAI 호환 포맷으로 변환됩니다.
- 이 변환 코드 자체에서 예외를 내거나 tool 개수를 제한하는 로직은 보이지 않습니다.

### 3. 401 발생 시 재시도는 "같은 키 재시도"가 아니라 "다음 키 회전"으로 처리됨
- `src/providers/base.py`의 `post_request()`는 요청마다 `_get_api_key()`를 다시 호출합니다.
- `StandardApiClient._get_api_key()`는 `KeyRotator.get_next_key()`를 사용합니다.
- `StandardApiClient._on_auth_failure()`는 항상 `False`를 반환하므로, 401 발생 시 별도 토큰 복구는 하지 않습니다.
- 대신 예외 처리 루프로 들어가고, 다음 반복에서 `get_next_key()`가 다음 키를 선택합니다.
- 즉, 현재 구조는 "401이 뜬 키는 그 요청에서 실패하고, 다음 키로 다음 재시도" 방식입니다.

### 4. 키 선택은 기본적으로 라운드로빈이며, 현 증상은 랜덤 선택 부작용이 아님
- `KeyRotator.get_next_key()`는 `quota_fraction`이 없는 경우 `(current_index + 1) % len(api_keys)`로 순차 회전합니다.
- `ollama-cloud` 경로는 `quota_fraction`을 넘기지 않으므로 쿼터-aware 랜덤 선택이 적용되지 않습니다.
- 따라서 현재 401은 "랜덤 선택이라 특정 키가 우연히 많이 걸린다"기보다, 순차 회전 중 문제 있는 키를 만날 때마다 재현되는 구조입니다.

### 5. Anthropic 스트리밍 경로는 중간 예외 로깅이 약함
- `src/routes/anthropic.py`는 스트리밍일 때 `AnthropicHandler.stream_anthropic_response()`를 직접 사용합니다.
- 이 함수는 `resp.iter_lines()`를 직접 순회하지만, `except` 로깅이 없습니다.
- 반면 `src/handlers/response.py`의 일반 스트리밍 핸들러는 timeout/connection 예외를 자세히 로그로 남깁니다.
- 따라서 upstream 스트림이 중간에 끊기면, Anthropic 경로에서는 로그가 거의 남지 않은 채 사용자가 "답변이 끊긴다"고 체감할 수 있습니다.

## 현재 판단
- 1차 결론: 현재 보이는 명시적 실패는 `tool` 자체보다는 `OllamaCloud`의 일부 토큰에서 발생하는 `401 Unauthorized`입니다.
- 2차 결론: 실패는 무작위 전체 분산이 아니라, 로그상 2개의 특정 마스킹 토큰에 집중됩니다.
- 3차 결론: 응답 끊김 체감에는 Anthropic 스트리밍 경로의 예외 로깅 부재도 영향을 줍니다. 실제 upstream 스트림 단절이 있어도 지금 로그만으로는 거의 보이지 않습니다.

## 권장 다음 단계
1. 문제 키 2개를 키 풀에서 잠시 제외하고 동일 사용 패턴에서 끊김이 사라지는지 확인합니다.
2. `src/handlers/anthropic.py`에 스트리밍 시작/첫 청크/종료/예외 로그를 추가해, "401 전 실패"와 "스트림 중간 단절"을 구분 가능하게 만듭니다.
3. 필요하면 401 발생 키를 `mark_key_failure()`로 기록해 일정 시간 제외하는 방식을 넣습니다.
