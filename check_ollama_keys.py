import os
import requests
import json
from concurrent.futures import ThreadPoolExecutor

# Load keys
with open('/home/jjb/Desktop/work/my/project/ollama-proxy/.env', 'r') as f:
    content = f.read()

keys_str = ""
in_keys = False
for line in content.split('\n'):
    if line.startswith('OLLAMA_API_KEYS='):
        in_keys = True
        keys_str += line.split('=', 1)[1] + '\n'
        if line.count("'") == 2:
            in_keys = False
    elif in_keys:
        keys_str += line + '\n'
        if "'" in line:
            in_keys = False

keys = [k.strip() for k in keys_str.strip("'\"\n ").split('\n') if k.strip()]

print(f"총 {len(keys)}개의 Ollama Cloud 키 검사 시작...")

def check_key(idx, key):
    headers = {
        'Authorization': f'Bearer {key}'
    }
    try:
        # models 엔드포인트는 비교적 빠르고 가벼움
        resp = requests.get('https://ollama.com/v1/models', headers=headers, timeout=5)
        status = resp.status_code
        if status == 200:
            return idx, key, "✅ 사용 가능 (200)"
        elif status == 401:
            return idx, key, "❌ 만료/인증 실패 (401)"
        elif status == 429:
            return idx, key, "⚠️ 한도 초과 (429)"
        else:
            return idx, key, f"❓ 알 수 없는 상태 ({status})"
    except Exception as e:
        return idx, key, f"🚨 연결 오류: {str(e)[:30]}"

results = []
with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(check_key, i, k) for i, k in enumerate(keys)]
    for future in futures:
        results.append(future.result())

# 정렬해서 출력
results.sort(key=lambda x: x[0])

expired = 0
rate_limited = 0
available = 0

print("-" * 50)
for idx, key, status in results:
    short_key = key[:8] + "..." + key[-8:] if len(key) > 16 else key
    print(f"[{idx+1:02d}] {short_key}: {status}")
    if "✅" in status: available += 1
    elif "❌" in status: expired += 1
    elif "⚠️" in status: rate_limited += 1

print("-" * 50)
print(f"결과 요약:")
print(f"✅ 사용 가능: {available}개")
print(f"❌ 만료됨: {expired}개")
print(f"⚠️ 한도 초과: {rate_limited}개")
print(f"총계: {len(keys)}개")
