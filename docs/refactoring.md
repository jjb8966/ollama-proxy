# ollama-proxy 리팩토링 분석 보고서

총 ~5,500줄 / 27개 Python 파일에 대한 clean-code 기준 분석 결과.

---

## P0: 즉시 개선 필요

### 1. ollama.py 라우트에 비즈니스 로직 과다 집중

**파일**: `src/routes/ollama.py:85-348`

`chat()` 함수가 스트리밍 변환 로직 260줄을 직접 포함. `ResponseHandler`에 이미 `handle_streaming_response()`가 존재함에도, Google 스트리밍 처리만 라우트 내부에 `google_stream_to_ollama()`로 중복 구현.

구체적 문제:
- 라인 126: `import datetime`이 함수 중간에 위치
- 라인 142-164: `normalize_tool_arguments()`가 `ResponseHandler._normalize_tool_calls()`와 동일 로직
- 라인 141-344: `google_stream_to_ollama()` 내부에 `__import__("time")`, `__import__("datetime")` 사용
- `<thought>` 태그 필터링이 `ResponseHandler._filter_thought_tags()`와 중복

**개선 방향**: `google_stream_to_ollama()` 로직을 `ResponseHandler` 또는 `GoogleApiClient`로 이동. 라우트는 핸들러 호출만 담당.

---

### 2. 스키마 정규화 중복 (Google ↔ Anthropic)

**파일-1**: `src/providers/google.py:78-145` — `GoogleApiClient._sanitize_schema_for_google()`
**파일-2**: `src/handlers/anthropic.py:338-381` — `AnthropicHandler._sanitize_tool_input_schema()`

두 메서드가 거의 동일한 스키마 정규화 로직을 수행:
- 허용 키 필터링
- `properties`, `items`, `anyOf/oneOf/allOf` 재귀 정규화
- 빈 스키마에 기본값 삽입

차이점은 허용 키 목록뿇임 (`_GOOGLE_ALLOWED` vs `_ANTHROPIC_ALLOWED`).

**개선 방향**: `src/utils/schema_sanitizer.py`에 공통 함수를 만들고, 허용 키 목록을 파라미터로 받도록 통합.

---

### 3. 텍스트 추출 / 도구 인자 파싱 중복 (3곳)

#### 3a. `_extract_text_from_content_value` 중복

**파일-1**: `src/handlers/anthropic.py:59-81`
**파일-2**: `src/handlers/response.py:96-127`

두 메서드가 거의 동일한 로직을 수행. 검색 키가 다름:
- `anthropic.py`: `("text", "value", "content")`
- `response.py`: `("content", "text", "value", "reasoning_content", "reasoning")`

#### 3b. `_parse_tool_arguments` 중복

**파일-1**: `src/handlers/response.py:41-61` — `ResponseHandler._parse_tool_arguments()`
**파일-2**: `src/routes/ollama.py:146-162` — `google_stream_to_ollama()` 내부 `normalize_tool_arguments()`

동일한 로직: JSON 문자열 파싱 → dict이면 그대로 반환 → 실패하면 `{"input": ...}` 래핑.

#### 3c. `_filter_thought_tags` 중복

**파일-1**: `src/handlers/response.py:276-306` — `ResponseHandler._filter_thought_tags()` (인스턴스 메서드)
**파일-2**: `src/routes/ollama.py:228-245` — `google_stream_to_ollama()` 내부 루프 (인라인 구현)

두 곳에서 `<thought>` 태그 필터링을 수행하지만 구현이 다름:
- `response.py`: `_in_thought_tag` 인스턴스 변수로 across 청크 상태 유지
- `ollama.py`: `in_thought` 지역 변수 사용

**개선 방향**:
- 텍스트 추출 → `src/utils/text_extraction.py`
- 도구 인자 파싱 → `src/utils/tool_args.py`
- thought 태그 필터 → 상태 기반 유틸리티 클래스로 추출

---

## P1: 구조 개선 권장

### 4. GoogleApiClient가 BaseApiClient를 상속하지 않음

**파일**: `src/providers/google.py:63`

`GoogleApiClient`는 `BaseApiClient`를 상속하지 않고 완전히 독립적으로 구현됨. 결과로:
- `base.py:95-216`의 재시도, 에러 처리, 로깅 로직이 `GoogleApiClient._make_request()`에 별도 재구현됨 (라인 502-542)
- `_on_auth_failure`, `_mark_key_failure` 등 훅 메서드가 Google에서 호출되지 않음
- `_build_upstream_proxy_error` 로직이 Google에 적용되지 않음

**개선 방향**: Google SDK 특성(다른 URL, 다른 응답 포맷)은 유지하되, 재시도/에러 처리 공통 로직은 `BaseApiClient`의 메서드로 위임하거나 믹스인으로 분리.

---

### 5. ChatHandler 하드코딩된 클라이언트 생성

**파일**: `src/handlers/chat.py:107-126`

```python
def __init__(self, api_config):
    self.google_client = GoogleApiClient(api_config.google_rotator)
    self.openrouter_client = StandardApiClient(api_config.openrouter_rotator)
    self.akash_client = StandardApiClient(api_config.akash_rotator)
    # ... 12개 클라이언트를 수동으로 생성
```

새 제공업체 추가 시 `PROVIDER_CONFIG` 딕셔너리와 `__init__` 두 곳을 모두 수정해야 함.

