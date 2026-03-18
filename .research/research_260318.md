# 연구 보고서: ollama-proxy 기능 개선

**작성일:** 2026-03-18
**모티브 프로젝트:** antigravity-proxy

---

## 1. 개요

ollama-proxy 프로젝트에 추가하고자 하는 세 가지 기능에 대한 조사 보고서입니다:

1. Context length 및 max token 체크 로직
2. 쿼터(Quota) 조회 기능
3. 계정 선택 로직

---

## 2. 현재 상태 분석

### 2.1 ollama-proxy 프로젝트 구조

```
ollama-proxy/
├── config.py                          # API 설정 (KeyRotator 초기화)
├── models.json                        # 모델 목록
├── src/
│   ├── auth/
│   │   ├── key_rotator.py            # API 키 순환 관리
│   │   └── qwen_oauth.py             # Qwen OAuth 관리
│   ├── providers/
│   │   ├── base.py                   # 기본 API 클라이언트
│   │   ├── standard.py               # 표준 클라이언트 (KeyRotator 사용)
│   │   ├── google.py                 # Google 클라이언트
│   │   └── qwen.py                   # Qwen 클라이언트
│   ├── handlers/
│   │   ├── chat.py                   # 채팅 요청 핸들러 (라우팅)
│   │   └── anthropic.py              # Anthropic 핸들러
│   └── routes/
│       ├── openai.py                 # OpenAI 호환 라우트
│       ├── ollama.py                 # Ollama 라우트
│       └── anthropic.py              # Anthropic 라우트
```

### 2.2 현재 API 키 관리 방식

`config.py`에서 `KeyRotator`를 사용하여 각 제공업체별 API 키를 관리합니다:

- `google_rotator` - GOOGLE_API_KEYS
- `openrouter_rotator` - OPENROUTER_API_KEYS
- `akash_rotator` - AKASH_API_KEYS
- `cohere_rotator` - COHERE_API_KEYS
- `codestral_rotator` - CODESTRAL_API_KEYS
- `qwen_oauth_manager` - QwenOAuthManager (OAuth 방식)
- `antigravity_rotator` - ANTIGRAVITY_API_KEYS
- `nvidia_nim_rotator` - NVIDIA_NIM_API_KEYS
- `cli_proxy_api_rotator` - CLI_PROXY_API_KEYS
- `ollama_cloud_rotator` - OLLAMA_API_KEYS

현재는 단순 Round-robin 방식으로 API 키를 순환합니다.

---

## 3. 기능별 상세 분석

### 3.1 Context Length 및 Max Token 체크 로직

#### antigravity-proxy 구현

**위치:** `client.py`, 메서드 `_check_context_limit`

```python
# 모델별 최대 컨텍스트 윈도우 (토큰 단위)
MODEL_MAX_CONTEXT = {
    public_model: config["context"]
    for public_model, config in PUBLIC_MODEL_CONFIG.items()
}

# PUBLIC_MODEL_CONFIG 예시
PUBLIC_MODEL_CONFIG = {
    "anti-claude-opus-4-6-thinking": {
        "backend": "claude-opus-4-6-thinking",
        "context": 200_000,
    },
    "anti-gemini-3.1-pro-high": {
        "backend": "gemini-3.1-pro-high",
        "context": 1_000_000,
    },
    # ...
}
```

**동작 방식:**

1. 요청이 들어오면 `MODEL_MAX_CONTEXT`에서 모델의 최대 컨텍스트 조회
2. `_estimate_messages_tokens()`로 메시지 토큰 수 추정
3. 90% 임계값 초과 시 Early Return으로 에러 반환
4. 초과 시 OpenAI 호환 형식의 에러 응답 반환

#### ollama-proxy에 필요한 것

- 각 모델별 최대 context 길이 정의 (models.json 또는 별도 config)
- 토큰 추정 유틸리티 함수
- 핸들러 레벨에서 사전 검증 로직 추가
- max_tokens가 context를 초과하는지 검증

### 3.2 쿼터 조회 기능

#### antigravity-proxy 구현

**위치:** `client.py`, 메서드 `_fetch_antigravity_quota`, `_fetch_gemini_cli_quota`

**주요 상수:**

```python
_QUOTA_ANTIGRAVITY_URL = "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels"
_QUOTA_GEMINI_CLI_URL = "https://cloudcode-pa.googleapis.com/v1internal:retrieveUserQuota"
_QUOTA_TIMEOUT = 10
CLI_QUOTA_CACHE_TTL = 300
```

**주요 메서드:**

