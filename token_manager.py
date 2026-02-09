import requests
import json
import datetime
import os
import config

# 💾 토큰을 저장할 통합 파일명
TOKEN_FILE = "kis_token.json"

def load_token_data():
    """JSON 파일에서 전체 토큰 데이터를 읽어옵니다."""
    if not os.path.exists(TOKEN_FILE):
        return {}
    
    try:
        with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_token_data(mode, token, expired_at):
    """토큰 정보를 JSON 파일에 저장합니다. (기존 데이터 유지)"""
    data = load_token_data()
    
    data[mode] = {
        "access_token": token,
        "expired_at": expired_at
    }
    
    with open(TOKEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_access_token(mode="MOCK"):
    """
    접근 토큰을 반환합니다.
    1. 파일에 저장된 토큰이 유효하면 -> 그대로 사용 (API 호출 X)
    2. 없거나 만료되었으면 -> API 호출하여 재발급 후 파일 저장
    :param mode: "REAL" (실전) 또는 "MOCK" (모의)
    """
    
    # [1] 파일에서 저장된 토큰 확인
    saved_data = load_token_data()
    
    if mode in saved_data:
        token_info = saved_data[mode]
        expired_at_str = token_info.get("expired_at")
        
        if expired_at_str:
            expired_at = datetime.datetime.strptime(expired_at_str, "%Y-%m-%d %H:%M:%S")
            # 만료 1분 전까지만 재사용 (안전마진)
            if datetime.datetime.now() < expired_at - datetime.timedelta(seconds=60):
                # print(f"✅ [{mode}] 기존 토큰 유효 (만료: {expired_at_str})") # 너무 자주 뜨면 주석 처리
                return token_info["access_token"]

    # [2] 토큰 재발급 요청 (유효하지 않을 경우)
    return issue_new_token(mode)

def issue_new_token(mode):
    print(f"🔄 [{mode}] 새로운 토큰 발급 요청 중...")
    
    if mode == "REAL":
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        appkey = config.REAL_API_KEY
        appsecret = config.REAL_API_SECRET
    else: # MOCK
        url = "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
        appkey = config.MOCK_API_KEY
        appsecret = config.MOCK_API_SECRET

    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": appkey,
        "appsecret": appsecret
    }

    try:
        res = requests.post(url, headers=headers, data=json.dumps(body))
        
        if res.status_code == 200:
            data = res.json()
            access_token = data['access_token']
            expires_in = int(data['expires_in']) # 유효기간(초)
            
            # 만료 시간 계산
            expired_at = datetime.datetime.now() + datetime.timedelta(seconds=expires_in)
            expired_at_str = expired_at.strftime("%Y-%m-%d %H:%M:%S")
            
            # [3] 파일에 저장
            save_token_data(mode, access_token, expired_at_str)
            
            print(f"✅ [{mode}] 토큰 발급 완료 (만료: {expired_at_str})")
            return access_token
        else:
            print(f"❌ 토큰 발급 실패: {res.json()}")
            return None
            
    except Exception as e:
        print(f"❌ 토큰 요청 중 에러 발생: {e}")
        return None

if __name__ == "__main__":
    # 테스트 실행
    print("--- REAL 모드 테스트 ---")
    print(get_access_token("REAL"))
    print("\n--- MOCK 모드 테스트 ---")
    print(get_access_token("MOCK"))