# Ollama Proxy Server

여러 LLM 제공업체의 API를 **Ollama**, **OpenAI**, **Anthropic Messages** 세 가지 호환 형식으로 통합 제공하는 프록시 서버입니다.

## 지원 제공업체

| 제공업체 | Prefix | 인증 방식 | Base URL |
|----------|--------|-----------|----------|
| Google (Gemini) | `google:` | API Key + `x-goog-api-key` 헤더 | Gemini 네이티브 API |
| OpenRouter | `openrouter:` | API Key (Bearer) | `https://openrouter.ai/api/v1` |
| Akash | `akash:` | API Key (Bearer) | `https://chatapi.akash.network/api/v1` |
| Cohere | `cohere:` | API Key (Bearer) | `https://api.cohere.ai/compatibility/v1` |
| Codestral (Mistral) | `codestral:` | API Key (Bearer) | `https://codestral.mistral.ai/v1` |
| Qwen | `qwen:` | OAuth 2.0 (access/refresh token) | `https://portal.qwen.ai/v1` |
| Antigravity | `antigravity:` | 자체 프록시 토큰 | 내부 프록시 컨테이너 |
| Nvidia NIM | `nvidia-nim:` | API Key (Bearer) | `https://integrate.api.nvidia.com/v1` |
| CLI Proxy API | `cli-proxy-api:` | API Key (Bearer) | 로컬 CLI 프록시 |
| CLI Proxy API Plus | `cli-proxy-api-plus:` | API Key (Bearer) | 로컬 CLI 프록시 Plus |
| Cursor | `cursor:` | API Key (Bearer, 기본 `unused`) | `cursor-api-proxy` (`CURSOR_API_BASE_URL`) |
| Ollama Cloud | `ollama-cloud:` | API Key (Bearer) | `https://ollama.com/v1` |
| OpenCode Go | `opencode:` | API Key (Bearer) | `https://opencode.ai/zen/go/v1` |

전체 모델 목록은 `models.json` 파일 또는 `GET /api/tags` 엔드포인트에서 확인할 수 있습니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **3중 API 호환** | Ollama, OpenAI, Anthropic Messages API 형식을 동시 지원 |
| **API 키 자동 순환** | 파일 락 기반 멀티 프로세스 안전 키 순환 (Round-Robin + 쿼터-Aware) |
| **Rate Limit 핸들링** | 429 응답 감지 시 해당 키 일시 차단 및 자동 복구 |
| **키 건강도 모니터링** | 키별 사용 횟수, 실패율, 건강도 점수 추적 |
| **OAuth 토큰 관리** | Qwen access token 만료 시 refresh token으로 자동 갱신 |
| **컨텍스트 초과 감지** | 요청 토큰 추정 후 모델 컨텍스트 윈도우의 80% 초과 시 사전 차단 (Compaction 안내) |
| **Google Thinking 모드** | Gemini Thinking 모델의 `<thought>` 태그 실시간 필터링 |
| **스트리밍 지원** | SSE → NDJSON 변환, Google 네이티브 SSE → Ollama NDJSON 변환 |
| **이미지 처리** | Cline 확장 이미지 형식을 OpenAI Vision API 형식으로 자동 변환 |
| **쿼터 조회 API** | Antigravity 계정별 Claude/Gemini 잔여 쿼터 확인 |

## 엔드포인트

### Ollama 호환

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/` | 서버 루트 (버전 정보) |
| `GET` | `/api/version` | 버전 정보 |
| `GET` | `/api/tags` | 사용 가능한 모델 목록 |
| `POST` | `/api/chat` | 채팅 요청 (스트리밍/비스트리밍) |

### OpenAI 호환

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/v1/models` | 모델 목록 (OpenAI 형식) |
| `POST` | `/v1/chat/completions` | 채팅 완료 (OpenAI 형식) |

