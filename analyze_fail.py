import time
import sys

# 📂 기존 봇의 설정을 그대로 가져옵니다
from jongga_bot import KisApi, BotConfig
import config

# =========================================================
# 🕵️‍♂️ [분석 도구] 왜 매수가 안 되었는지 검증
# =========================================================
def analyze_rejection_reasons():
    print("🕵️‍♂️ [진단 시작] 조건검색 종목 정밀 분석 중...\n")
    
    # 1. API 연결
    api = KisApi()
    
    # 2. 조건검색식 결과 가져오기 (봇과 동일하게 'jongga' 검색)
    target_cond = "jongga"
    candidates = api.fetch_condition_stocks(target_cond)
    
    if not candidates:
        print(f"⚠️ [1차 원인] 조건검색식 '{target_cond}' 결과가 0개입니다.")
        print("   -> HTS/MTS에서 조건식이 정상 동작하는지, 종목이 뜨는지 확인하세요.")
        return

    print(f"🔎 조건검색 발견 종목 수: {len(candidates)}개")
    print("="*60)
    print(f"{'종목명':<10} | {'현재가':<8} | {'등락률':<6} | {'상태':<5} | {'상세 사유'}")
    print("="*60)

    # 3. 한 종목씩 봇의 기준(BotConfig)으로 검사
    pass_list = []
    
    for stock in candidates:
        code = stock['stck_shrn_iscd']
        name = stock['hts_kor_isnm']
        
        # -------------------------------------------------
        # [Filter 1] 이름 필터 (ETF, 스팩 등)
        # -------------------------------------------------
        ban_keywords = ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]
        if any(x in name for x in ban_keywords) or name.endswith("우"):
            print(f"{name:<10} | {'-':<8} | {'-':<6} | ❌ | [이름 제외] ETF/스팩/우선주 등")
            continue
        
        if code in config.EXCLUDE_LIST:
            print(f"{name:<10} | {'-':<8} | {'-':<6} | ❌ | [설정 제외] config.EXCLUDE_LIST 포함")
            continue

        # 상세 데이터 조회 (OHLCV + 수급)
        info = api.fetch_price_detail(code, name)
        if not info:
            print(f"{name:<10} | {'ERROR':<8} | {'-':<6} | ❌ | API 데이터 조회 실패")
            continue

        price = info['price']
        rate = info['rate']
        
        # -------------------------------------------------
        # [Filter 2] 등락률 (BotConfig.MIN_RATE: 3.0% 이상)
        # -------------------------------------------------
        if rate < BotConfig.MIN_RATE:
            print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ❌ | [등락률 미달] 기준 {BotConfig.MIN_RATE}% > 실제 {rate:.2f}%")
            continue

        # -------------------------------------------------
        # [Filter 3] 양봉 여부 (시가 <= 종가)
        # -------------------------------------------------
        if price <= info['open']:
            print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ❌ | [음봉/도지] 시가({info['open']}) >= 종가({price})")
            continue

        # -------------------------------------------------
        # [Filter 4] 윗꼬리 (BotConfig.MAX_WICK: 0.3 미만)
        # -------------------------------------------------
        if info['wick_ratio'] >= BotConfig.MAX_WICK:
            print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ❌ | [윗꼬리 과다] 기준 {BotConfig.MAX_WICK} <= 실제 {info['wick_ratio']:.2f}")
            continue

        # -------------------------------------------------
        # [Filter 5] 상한가 제외
        # -------------------------------------------------
        if price >= info['max_price']:
            print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ❌ | [상한가] 매수 불가 (이미 잠김)")
            continue

        # -------------------------------------------------
        # [Filter 6] 프로그램 수급 (양수여야 함)
        # -------------------------------------------------
        pg_amt = info['program_buy'] * price
        if pg_amt <= 0:
            print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ❌ | [수급 이탈] 프로그램 순매수 음수/0 ({info['program_buy']:,}주)")
            continue

        # ✅ 모든 조건 통과
        print(f"{name:<10} | {price:<8,} | {rate:+.2f}% | ✅ | [조건 통과] 매수 후보 등록 가능")
        
        # 거래대금 계산 (정렬용)
        trade_amt = price * info['acml_vol']
        pass_list.append({
            'name': name,
            'trade_amt': trade_amt
        })
        
        time.sleep(0.1) # API 부하 방지

    print("="*60)
    
    # 4. 최종 결과 요약
    if pass_list:
        pass_list.sort(key=lambda x: x['trade_amt'], reverse=True)
        print(f"🎉 최종 매수 대상 ({min(len(pass_list), BotConfig.MAX_STOCKS)}개 선정 예정):")
        for i, item in enumerate(pass_list[:BotConfig.MAX_STOCKS]):
            print(f"   {i+1}순위: {item['name']} (거래대금 {item['trade_amt']/100000000:.1f}억)")
    else:
        print("❄️ 최종 결과: 매수 조건을 만족하는 종목이 '하나도' 없습니다.")
        print("   (팁: 조건검색식은 통과했으나, 봇의 2차 필터(윗꼬리, 수급 등)에서 모두 탈락함)")

if __name__ == "__main__":
    analyze_rejection_reasons()

