import requests
import json
import config
import token_manager

# ==========================================
# ⚙️ 설정
# ==========================================
TARGET_CODE = "005380"  # 현대차
TARGET_NAME = "현대차"
MODE = "REAL"           # 실전투자 서버 사용 (데이터 정확도 위함)

# ==========================================
# 📡 API 호출 함수 (봇 로직 축소판)
# ==========================================
def check_hyundai_wick():
    print(f"🔍 [{TARGET_NAME}({TARGET_CODE})] 시세 조회 및 윗꼬리 계산 시작...\n")

    # 1. 토큰 발급
    access_token = token_manager.get_access_token(MODE)
    if not access_token:
        print("❌ 토큰 발급 실패")
        return

    # 2. 헤더 설정
    base_url = "https://openapi.koreainvestment.com:9443"  # 실전 서버
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": config.REAL_API_KEY,
        "appSecret": config.REAL_API_SECRET,
        "tr_id": "FHKST01010100",  # 주식현재가 시세 조회 TR
        "custtype": "P"
    }

    # 3. API 요청 (inquire-price)
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": TARGET_CODE
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res_json = res.json()

        if res_json['rt_cd'] != '0':
            print(f"❌ API 호출 실패: {res_json['msg1']}")
            return

        output = res_json['output']

        # 4. 데이터 파싱 (OHLCV)
        # API는 문자열로 주므로 int/float 변환 필수
        stck_prpr = int(output['stck_prpr'])  # 현재가(종가)
        stck_oprc = int(output['stck_oprc'])  # 시가
        stck_hgpr = int(output['stck_hgpr'])  # 고가
        stck_lwpr = int(output['stck_lwpr'])  # 저가
        acml_vol  = int(output['acml_vol'])   # 거래량

        print(f"📊 [OHLCV 데이터]")
        print(f" - 현재가(Close): {stck_prpr:,}원")
        print(f" - 시  가(Open) : {stck_oprc:,}원")
        print(f" - 고  가(High) : {stck_hgpr:,}원")
        print(f" - 저  가(Low)  : {stck_lwpr:,}원")
        print(f" - 거래량(Vol)  : {acml_vol:,}주")
        
        # 캔들 상태 확인
        is_yangbong = stck_prpr >= stck_oprc
        candle_color = "🔴양봉" if is_yangbong else "🔵음봉"
        print(f" - 캔들 타입    : {candle_color}")

        print("-" * 30)

        # 5. 윗꼬리 계산 (봇 로직과 동일)
        # 공식: (고가 - 몸통상단) / (고가 - 저가)
        wick_ratio = 0.0
        
        # 분모(전체 길이)가 0이 아닐 때만 계산
        if stck_hgpr > stck_lwpr:
            # 몸통 상단 값 구하기 (양봉이면 현재가, 음봉이면 시가)
            body_top = max(stck_prpr, stck_oprc)
            
            # 윗꼬리 길이
            upper_wick = stck_hgpr - body_top
            
            # 전체 캔들 길이
            total_candle_len = stck_hgpr - stck_lwpr
            
            # 비율 계산
            wick_ratio = upper_wick / total_candle_len
            
            print(f"📐 [윗꼬리 계산]")
            print(f" - 윗꼬리 길이 : {upper_wick} (고가 {stck_hgpr} - 몸통상단 {body_top})")
            print(f" - 캔들 전체   : {total_candle_len} (고가 {stck_hgpr} - 저가 {stck_lwpr})")
            print(f" - 계산 식     : {upper_wick} / {total_candle_len}")
        else:
            print("📐 [윗꼬리 계산] 고가와 저가가 같아 계산 불가 (0)")

        # 6. 결과 출력
        print("-" * 30)
        print(f"✅ 최종 윗꼬리 비율: {wick_ratio:.4f} ({wick_ratio*100:.2f}%)")
        
        # 봇 기준(0.3 미만) 통과 여부
        if wick_ratio < 0.3:
            print("👉 결과: [매수 대상] (윗꼬리가 30% 미만입니다)")
        else:
            print("👉 결과: [매수 제외] (윗꼬리가 너무 깁니다)")

    except Exception as e:
        print(f"❌ 에러 발생: {e}")

if __name__ == "__main__":
    check_hyundai_wick()