- `_fetch_antigravity_quota()` - Antigravity 계정의 쿼터 조회
- `_fetch_gemini_cli_quota()` - Gemini CLI 계정의 쿼터 조회
- `_aggregate_by_group()` - 모델군별 쿼터 집계
- `_classify_model_group()` - 모델을 claude/gemini-pro/gemini-flash로 분류

**응답 형식:**
```json
{
  "claude": {
    "remainingFraction": 0.85,
    "resetTime": "2026-03-18T12:00:00Z",
    "modelCount": 3
  },
  "gemini-pro": {
    "remainingFraction": 0.42,
    "resetTime": "2026-03-18T12:00:00Z",
    "modelCount": 5
  },
  "gemini-flash": {
    "remainingFraction": 0.70,
    "resetTime": "2026-03-18T12:00:00Z",
    "modelCount": 2
  }
}
```

#### parse_quota.py (출력 포맷)

```python
def get_emoji(fraction):
    if fraction >= 0.7: return f"🟢 {int(fraction*100)}%"
    elif fraction >= 0.3: return f"🟡 {int(fraction*100)}%"
    else: return f"🔴 {int(fraction*100)}%"

def time_until_reset(reset_str):
    # 리셋 시간까지 남은 시간 계산
    # 예: "(resets in 2h 30m)"
```

#### ollama-proxy에 필요한 것

- Antigravity 프록시가 제공하는 쿼터 조회 API 연동
- 각 제공업체별 쿼터 상태 추적 (메모리 또는 파일)
- CLI 명령 또는 API 엔드포인트로 쿼터 조회 기능 제공
- 캐싱 로직 (TTL: 300초)

#### ⚠️ 중요: antigravity-proxy에 쿼터 조회 API 없음

현재 antigravity-proxy는 내부적으로 `_fetch_antigravity_quota()` 메서드로 쿼터를 조회하지만, **외부에 API로 노출하지 않음**.

**필요 작업:**
1. antigravity-proxy에 `GET /v1/quota` 또는 `GET /v1/accounts` API 추가
2. ollama-proxy에서 해당 API 호출하여 쿼터 정보 획득

### 3.3 계정 선택 로직

#### antigravity-proxy 구현

**위치:** `auth.py`, 메서드 `get_next_account`, `_select_by_tier`

**핵심 상수:**

```python
TIER_THRESHOLDS = [0.70, 0.40, 0.10]
# 70% 이상 -> 40% 이상 -> 10% 이상 순서로 계정 사용
```

**동작 방식:**

1. **1차 필터링:** 사용 가능한 계정 수집 (hard exclude 적용)
   - Rate limit 상태
   - 토큰 만료
   - 쿼터 소진 (5% 이하)

2. **2차 선택:** 티어 기반 순환
   - T1 (70% 이상): 쿼터充裕한 계정 우선
   - T2 (40% 이상): T1 계정이 바닥날 때 사용
   - T3 (10% 이상): T2 계정이 바닥날 때 사용

3. **3차 폴백:** 모든 계정이 제외된 경우
   - 가장 빨리 복귀 가능한 계정 대기 후 재시도 (최대 5초)

**상태 추적:**
- `_rate_limit_until`: rate limit 해제 시각
- `_last_selected`: 마지막 선택 시각
- `_selection_counts`: 선택 횟수 (점수 계산에 사용)
- `_health`: 계정별 건강도 점수

**점수 계산 (`_compute_selection_score`):**
```python
score = (
    quota_score * 1.0 +           # 쿼터 잔량 (가중치 1.0)
    recency_score * 0.5 +          # 최근 선택 여부 (가중치 0.5)
    health_score * 0.3             # 건강도 (가중치 0.3)
)
```

#### ollama-proxy에所需的

현재 ollama-proxy는 단순 Round-robin 방식입니다. 이를 개선하려면:

1. **API 키별 상태 추적:** 사용 횟수, 실패 횟수, 최근 사용 시각
2. **쿼터-awareness:** 쿼터 상태를 기반으로 키 선택
3. **폴백 로직:** 실패 시 다음 키로 자동 전환
4. **점수 기반 선택:** 가중치 기반 최적 키 선택

---

## 4. 구현 고려사항

### 4.1 Context Length 체크

| 구분 | antigravity-proxy | ollama-proxy |
|------|-------------------|--------------|
| 모델 정의 | `PUBLIC_MODEL_CONFIG` (client.py) | `models.json` |
| 검증 시점 | API 호출 전 (`_check_context_limit`) | 핸들러에서 사전 검증 권장 |
| 토큰 추정 | `_estimate_messages_tokens` | tiktoken 또는 유사 라이브러리 사용 권장 |