### Anthropic Messages 호환

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/v1/messages` | Anthropic Messages API |

### 관리 API

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `GET` | `/v1/keys/status` | 제공업체별 API 키 상태 (건강도, Rate Limit) |
| `GET` | `/v1/quota` | Antigravity 계정별 쿼터 정보 (캐시 TTL 300초) |
| `GET` | `/v1/quota/refresh` | 쿼터 정보 강제 새로고침 |

### 인증

모든 엔드포인트는 `PROXY_API_TOKEN` 환경 변수로 설정된 토큰을 요구합니다.

```
Authorization: Bearer <PROXY_API_TOKEN>
```

또는

```
x-api-key: <PROXY_API_TOKEN>
```

## 프로젝트 구조

```
ollama-proxy/
├── app.py                     # Flask 애플리케이션 팩토리 및 진입점
├── config.py                  # API 설정 (KeyRotator, OAuthManager 초기화)
├── models.json                # 지원 모델 목록 (컨텍스트 길이, 최대 출력 토큰 포함)
├── src/
│   ├── routes/                # API 라우트 (Blueprint)
│   │   ├── ollama.py          # Ollama 호환 엔드포인트 (/api/*)
│   │   ├── openai.py          # OpenAI 호환 엔드포인트 (/v1/*)
│   │   ├── anthropic.py       # Anthropic Messages 호환 엔드포인트
│   │   ├── quota.py           # 쿼터 조회 API
│   │   └── keys.py            # API 키 상태 조회 API
│   ├── handlers/              # 요청/응답 처리
│   │   ├── chat.py            # 채팅 요청 라우팅 (제공업체별 분기)
│   │   ├── response.py        # OpenAI → Ollama 응답 변환 + 스트림 처리
│   │   └── anthropic.py       # OpenAI ↔ Anthropic 메시지/응답 변환
│   ├── providers/             # 제공업체별 API 클라이언트
│   │   ├── base.py            # 추상 베이스 클래스 (재시도, 에러 처리, Rate Limit)
│   │   ├── standard.py        # 표준 KeyRotator 기반 클라이언트
│   │   ├── google.py          # Google Gemini 전용 (네이티브 API, 도구 변환)
│   │   └── qwen.py            # Qwen OAuth 전용 클라이언트
│   ├── auth/                  # 인증 관리
│   │   ├── key_rotator.py     # API 키 순환기 (멀티 프로세스 안전, 쿼터-Aware)
│   │   └── qwen_oauth.py      # Qwen OAuth 토큰 관리 (만료 시 자동 갱신)
│   ├── core/                  # 핵심 유틸리티
│   │   ├── errors.py          # 에러 처리 (컨텍스트 오버플로우 감지, ProxyRequestError)
│   │   └── logging.py         # 로깅 설정
│   ├── services/              # 서비스 레이어
│   │   └── quota_service.py   # 쿼터 조회 서비스 (Antigravity 연동, 캐싱)
│   ├── models/                # 데이터 모델
│   │   └── quota.py           # AccountQuota, QuotaInfo 데이터클래스
│   └── utils/                 # 유틸리티
│       ├── model_limits.py    # 모델별 컨텍스트 길이 조회
│       ├── schema_sanitizer.py # Google 호환 스키마 정리
│       ├── text_extraction.py # 메시지/응답에서 텍스트 추출
│       ├── thought_filter.py  # Gemini Thinking <thought> 태그 필터
│       └── tokenizer.py       # 토큰 추정 유틸리티
├── tests/                     # 테스트 코드
├── Dockerfile                 # Docker 이미지 빌드
├── docker-compose.yml         # Docker Compose (ollama-proxy + antigravity-proxy)
├── run.sh                     # 프로덕션 배포 스크립트
├── run-dev.sh                 # 개발 환경 실행 스크립트
├── run-test.sh                # 로컬 통합 테스트 스크립트
└── requirements.txt           # Python 의존성
```

## 설치 및 실행

### 1. 의존성 설치

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 생성하고 제공업체별 API 키를 설정합니다.

```env
# 프록시 서버 자체 인증 토큰 (필수)
PROXY_API_TOKEN="your-proxy-token-here"

# Google Gemini API 키 (쉼표 또는 개행으로 구분, 여러 개 가능)
GOOGLE_API_KEYS="key1,key2,key3"

# OpenRouter API 키
OPENROUTER_API_KEYS="key1,key2"

# Akash API 키
AKASH_API_KEYS="key1"

# Cohere API 키
COHERE_API_KEYS="key1,key2"

# Codestral (Mistral) API 키
CODESTRAL_API_KEYS="key1"

# Nvidia NIM API 키
NVIDIA_NIM_API_KEYS="key1"
# Nvidia NIM Base URL (선택, 기본값: https://integrate.api.nvidia.com/v1)
NVIDIA_NIM_BASE_URL="https://integrate.api.nvidia.com/v1"

# Antigravity 프록시 토큰
ANTIGRAVITY_API_KEYS="token1,token2"
# Antigravity 프록시 URL (선택, 기본값: http://antigravity-proxy:5010/v1)
ANTIGRAVITY_PROXY_URL="http://antigravity-proxy:5010/v1"

# CLI Proxy API 키
CLI_PROXY_API_KEYS="key1"
CLI_PROXY_API_GPT_KEYS="key1"
# CLI Proxy API Base URL (선택, 기본값: http://cli-proxy-api:8317/v1)
CLI_PROXY_API_BASE_URL="http://cli-proxy-api:8317/v1"
# CLI Proxy API Plus Base URL (선택, 기본값: http://cli-proxy-api-plus:8317/v1)
# API 키는 CLI_PROXY_API_KEYS를 함께 사용
CLI_PROXY_API_PLUS_BASE_URL="http://cli-proxy-api-plus:8317/v1"

# Cursor API Proxy (cursor-api-proxy, 호스트에서 8765 실행 시)
CURSOR_API_KEYS="unused"
CURSOR_API_BASE_URL="http://host.docker.internal:8765/v1"

