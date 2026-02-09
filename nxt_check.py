import requests
import json
import config
import token_manager

TARGET_CODE = "005930"  # 삼성전자
MODE = "REAL"

def check_ats_ticks():
    print(f"🚀 [넥스트트레이드] 체결 내역(Tick) 우회 검증 - {TARGET_CODE}")
    
    # 1. 토큰 발급
    access_token = token_manager.get_access_token(MODE)
    if not access_token: return

    base_url = "https://openapi.koreainvestment.com:9443"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": config.REAL_API_KEY,
        "appSecret": config.REAL_API_SECRET,
        "tr_id": "FHKST01010400",  # ✅ 현재가(100) 대신 주식현재가 시세 체결추이(400) 사용
        "custtype": "P"
    }

    # 2. 체결내역 조회
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",  # 통합 코드
        "FID_INPUT_ISCD": TARGET_CODE,
        "FID_INPUT_HOUR_1": "160000",   # 16시 기준 조회 (ATS 시간대)
        "FID_PW_DATA_INCU_YN": "N"      # 과거 데이터 포함 여부
    }

    try:
        res = requests.get(url, headers=headers, params=params).json()
        
        if res['rt_cd'] == '0':
            outputs = res['output2'] # 체결 내역 리스트
            
            print(f"📊 최근 체결 내역 (상위 5개):")
            found_ats = False
            
            for i, item in enumerate(outputs[:10]):
                time_str = item['stck_cntg_hour'] # 체결 시간 (HHMMSS)
                price = item['stck_prpr']
                vol = item['cntg_vol']
                
                # 15:30 이후 데이터인지 확인
                is_after_market = int(time_str) > 153000
                mark = "🟢ATS(NXT)" if is_after_market else "⚪KRX(정규)"
                
                print(f"   [{i+1}] {time_str} | {price}원 | {vol}주 | {mark}")
                
                if is_after_market:
                    found_ats = True

            print("-" * 50)
            if found_ats:
                print("🎉 [성공] 15:30 이후 체결 내역이 발견되었습니다!")
                print("   👉 현재가 조회(100) 대신 이 체결 API(400)를 사용하면 시세를 볼 수 있습니다.")
            else:
                print("❄️ [실패] 15:30 이후 체결 내역이 전혀 없습니다.")
                print("   👉 정말로 계좌의 [넥스트트레이드 서비스]가 미신청 상태일 확률 99%입니다.")
        else:
            print(f"❌ 조회 실패: {res['msg1']}")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    check_ats_ticks()
