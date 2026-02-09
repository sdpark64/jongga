import time
import sys
import logging
from jongga_bot import KisApi, BotConfig  # 기존 봇 파일에서 클래스 임포트

# ==========================================
# ⚙️ 검증 설정 (사용자가 요청한 기준 강제 적용)
# ==========================================
TEST_MIN_RATE = 10.0      # 시가 대비 상승률 10% 이상
TEST_MIN_WICK = 0.1       # 윗꼬리 10% 이상
TEST_MAX_WICK = 0.3       # 윗꼬리 30% 이하

def verify_selection_logic():
    print("=" * 80)
    print(f"🚀 [검증 시작] 종목 선정 로직 시뮬레이션")
    print(f"   👉 기준: 시가대비상승 {TEST_MIN_RATE}%↑ / 윗꼬리 {TEST_MIN_WICK}~{TEST_MAX_WICK}")
    print("=" * 80)

    api = KisApi()
    
    # 1. 조건검색식 종목 가져오기
    print("📡 [1단계] 조건검색식 'jongga' 조회 중...")
    candidates = api.fetch_condition_stocks("jongga")
    
    if not candidates:
        print("❌ 조건검색 결과가 없습니다. (장 시간이 아니거나 조건식 문제)")
        return

    print(f"   ✅ 검색된 후보 개수: {len(candidates)}개\n")

    passed_stocks = []

    # 2. 상세 분석 및 필터링
    print(f"📡 [2단계] 후보 종목 상세 분석 시작...")
    print("-" * 80)
    print(f"{'종목명':<10} | {'현재가':>8} | {'시가대비%':>8} | {'윗꼬리%':>6} | {'거래대금(추정)':>15} | {'판정'}")
    print("-" * 80)

    for stock in candidates:
        code = stock['stck_shrn_iscd']
        name = stock['hts_kor_isnm']
        
        # 제외 종목 필터 (간략화)
        if name.endswith("우") or "스팩" in name: 
            continue

        info = api.fetch_price_detail(code, name)
        if not info: continue

        # ------------------------------------------------------------------
        # 🔍 검증 로직 (봇 로직과 동일하게 구현)
        # ------------------------------------------------------------------
        
        # [데이터 추출]
        current_price = info['price']
        open_price = info['open']
        high_price = info['high']
        low_price = info['low']
        
        # [계산 1] 시가 대비 상승률
        if open_price > 0:
            rate_from_open = ((current_price - open_price) / open_price) * 100
        else:
            rate_from_open = 0.0

        # [계산 2] 윗꼬리 비율 (고가-저가 기준)
        wick_ratio = 0.0
        if high_price > low_price:
            upper_wick = high_price - max(current_price, open_price)
            total_candle = high_price - low_price
            wick_ratio = upper_wick / total_candle

        # [계산 3] 거래대금 (현재가 * 거래량 추정치)
        # ※ KisApi 수정 없이 현재 코드를 쓴다고 했으므로 info['acml_vol'] 사용
        est_trade_amt = current_price * info['acml_vol']

        # ------------------------------------------------------------------
        # 🛑 필터링 판정
        # ------------------------------------------------------------------
        status = "✅통과"
        fail_reason = ""

        # 1. 시가 대비 10% 상승 미만 탈락
        if rate_from_open < TEST_MIN_RATE:
            status = "❌탈락"
            fail_reason = f"(상승률부족 {rate_from_open:.1f}%)"
        
        # 2. 음봉 탈락
        elif current_price <= open_price:
            status = "❌탈락"
            fail_reason = "(음봉)"
            
        # 3. 윗꼬리 범위(0.1 ~ 0.3) 벗어나면 탈락
        elif not (TEST_MIN_WICK <= wick_ratio <= TEST_MAX_WICK):
            status = "❌탈락"
            fail_reason = f"(윗꼬리 {wick_ratio:.2f})"

        # 출력
        print(f"{name:<10} | {current_price:>8,} | {rate_from_open:>8.1f}% | {wick_ratio:>6.2f} | {est_trade_amt:>15,} | {status} {fail_reason}")

        if status == "✅통과":
            passed_stocks.append({
                'name': name,
                'price': current_price,
                'rate': rate_from_open,
                'wick': wick_ratio,
                'trade_amt': est_trade_amt
            })
        
        time.sleep(0.1) # API 부하 방지

    # 3. 최종 순위 선정
    print("-" * 80)
    print(f"📡 [3단계] 최종 선정 (거래대금 순 정렬)")
    
    if passed_stocks:
        # 거래대금 내림차순 정렬
        passed_stocks.sort(key=lambda x: x['trade_amt'], reverse=True)
        
        print(f"🏆 [최종 1위] {passed_stocks[0]['name']}")
        print(f"   - 거래대금: {passed_stocks[0]['trade_amt']:,}원")
        print(f"   - 상승률: {passed_stocks[0]['rate']:.2f}%")
        print(f"   - 윗꼬리: {passed_stocks[0]['wick']:.2f}")
        
        if len(passed_stocks) > 1:
            print(f"\n🥈 [예비 2위] {passed_stocks[1]['name']} ({passed_stocks[1]['trade_amt']:,}원)")
            print(f"🥉 [예비 3위] {passed_stocks[2]['name']} ({passed_stocks[2]['trade_amt']:,}원)")
    else:
        print("😭 조건에 맞는 종목이 하나도 없습니다.")

if __name__ == "__main__":
    verify_selection_logic()
