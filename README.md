# Ollama 프록시

Ollama 프록시는 다양한 LLM(대규모 언어 모델) 제공업체와 상호 작용하기 위한 통합된 Ollama 유사 API 인터페이스를 제공하는 Flask 기반 서버입니다. 이 프록시를 사용하면 일관된 API 인터페이스를 유지하면서 다양한 LLM 제공업체(Google, OpenRouter, Akash)를 사용할 수 있습니다.

## 기능

- Ollama API 인터페이스와 호환
- 다양한 LLM 제공업체 지원:
    - Google AI 모델
    - OpenRouter 모델
    - Akash Network 모델
- 스트리밍 및 비스트리밍 응답 처리
- 부하 분산 및 대체를 위한 API 키 순환
- 쉬운 배포를 위한 Docker 지원

## 설치

### 사전 요구 사항

- Python 3.11 이상
- pip (Python 패키지 관리자)

### 로컬 설정

1. 저장소 복제:
   ```bash
   git clone https://github.com/jjb8966/ollama-proxy
   cd ollama-proxy
   ```

2. 가상 환경 생성(권장):
   ```bash
   python -m venv myenv
   source myenv/bin/activate  # Windows의 경우: myenv\Scripts\activate
   ```

3. 의존성 설치:
   ```bash
   pip install -r requirements.txt
   ```

4. 환경 변수 설정:
   
    **Linux/macOS:**
   ```bash
   export GOOGLE_API_KEYS="your-google-api-key-1,your-google-api-key-2"
   export OPENROUTER_API_KEYS="your-openrouter-api-key-1,your-openrouter-api-key-2"
   export AKASH_API_KEYS="your-akash-api-key-1,your-akash-api-key-2"
   ```

    **Windows Command Prompt:**
   ```cmd
   set GOOGLE_API_KEYS=your-google-api-key-1,your-google-api-key-2
   set OPENROUTER_API_KEYS=your-openrouter-api-key-1,your-openrouter-api-key-2
   set AKASH_API_KEYS=your-akash-api-key-1,your-akash-api-key-2
   ```

   **Windows PowerShell:**
   ```powershell
   $env:GOOGLE_API_KEYS="your-google-api-key-1,your-google-api-key-2"
   $env:OPENROUTER_API_KEYS="your-openrouter-api-key-1,your-openrouter-api-key-2"
   $env:AKASH_API_KEYS="your-akash-api-key-1,your-akash-api-key-2"
   ```

## 서버 실행

### 로컬 실행

다음 명령으로 서버를 실행합니다:

```bash
python ollama_proxy.py
```

기본적으로 서버는 포트 5005에서 실행됩니다. `PORT` 환경 변수를 설정하여 이를 변경할 수 있습니다:

```bash
PORT=8080 python ollama_proxy.py
```

디버그 모드를 활성화하려면:

```bash
FLASK_DEBUG=true python ollama_proxy.py
```

### Docker 배포

1. Docker Compose를 사용하여 빌드 및 실행:
   ```bash
   docker-compose up -d
   ```

2. 또는 수동으로 빌드 및 실행:
   ```bash
   docker build -t ollama-proxy .
   docker run -p 5002:5002 \
     -e GOOGLE_API_KEYS="your-google-api-keys" \
     -e OPENROUTER_API_KEYS="your-openrouter-api-keys" \
     -e AKASH_API_KEYS="your-akash-api-keys" \
     --name ollama-proxy ollama-proxy
   ```

## API 엔드포인트

### 1. 채팅 완성

**엔드포인트:** `/api/chat`  
**메서드:** `POST`  
**설명:** 채팅 완성 요청을 처리하고 적절한 LLM 제공업체로 전달합니다.

**요청 형식:**
```json
{
  "model": "google:gemini-2.5-pro-exp-03-25",
  "messages": [
    {"role": "user", "content": "안녕하세요, 어떻게 지내세요?"}
  ],
  "stream": true
}
```

**응답 형식(비스트리밍):**
```json
{
  "model": "gemini-2.5-pro-exp-03-25",
  "created_at": "2023-06-01T12:00:00Z",
  "message": {
    "role": "assistant",
    "content": "잘 지내고 있습니다. 감사합니다! 오늘 어떻게 도와드릴까요?"
  },
  "done": true
}
```

**스트리밍 응답:**
스트리밍 응답은 응답의 일부를 포함하는 일련의 청크를 반환합니다.

### 2. 사용 가능한 모델

**엔드포인트:** `/api/tags`  
**메서드:** `GET`  
**설명:** 사용 가능한 모델 목록을 반환합니다.

**응답 형식:**
```json
{
  "models": [
    {
      "name": "google:gemini-2.5-pro-exp-03-25",
      "model": "google:gemini-2.5-pro-exp-03-25"
    },
    {
      "name": "openrouter:meta-llama/llama-4-maverick:free",
      "model": "openrouter:meta-llama/llama-4-maverick:free"
    },
    ...
  ]
}
```

### 3. 버전 정보

**엔드포인트:** `/api/version` 또는 `/`  
**메서드:** `GET`  
**설명:** 프록시에 대한 버전 정보를 반환합니다.

**응답 형식:**
```json
{
  "version": "0.1.0-openai-proxy"
}
```

## 모델 명명 규칙

프록시는 요청을 적절한 제공업체로 라우팅하기 위해 접두사 기반 명명 규칙을 사용합니다:

- `google:` - Google AI 모델로 라우팅 (예: `google:gemini-2.5-pro-exp-03-25`)
- `openrouter:` - OpenRouter 모델로 라우팅 (예: `openrouter:meta-llama/llama-4-maverick:free`)
- `akash:` - Akash Network 모델로 라우팅 (예: `akash:DeepSeek-R1`)

## 구성

### 환경 변수

- `GOOGLE_API_KEYS`: 쉼표로 구분된 Google AI API 키 목록
- `OPENROUTER_API_KEYS`: 쉼표로 구분된 OpenRouter API 키 목록
- `AKASH_API_KEYS`: 쉼표로 구분된 Akash Network API 키 목록
- `PORT`: 서버의 포트 번호 (기본값: 5005)
- `FLASK_DEBUG`: "true"로 설정하면 디버그 모드 활성화 (기본값: "false")

## API 키 순환

프록시는 다음을 위해 API 키 순환을 구현합니다:
- 여러 API 키에 걸쳐 부하 분산
- 속도 제한이나 키 실패 시 대체 제공
- 서비스의 가용성 최대화

하나의 API 키로 요청이 실패하면 시스템은 자동으로 다음 사용 가능한 키를 시도합니다.