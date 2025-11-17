# Ollama Proxy Server

이 프로젝트는 여러 LLM 제공업체(Google, OpenRouter, Akash, Cohere, Codestral, Qwen)의 OpenAI 호환 API를 **Ollama 호환 API** 및 **OpenAI 호환 API** 형태로 변환해 주는 프록시 서버입니다.

- Ollama 스타일 엔드포인트: `/api/chat`, `/api/tags`, `/api/version`
- OpenAI 스타일 엔드포인트: `/v1/chat/completions`, `/v1/models`

## 주요 기능

- 다양한 LLM 제공업체에 대한 API 키 로테이션 및 에러 핸들링
- Ollama 클라이언트가 사용할 수 있는 `/api/chat`, `/api/tags` 인터페이스 제공
- OpenAI SDK 및 호환 클라이언트에서 사용할 수 있는 `/v1/chat/completions`, `/v1/models` 인터페이스 제공
- 스트리밍/비스트리밍 요청 모두 지원

## 요구 사항

- Python 3.10+ (권장)
- pip 또는 호환되는 패키지 매니저

## 설치 및 실행

1. 의존성 설치

```bash
pip install -r requirements.txt
```

2. 환경 변수 설정 (.env 파일 권장)

아래 환경 변수에 각 제공업체의 API 키를 설정합니다. 여러 키를 사용할 경우 `,` 로 구분하여 입력합니다.

```env
GOOGLE_API_KEYS="key1,key2,..."
OPENROUTER_API_KEYS="key1,key2,..."
AKASH_API_KEYS="key1,key2,..."
COHERE_API_KEYS="key1,key2,..."
CODESTRAL_API_KEYS="key1,key2,..."
QWEN_API_KEYS="key1,key2,..."
```

3. 서버 실행

```bash
python ollama_proxy.py
```

기본 포트는 `5005` 이며, 환경 변수 `PORT` 로 변경할 수 있습니다.

```bash
PORT=5005 python ollama_proxy.py
```

## 엔드포인트 설명

### 1. Ollama 스타일 API

#### `POST /api/chat`

- Ollama 호환 채팅 엔드포인트입니다.
- 요청 예시

```json
{
  "model": "google:gemini-2.5-pro",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "stream": true
}
```

- 응답
  - `stream: true` 인 경우: `application/x-ndjson` 형식의 Ollama 스타일 스트리밍 청크
  - `stream: false` 인 경우: 단일 Ollama 스타일 JSON 응답

#### `GET /api/tags`

- Ollama 의 `/api/tags` 를 모방하여, 사용 가능한 모델 목록을 반환합니다.

#### `GET /` 및 `GET /api/version`

- 프록시 서버 버전 정보를 반환합니다.

---

### 2. OpenAI 스타일 API

#### `POST /v1/chat/completions`

- OpenAI Chat Completions 호환 엔드포인트입니다.
- OpenAI SDK 또는 호환 클라이언트에서 `base_url` 만 이 프록시로 변경하면 사용할 수 있습니다.

- 요청 예시

```json
{
  "model": "google:gemini-2.5-pro",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "stream": false
}
```

- 동작 방식
  - `stream: false` 인 경우: 업스트림(OpenAI 호환 백엔드)의 JSON 응답을 그대로 반환
  - `stream: true` 인 경우: 업스트림의 SSE/스트리밍 응답을 그대로 프록시

> 모델 이름은 `google:...`, `openrouter:...`, `akash:...`, `cohere:...`, `codestral:...`, `qwen:...` 과 같이 prefix 를 포함해 지정합니다.

#### `GET /v1/models`

- OpenAI 의 `/v1/models` 형식을 모방하여, 현재 프록시가 노출하는 모델 목록을 반환합니다.

응답 예시:

```json
{
  "object": "list",
  "data": [
    {
      "id": "google:gemini-2.5-pro",
      "object": "model",
      "created": 0,
      "owned_by": "proxy"
    }
  ]
}
```

---

## 구조 개요

- `ollama_proxy.py`
  - Flask 앱 진입점
  - `/api/chat`, `/api/tags`, `/api/version`, `/v1/chat/completions`, `/v1/models` 라우트 정의
- `chat_handler.py`
  - 클라이언트 요청을 각 제공업체별 OpenAI 호환 백엔드로 전달하는 로직
- `response_handler.py`
  - OpenAI 호환 응답을 Ollama 스타일 응답으로 변환하는 로직
- `config.py`
  - 각 제공업체의 기본 URL 및 모델 prefix 처리, API 키 로테이션 설정
- `utils/api_client.py`
  - 실제 HTTP 요청 및 재시도, 키 로테이션 처리
- `utils/key_rotator.py`
  - 다수의 API 키를 순환하며 사용하도록 지원
- `utils/error_handlers.py`, `utils/logging_config.py`
  - 에러/로그 처리 유틸리티

## OpenAI SDK에서 사용 예시 (Python)

```python
from openai import OpenAI

client = OpenAI(
    api_key="dummy",  # 프록시 자체는 이 키를 사용하지 않습니다.
    base_url="http://localhost:5005/v1"
)

resp = client.chat.completions.create(
    model="google:gemini-2.5-pro",
    messages=[{"role": "user", "content": "Hello!"}],
    stream=False,
)

print(resp.choices[0].message.content)
```

## 주의 사항

- 실제 호출은 각 제공업체의 요금 정책과 제한에 따릅니다.
- API 키는 절대 코드에 하드코딩하지 말고, 환경 변수 또는 .env 파일을 이용해 관리하세요.
