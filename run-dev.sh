#!/bin/bash
set -e

cd "$(dirname "$0")"

# 1. 로컬 소스로 이미지 빌드 후 컨테이너 실행
# NOTE: 개발 서버에서 antigravity-proxy 컨테이너가 다른 compose 프로젝트로 이미 떠 있을 수 있어
# 이름 충돌로 docker-compose up이 실패하면(set -e) 아래 단계(nginx-network connect)가 실행되지 않습니다.
# 따라서 이 스크립트는 ollama-proxy만 빌드/기동합니다.
echo "🚀 Building and starting ollama-proxy (only) from local source..."
docker-compose up --build -d --no-deps ollama-proxy

# 2. nginx-network 네트워크 연결
echo "🔗 Connecting containers to nginx-network..."
docker network connect nginx-network ollama-proxy 2>/dev/null || echo "⚠️ ollama-proxy already connected or nginx-network not found."
docker network connect nginx-network antigravity-proxy 2>/dev/null || echo "⚠️ antigravity-proxy already connected or nginx-network not found."

# 3. Nginx 설정 리로드
echo "🔄 Reloading Nginx configuration..."
docker exec nginx nginx -s reload 2>/dev/null || echo "⚠️ Nginx container is not running or failed to reload."

# 4. 미사용 이미지 정리
echo "🧹 Pruning unused images..."
docker image prune -a -f

echo "✅ Setup complete!"