**권장 구현:**
- `models.json`에 `context_length` 필드 추가
- 공통 유틸리티 모듈 생성 (`src/utils/tokenizer.py`)
- 핸들러에서.chat() 메서드 호출 전 검증

### 4.2 쿼터 조회

| 구분 | antigravity-proxy | ollama-proxy |
|------|-------------------|--------------|
| 데이터 소스 | Google API 직접 호출 | Antigravity 프록시 API |
| 캐시 | 메모리 (TTL: 300초) | 동일 방식 적용 |
| 출력 | CLI (`parse_quota.py`) | CLI + API 엔드포인트 |

**권장 구현:**
- Antigravity 프록시에 쿼터 조회 API 추가 필요 (현재 없는 것으로 보임)
- 대안: ollama-proxy에서 직접 Google APIs 호출하여 쿼터 조회
- 또는 AntigravityAccountManager를 ollama-proxy로 포팅

### 4.3 계정 선택 로직

| 구분 | antigravity-proxy | ollama-proxy |
|------|-------------------|--------------|
| 인증 방식 | OAuth (Google) | API Key |
| 상태 저장 | 메모리 (동적) | 현재 로드된 키 목록 |
| 스코프 | 전체 계정 관리 | 제공업체별 키 관리 |

**권장 구현:**
- `KeyRotator` 클래스를 확장하여 쿼터-aware 선택 로직 추가
- 또는 새로운 `AccountManager` 클래스 생성
- 점수 기반 알고리즘 적용

---

## 5. 응답 끊김 문제 원인 추적

### 5.1 현재 상태 분석

**ollama-proxy 스트리밍 처리 (`src/handlers/response.py`):**
- `handle_streaming_response()`에서 SSE 스트림 처리
- `finish_reason`이 "stop", "tool_calls", "length"일 때 종료
- 예외 발생 시 에러 청크 반환
- 로깅: 현재 최소한 (예외 발생 시에만 로그)

**antigravity-proxy 스트리밍 처리:**
- `REQUEST_TIMEOUT = (50, 300)` - 50초 연결, 300초 읽기 타임아웃
- `finish_raw == "MAX_TOKENS"` → `finish_reason = "length"`
- 429 Rate Limit, 5xx 에러에 대한 백오프 및 계정 전환 로직 존재

### 5.2 끊김 가능 원인

| 원인 | 증상 | 확인 포인트 |
|------|------|-------------|
| **Timeout** | 일정 시간 후 연결 종료 | 요청 지속 시간, timeout 설정 |
| **Rate Limit (429)** | "length" finish_reason | 응답 헤더, 재시도 로그 |
| **Max Tokens 도달** | "length" finish_reason | 요청 max_tokens, 응답 토큰 수 |
| **Connection Error** | 갑작스러운 연결 종료 | 네트워크, upstream 응답 |
| **Context 초과** | 에러 반환 또는 truncated | context length 검증 |
| **Upstream 에러** | 5xx, 4xx 응답 | HTTP 상태 코드 |

### 5.3 추가 필요 로그

#### 스트림 시작/종료
- 요청 시작 시: 모델명, 메시지 수, max_tokens
- 스트림 시작 시: 첫 청크 수신 시간
- 스트림 종료 시: `finish_reason`, 총 지속 시간

#### 청크 레벨
- 청크 수신 시간 및 크기 (샘플링)
- 마지막 5초간 수신 데이터 없음 경고

#### 예외/에러
- HTTP 상태 코드
- 응답 헤더 (X-RateLimit-*, Retry-After 등)
- 예외 타입 및 스택 트레이스

#### finish_reason 상세
- "stop": 정상 종료
- "length": max_tokens 도달 또는 context 초과
- "tool_calls": 툴 호출 완료

---

## 6. 결론 및 권장사항

### 우선순위

1. **최우선:** 응답 끊김 추적 로그 - 원인 파악 후 다른 기능 구현
2. **높음:** Context Length 체크 - 사용자 경험 향상 (불필요한 API 호출 방지)
3. **중간:** 계정 선택 로직 - 다중 키 환경에서 효율성 향상
4. **선행 필요:** antigravity-proxy 쿼터 조회 API 추가

### 선행 작업

**antigravity-proxy에 쿼터 조회 API 추가 필요:**
- 현재 내부 메서드 `_fetch_antigravity_quota()`만 존재
- 외부 노출 API 없음 (`/v1/quota` 필요)
- ollama-proxy 쿼터 기능 구현 전 선행 필요