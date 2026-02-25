# Ollama Proxy Server

여러 LLM 제공업체(Google, OpenRouter, Akash, Cohere, Codestral, Qwen, Perplexity)의 OpenAI 호환 API를 **Ollama 호환 API** 및 **OpenAI 호환 API** 형태로 제공하는 프록시 서버입니다.

## 주요 기능

| 기능 | 설명 |
|------|------|
| **다중 제공업체 지원** | 7개 LLM 제공업체를 단일 인터페이스로 사용 |
| **API 키 자동 순환** | 여러 API 키를 라운드 로빈 방식으로 순환하여 rate limit 분산 |
| **OAuth 토큰 관리** | Qwen의 OAuth 토큰 자동 갱신 |
| **스트리밍 지원** | 스트리밍/비스트리밍 모두 지원 |
| **이중 호환성** | Ollama 클라이언트와 OpenAI SDK 모두 사용 가능 |

## 엔드포인트

| 스타일 | 엔드포인트 | 설명 |
|--------|------------|------|
| Ollama | `POST /api/chat` | 채팅 요청 |
| Ollama | `GET /api/tags` | 모델 목록 |
| Ollama | `GET /api/version` | 버전 정보 |
| OpenAI | `POST /v1/chat/completions` | 채팅 완료 |
| OpenAI | `GET /v1/models` | 모델 목록 |

## 프로젝트 구조

```
ollama-proxy/
├── app.py                 # 애플리케이션 진입점
├── config.py              # API 설정 및 인증 관리
├── models.json            # 사용 가능한 모델 목록
├── src/
│   ├── routes/            # API 라우트
│   │   ├── ollama.py      # Ollama 호환 엔드포인트
│   │   └── openai.py      # OpenAI 호환 엔드포인트
│   ├── handlers/          # 요청/응답 핸들러
│   │   ├── chat.py        # 채팅 요청 처리
│   │   └── response.py    # 응답 변환
│   ├── providers/         # API 클라이언트
│   │   ├── base.py        # 베이스 클래스
│   │   ├── standard.py    # 표준 API 클라이언트
│   │   └── qwen.py        # Qwen OAuth 클라이언트
│   ├── auth/              # 인증
│   │   ├── key_rotator.py # API 키 순환
│   │   └── qwen_oauth.py  # Qwen OAuth 관리
│   └── core/              # 핵심 유틸리티
│       ├── logging.py     # 로깅 설정
│       └── errors.py      # 에러 처리
├── Dockerfile             # Docker 빌드 설정
├── docker-compose.yml     # Docker Compose 설정
├── requirements.txt       # Python 의존성
└── run.sh                 # 배포 스크립트
```

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env` 파일을 생성하고 API 키를 설정합니다:

```env
# 각 제공업체의 API 키 (쉼표로 구분하여 여러 개 설정 가능)
GOOGLE_API_KEYS="key1,key2,key3"
OPENROUTER_API_KEYS="key1,key2"
AKASH_API_KEYS="key1"
COHERE_API_KEYS="key1,key2"
CODESTRAL_API_KEYS="key1"
PERPLEXITY_API_KEYS="key1"

# 선택적 설정
PORT=5005
LOG_LEVEL=INFO
FLASK_DEBUG=false
```

Qwen은 OAuth를 사용하므로 `~/.qwen/oauth_creds.json` 파일이 필요합니다:

```json
{
  "access_token": "your_access_token",
  "refresh_token": "your_refresh_token",
  "expires_at": 1234567890
}
```

### 3. 서버 실행

```bash
# 개발 모드
python app.py

# 프로덕션 (gunicorn)
gunicorn --workers=4 --bind 0.0.0.0:5005 --timeout=300 app:app
```

### 4. Docker로 실행

```bash
docker-compose up -d
```

## 사용 예시

### Ollama 클라이언트 (curl)

```bash
curl -X POST http://localhost:5005/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "google:gemini-2.5-flash",
    "messages": [{"role": "user", "content": "Hello!"}],
    "stream": false
  }'
```

### OpenAI Python SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="dummy",  # 프록시 자체는 이 키를 사용하지 않습니다
    base_url="http://localhost:5005/v1"
)

response = client.chat.completions.create(
    model="google:gemini-2.5-flash",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=False
)

print(response.choices[0].message.content)
```

## 지원 모델

모델 이름은 `제공업체:모델명` 형식으로 지정합니다:

| 제공업체 | 예시 |
|----------|------|
| Google | `google:gemini-2.5-flash` |
| OpenRouter | `openrouter:mistralai/devstral-2512:free` |
| Cohere | `cohere:command-a-03-2025` |
| Codestral | `codestral:codestral-2508` |
| Qwen | `qwen:qwen3-coder-plus` |
| Perplexity | `perplexity:sonar` |
| Akash | `akash:Meta-Llama-3-1-8B-Instruct-FP8` |

전체 모델 목록은 `models.json` 파일에서 확인하거나 `/api/tags` 엔드포인트를 호출하세요.

## 주의 사항

- API 호출은 각 제공업체의 요금 정책과 제한에 따릅니다.
- API 키는 환경 변수나 `.env` 파일로 관리하세요. 코드에 하드코딩하지 마세요.
- 프로덕션 환경에서는 gunicorn 등 WSGI 서버를 사용하세요.
