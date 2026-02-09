import jongga_bot  # 원본 봇 파일 임포트
import requests
import config

# ==============================================================================
# 🛠️ 수정된 잔고 조회 함수 (순자산 우선 조회 + 타임아웃 30초)
# ==============================================================================
def fixed_fetch_balance(self):
    print("🔄 [API 요청 중] 한국투자증권 서버에 잔고를 조회합니다...")
    
    base_url = jongga_bot.BotConfig.URL_REAL if jongga_bot.MODE == "REAL" else jongga_bot.BotConfig.URL_MOCK
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
    headers = self.get_headers(jongga_bot.BotConfig.TR_ID["balance"], type="TRADE")
    acc_no = config.REAL_ACC_NO if jongga_bot.MODE == "REAL" else config.MOCK_ACC_NO
    
    params = {
        "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
        "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
    }
    
    try:
        # ✅ 타임아웃 30초 설정
        res = requests.get(url, headers=headers, params=params, timeout=30).json()
        
        if res['rt_cd'] == '0':
            out2 = res['output2'][0]
            
            # ✅ 데이터 추출
            nass_amt = self._safe_int(out2.get('nass_amt', 0))       # 순자산 (주식+현금)
            dnca_tot_amt = self._safe_int(out2.get('dnca_tot_amt', 0)) # 예수금 (현금)
            tot_evlu_amt = self._safe_int(out2.get('tot_evlu_amt', 0)) # 주식평가액
            
            print("\n" + "="*50)
            print(f"📊 [잔고 조회 결과 - {jongga_bot.MODE} 모드]")
            print("="*50)
            print(f"1️⃣  순자산금액 (nass_amt)   : {nass_amt:>15,} 원 (봇 사용 기준)")
            print(f"2️⃣  예수금총액 (dnca_tot_amt): {dnca_tot_amt:>15,} 원")
            print(f"3️⃣  주식평가액 (tot_evlu_amt): {tot_evlu_amt:>15,} 원")
            print("="*50)
            
            if nass_amt > 0:
                print(f"✅ 결과: 정상 (순자산 {nass_amt:,}원으로 인식됨)")
                return nass_amt
            elif (dnca_tot_amt + tot_evlu_amt) > 0:
                hap = dnca_tot_amt + tot_evlu_amt
                print(f"⚠️ 결과: 순자산 0원 오류 -> 예수금+평가액 합산({hap:,}원)으로 대체 성공")
                return hap
            else:
                print("❌ 결과: 잔고가 0원입니다. (실제 잔고가 없는지 확인 필요)")
                return 0
        else:
            print(f"❌ API 요청 실패: {res['msg1']} (코드: {res['rt_cd']})")
            return 0
            
    except Exception as e:
        print(f"❌ 에러 발생: {e}")
    return 0

# ==============================================================================
# 🚀 실행부
# ==============================================================================
if __name__ == "__main__":
    # 1. 원본 봇의 함수를 수정된 함수로 교체 (Monkey Patch)
    jongga_bot.KisApi.fetch_balance = fixed_fetch_balance
    
    # 2. API 객체 생성
    api = jongga_bot.KisApi()
    
    # 3. 잔고 조회 실행 (단 1회)
    balance = api.fetch_balance()

