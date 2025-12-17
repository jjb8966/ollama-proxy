# Python 3.11-slim 이미지를 기반으로 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 현재 디렉토리의 모든 파일을 컨테이너의 작업 디렉토리로 복사
COPY . .

# pip를 최신 버전으로 업그레이드하고 requirements.txt에 명시된 의존성 설치
# --no-cache-dir 옵션으로 불필요한 캐시 레이어를 생성하지 않음
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 컨테이너가 리슨할 포트 설정
EXPOSE 5002

# 컨테이너 실행 시 gunicorn을 사용하여 Flask 애플리케이션 실행
# app:app - app.py 파일의 Flask 앱 인스턴스(app)를 지정
CMD ["gunicorn", "--workers=10", "--preload", "--bind", "0.0.0.0:5002", "--timeout=300", "app:app"]