# Ollama Cloud API 키 (환경 변수명은 OLLAMA_API_KEYS 사용)
OLLAMA_API_KEYS="key1,key2"
OLLAMA_BASE_URL="https://ollama.com/v1"

# OpenCode Go API 키
OPENCODE_API_KEYS="key1,key2"
OPENCODE_BASE_URL="https://opencode.ai/zen/go/v1"

# 선택적 설정
PORT=5005
LOG_LEVEL=INFO
FLASK_DEBUG=false
```

Qwen은 OAuth 2.0 인증을 사용하므로 `~/.qwen/oauth_creds.json` 파일이 필요합니다.

```json
{
  "access_token": "your_access_token",
  "refresh_token": "your_refresh_token",
  "expires_at": 1711234567
}
```

### 3. 서버 실행

```bash
# 개발 모드
python app.py

# 프로덕션 (gunicorn, 10 워커)
gunicorn --workers=10 --preload --bind 0.0.0.0:5002 --timeout=300 app:app
```

### 4. Docker 실행

```bash
# 전체 스택 (ollama-proxy + antigravity-proxy)
docker-compose up -d

# ollama-proxy 만 재빌드/재시작
./run-dev.sh
```

## 사용 예시

### Ollama 클라이언트 (curl)

```bash
curl -X POST http://localhost:5005/api/chat \
  -H "Authorization: Bearer $PROXY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google:gemini-3-flash-preview",
    "messages": [{"role": "user", "content": "안녕하세요!"}],
    "stream": false
  }'
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="<PROXY_API_TOKEN>",
    base_url="http://localhost:5005/v1"
)

response = client.chat.completions.create(
    model="google:gemini-3-flash-preview",
    messages=[{"role": "user", "content": "안녕하세요!"}],
    stream=False
)

print(response.choices[0].message.content)
```

### Anthropic Messages API (Claude Code 등)

```bash
curl -X POST http://localhost:5005/v1/messages \
  -H "Authorization: Bearer $PROXY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode:deepseek-v4-pro",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

### 모델 목록 조회

```bash
# Ollama 형식
curl -H "Authorization: Bearer $PROXY_API_TOKEN" http://localhost:5005/api/tags

# OpenAI 형식
curl -H "Authorization: Bearer $PROXY_API_TOKEN" http://localhost:5005/v1/models
```

### API 키 상태 확인

```bash
curl -H "Authorization: Bearer $PROXY_API_TOKEN" http://localhost:5005/v1/keys/status
```

응답 예시:

```json
{
  "providers": [
    {
      "provider": "OllamaCloud",
      "total_keys": 3,
      "available_keys": 2,
      "rate_limited_keys": 1,
      "keys": [
        {
          "index": 0,
          "key_hash": "a1b2c3d4",
          "status": "available",
          "usage_count": 42,
          "failure_count": 0,
          "health_score": 1.0,
          "retry_after_sec": null
        }
      ]
    }
  ]
}
```

## 아키텍처

### 요청 흐름

```
클라이언트 → [인증] → [라우트] → [ChatHandler] → [Provider Client] → Upstream API
                │          │              │
                │          │              ├─ google: → GoogleApiClient (Gemini 네이티브 API)
                │          │              ├─ qwen:   → QwenApiClient (OAuth)
                │          │              └─ 그 외:   → StandardApiClient (OpenAI 호환)
                │          │
                │          └─ Ollama 형식: ResponseHandler로 응답 변환 (SSE → NDJSON)
                │             OpenAI 형식: 응답 그대로 전달
                │             Anthropic 형식: AnthropicHandler로 메시지/응답 변환
                │
                └─ PROXY_API_TOKEN 검증 (Bearer 또는 x-api-key)
```

### 키 순환 메커니즘

`KeyRotator`는 Gunicorn 멀티 워커 환경에서도 안전하게 동작합니다.

1. **파일 락 (`fcntl.flock`)**: `/tmp/key_rotator_{provider}.lock` 파일로 프로세스 간 동기화
2. **인덱스 파일**: `/tmp/key_rotator_{provider}.index` 파일로 현재 순환 위치 공유
3. **스레드 락**: `threading.Lock`으로 동일 프로세스 내 스레드 간 동기화
4. **건강도 점수**: 각 키의 실패율, Rate Limit 상태, 마지막 사용 시간을 추적하여 최적 키 선택
5. **Rate Limit 복구**: 429 응답 시 해당 키를 `retry_after` 초만큼 차단 후 자동 복구

## 주의 사항

- API 호출은 각 제공업체의 요금 정책과 사용 제한에 따릅니다.
- API 키는 반드시 환경 변수나 `.env` 파일로 관리하고, 코드에 하드코딩하지 마십시오.
- 프로덕션 환경에서는 반드시 gunicorn 등 WSGI 서버를 사용하십시오.
- `.env` 파일과 `~/.qwen/oauth_creds.json` 파일은 `.gitignore`에 등록되어 Git에 커밋되지 않도록 되어 있습니다.
