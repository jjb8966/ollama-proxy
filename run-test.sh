#!/bin/bash
set -e

cd "$(dirname "$0")"

TEST_PORT=5008

echo "========================================="
echo "🧪 Ollama-Proxy 로컬 테스트"
echo "========================================="
echo ""
echo "⚠️  Docker 컨테이너를 사용하지 않고 로컬에서 테스트합니다."
echo "   테스트 포트: $TEST_PORT"
echo ""

# 가상 환경 확인
if [ ! -d "venv" ]; then
    echo "❌ 가상 환경이 없습니다. 먼저 생성하세요:"
    echo "   python3 -m venv venv"
    exit 1
fi

# 가상 환경 활성화 (source 대신 직접 사용)
PYTHON="$(cd venv && pwd)/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "❌ Python 실행 파일을 찾을 수 없습니다: $PYTHON"
    exit 1
fi

echo "✅ Python 확인: $PYTHON"
$PYTHON --version
echo ""

# 의존성 확인
echo "📦 의존성 확인 중..."
$PYTHON -c "import flask, requests" 2>/dev/null || {
    echo "❌ 필요한 패키지가 없습니다. 설치하세요:"
    echo "   pip install -r requirements.txt"
    exit 1
}
echo "✅ 의존성 확인 완료"
echo ""

# Python 문법 검사
echo "🔍 Python 문법 검사 중..."
$PYTHON -m py_compile app.py config.py src/handlers/response.py src/handlers/chat.py src/auth/key_rotator.py src/services/quota_service.py || {
    echo "❌ 문법 오류 발견!"
    exit 1
}
echo "✅ 문법 검사 통과"
echo ""

# .env 파일 확인
if [ ! -f ".env" ]; then
    echo "❌ .env 파일이 없습니다."
    exit 1
fi

# 환경 변수 로드 (Python으로 안전하게 파싱)
echo "📂 환경 변수 로드 중..."
$PYTHON << 'EOF'
import os
import re

with open('.env', 'r') as f:
    content = f.read()

# 간단한 파서
lines = content.split('\n')
export_lines = []
for line in lines:
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    if '=' in line:
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value:
            export_lines.append(f'{key}={value}')

with open('/tmp/env_export.sh', 'w') as f:
    f.write('\n'.join(export_lines))
EOF

while IFS= read -r line || [ -n "$line" ]; do
    [ -z "$line" ] && continue
    export "$line"
done < /tmp/env_export.sh
rm -f /tmp/env_export.sh

echo "✅ 환경 변수 로드 완료"
echo "   PROXY_API_TOKEN: ${PROXY_API_TOKEN:0:10}..."
echo "   OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-not set}"

# API 키 개수 확인
KEY_COUNT=$(echo "$OLLAMA_API_KEYS" | tr ',' '\n' | grep -v '^$' | wc -l)
echo "   OLLAMA_API_KEYS: $KEY_COUNT 개"
echo ""

# 테스트 서버 실행
echo "🚀 테스트 서버 시작 (port: $TEST_PORT)..."
PORT=$TEST_PORT $PYTHON app.py &
SERVER_PID=$!
echo "   PID: $SERVER_PID"

# 종료 시 정리
cleanup() {
    echo ""
    echo "🛑 테스트 서버 종료 중..."
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
}
trap cleanup EXIT

# 서버 시작 대기
echo "⏳ 서버 시작 대기 중..."
for i in {1..30}; do
    if curl -s -o /dev/null -w "%{http_code}" http://localhost:$TEST_PORT/v1/models 2>/dev/null | grep -q "401\|403"; then
        echo "✅ 서버 응답 확인 (401 Unauthorized = 정상)"
        break
    fi
    sleep 0.5
done

echo ""
echo "========================================="
echo "🧪 테스트 실행"
echo "========================================="
echo ""