**개선 방향**: `PROVIDER_CONFIG`에 클라이언트 타입을 명시하고, `__init__`에서 순회하며 자동 생성:

```python
PROVIDER_CONFIG = {
    'google': {'client_type': 'google', 'rotator_attr': 'google_rotator', ...},
    'openrouter': {'client_type': 'standard', 'rotator_attr': 'openrouter_rotator', ...},
    ...
}
```

---

### 6. anthropic.py 과도한 길이 (1188줄)

**파일**: `src/handlers/anthropic.py`

단일 클래스가 1188줄로 책임이 과도하게 집중:
- 요청 정규화 (messages, tools, schema)
- 응답 변환 (streaming, non-streaming)
- Anthropic ↔ OpenAI 포맷 변환
- thought 태그 처리
- 시스템 프롬프트 처리

**개선 방향**: 역할별로 분리:
- `AnthropicRequestNormalizer`: 요청 변환 담당
- `AnthropicResponseConverter`: 응답 변환 담당
- `AnthropicHandler`: 오케스트레이션만 담당

---

### 7. 정적 상수와 클래스 레벨 데이터 과다

**파일**: `src/handlers/chat.py:39-105`

- `PROVIDER_CONFIG`: 런타임 구성(환경변수 포함)이 클래스 레벨에 하드코딩
- `REMOVED_ANTIGRAVITY_MODELS`: 외부 설정이나 DB에서 관리하는 것이 더 적절
- `COMPACTION_REQUIRED_MESSAGE`: 한국어 하드코딩 문자열

**개선 방향**: `PROVIDER_CONFIG`는 설정 파일이나 팩토리로 분리. `REMOVED_ANTIGRAVITY_MODELS`는 `models.json`이나 별도 설정으로 이동.

---

## P2: 개선 권장

### 8. KeyRotator 더미 쿼터 구현 방치

**파일**: `src/auth/key_rotator.py:284-299`

```python
def _estimate_key_quota(self, key_index: int, min_tier: int) -> float:
    # 더미 구현: 인덱스마다 다른 쿼터량 시뮬레이션
    base = 0.9 - (key_index * 0.15)
    return max(0.0, base)
```

`_select_quota_aware_index`에서 실제로 호출되어 키 선택에 영향을 주지만, 반환값이 의미 없는 더미. `QuotaService`도 완전한 더미 구현.

- `_estimate_key_quota`의 `base = 0.9 - (key_index * 0.15)`는 인덱스가 큰 키일수록 낮은 쿼터를 반환해 의도치 않은 편향 유발

**개선 방향**: 더미 구현을 제거하거나, `QuotaService` 연동 전까지 쿼터-aware 선택 경로를 비활성화하고 라운드 로빈만 사용.

---

### 9. ApiConfig 반복적인 초기화 패턴

**파일**: `config.py:27-71`

12개의 `KeyRotator` 생성이 동일한 패턴으로 반복:

```python
self.google_rotator = KeyRotator("Google", "GOOGLE_API_KEYS")
self.google_rotator.log_key_count()
self.openrouter_rotator = KeyRotator("OpenRouter", "OPENROUTER_API_KEYS")
self.openrouter_rotator.log_key_count()
# ... 12회 반복
```

**개선 방향**: 딕셔너리 기반 설정으로 정의하고 루프로 초기화.

---

## P3: 사소한 개선

### 10. `print()` 호출 잔존

**파일**: `src/providers/base.py:255`

```python
logging.error(...)
print(error_msg)  # 콘솔 출력 유지
```

프로덕션 코드에서 `print()`는 로깅 프레임워크로 대체 필요.

---

### 11. `_build_contents` 수동 인덱스 루프

**파일**: `src/providers/google.py:218-311`

`while i < len(messages)` + `i += 1` 수동 인덱스 루프 사용. `tool` 메시지 병합 의도는 이해되나 가독성 저하.

**개선 방향**: `itertools.groupby`나 명시적 반복자로 가독성 개선.

---

### 12. `server.log` Git 노출 위험

**파일**: 프로젝트 루트 `/server.log`

`.gitignore`에 `server.log` 포함 여부 확인 필요.

---

## 요약: 우선순위별 리팩토링 항목

| 우선순위 | 항목 | 규칙 위반 | 파일 |
|---------|------|-----------|------|
| **P0** | ollama.py 비즈니스 로직 분리 | 책임 분리 위반, 중복 | `src/routes/ollama.py` |
| **P0** | 스키마 정규화 공통화 | 중복 | `google.py`, `anthropic.py` |
| **P0** | 텍스트 추출/도구 인자 파싱 공통화 | 중복 (3곳) | `response.py`, `anthropic.py`, `ollama.py` |
| **P1** | GoogleApiClient 공통 로직 재사용 | 중복, 추상화 부족 | `src/providers/google.py` |
| **P1** | ChatHandler 클라이언트 자동 생성 | 변경 범위 절제 | `src/handlers/chat.py` |
| **P1** | anthropic.py 책임 분리 | 함수/클래스 과도 길이 | `src/handlers/anthropic.py` |
| **P2** | 더미 쿼터 구현 정리 | 의미 없는 코드 | `src/auth/key_rotator.py` |
| **P2** | PROVIDER_CONFIG 외부 설정화 | 설정 하드코딩 | `src/handlers/chat.py` |
| **P3** | print() 제거 | 이름/구조 개선 | `src/providers/base.py` |
| **P3** | 반복 초기화 패턴 정리 | 중복 | `config.py` |