# 테스트 1: 인증 없이 요청
echo "테스트 1: 인증 오류 확인"
RESPONSE=$(curl -s -w "\n%{http_code}" http://localhost:$TEST_PORT/v1/models 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
if [ "$HTTP_CODE" = "401" ]; then
    echo "   ✅ 인증 오류 확인 (HTTP 401)"
else
    echo "   ❌ 예상치 못한 응답: HTTP $HTTP_CODE"
fi
echo ""

# 테스트 2: 인증된 요청 - 모델 목록
echo "테스트 2: 모델 목록 조회"
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer $PROXY_API_TOKEN" \
    http://localhost:$TEST_PORT/v1/models 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')
if [ "$HTTP_CODE" = "200" ]; then
    MODEL_COUNT=$(echo "$BODY" | grep -o '"id":' | wc -l)
    echo "   ✅ 모델 목록 조회 성공 (HTTP 200)"
    echo "   📊 약 $MODEL_COUNT 개 모델 발견"
else
    echo "   ❌ 응답 오류: HTTP $HTTP_CODE"
    echo "$BODY" | head -20
fi
echo ""

# 테스트 3: 쿼터 API
echo "테스트 3: 쿼터 조회 API"
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer $PROXY_API_TOKEN" \
    http://localhost:$TEST_PORT/v1/quota 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')
if [ "$HTTP_CODE" = "200" ]; then
    echo "   ✅ 쿼터 API 응답 성공 (HTTP 200)"
    echo "$BODY" | python3 -m json.tool 2>/dev/null | head -20 || echo "$BODY" | head -5
else
    echo "   ❌ 응답 오류: HTTP $HTTP_CODE"
    echo "$BODY" | head -5
fi
echo ""

# 테스트 4: 건강 체크 (Ollama 형식)
echo "테스트 4: Ollama 형식 엔드포인트"
RESPONSE=$(curl -s -w "\n%{http_code}" \
    -H "Authorization: Bearer $PROXY_API_TOKEN" \
    http://localhost:$TEST_PORT/api/tags 2>/dev/null)
HTTP_CODE=$(echo "$RESPONSE" | tail -1)
if [ "$HTTP_CODE" = "200" ]; then
    echo "   ✅ Ollama /api/tags 응답 성공 (HTTP 200)"
else
    echo "   ❌ 응답 오류: HTTP $HTTP_CODE"
fi
echo ""

# 테스트 5: chat completions 엔드포인트 (스트리밍 비활성화)
echo "테스트 5: Chat completions 엔드포인트"
echo "   모델: google:gemini-3-flash-preview (Google API 키 사용)"
echo "   요청 전송 중... (최대 10초 대기)"

RESPONSE=$(curl -s -w "\n%{http_code}" \
    --max-time 10 \
    -H "Authorization: Bearer $PROXY_API_TOKEN" \
    -H "Content-Type: application/json" \
    -X POST \
    -d '{
      "model": "google:gemini-3-flash-preview",
      "messages": [{"role": "user", "content": "Say hello"}],
      "stream": false,
      "max_tokens": 50
    }' \
    http://localhost:$TEST_PORT/v1/chat/completions 2>/dev/null || echo -e "\n000")

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    echo "   ✅ Chat completions 응답 성공 (HTTP 200)"
    # 응답에서 content 추출 시도
    CONTENT=$(echo "$BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('choices',[{}])[0].get('message',{}).get('content','N/A')[:50])" 2>/dev/null || echo "N/A")
    echo "   💬 응답 미리보기: $CONTENT"
elif [ "$HTTP_CODE" = "000" ]; then
    echo "   ⏱️  타임아웃 또는 연결 실패"
elif [ "$HTTP_CODE" = "400" ]; then
    echo "   ⚠️  응답: HTTP 400 (요청 오류)"
    ERROR_MSG=$(echo "$BODY" | $PYTHON -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',{}).get('message','Unknown'))" 2>/dev/null)
    [ -n "$ERROR_MSG" ] && echo "      에러: $ERROR_MSG"
elif [ "$HTTP_CODE" = "500" ]; then
    echo "   ⚠️  응답: HTTP 500 (서버 오류)"
    echo "      (실제 API 호출 시도 중 오류 - API 키 또는 네트워크 문제 가능)"
else
    echo "   ⚠️  응답: HTTP $HTTP_CODE"
    echo "$BODY" | head -3
fi
echo ""

echo "========================================="
echo "✅ 로컬 테스트 완료"
echo "========================================="
echo ""
echo "이제 Docker 컨테이너를 실행하려면:"
echo "   ./run-dev.sh"
echo ""
