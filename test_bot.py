import jongga_bot
import time
import sys

# ==============================================================================
# 🚀 실전 데이터 테스트
# 1. 실제 API를 통해 'jongga' 조건검색식을 조회합니다.
# 2. 실제 시세와 프로그램 수급, 윗꼬리 비율을 계산합니다.
# 3. 로직대로(윗꼬리 작은 순) 정렬되는지 확인합니다.
# 4. 실제 내 계좌 잔고를 조회하여 70% 자금 배분이 얼마인지 계산합니다.
# ==============================================================================

def test_real_execution():
    print("🔥 [REAL] 실전 데이터 기반 로직 검증 시작")
    print("=" * 60)
    
    # 1. 봇 인스턴스 생성 (이 과정에서 API 토큰 발급 및 로그인 수행)
    try:
        print("🔑 API 로그인을 시도합니다...")
        bot = jongga_bot.TradingBot()
        print("✅ 로그인 성공! 봇 인스턴스 생성됨.")
    except Exception as e:
        print(f"❌ 초기화 실패: {e}")
        sys.exit(1)

    # 2. 종목 선정 로직 실행 (실제 API 통신 발생)
    print("\n📡 한국투자증권 서버에서 'jongga' 조건식 결과를 가져오는 중...")
    print("   (종목이 많으면 상세조회 하느라 시간이 좀 걸릴 수 있습니다)")
    
    start_time = time.time()
    targets = bot.get_jongga_targets()
    end_time = time.time()
    
    # 3. 결과 출력
    print("\n" + "=" * 60)
    print(f"🎯 [최종 선정 결과] 총 {len(targets)}개 (소요시간: {end_time - start_time:.1f}초)")
    print("=" * 60)
    
    if not targets:
        print("⚠️ 검색된 종목이 없습니다.")
        print("   (가능성 1: 장 마감 후 조건식이 초기화됨)")
        print("   (가능성 2: 오늘 조건(3%상승, 100억수급 등)을 만족하는 종목이 없음)")
    else:
        print(f"{'순위':<4} | {'종목명':<10} | {'현재가':<8} | {'윗꼬리(%)':<10} | {'거래대금(억)':<10}")
        print("-" * 60)
        
        for i, stock in enumerate(targets):
            # 윗꼬리 비율 퍼센트 변환
            wick_pct = stock['wick_ratio'] * 100
            # 거래대금 억 단위 변환
            trade_amt_ok = stock['trade_amt'] / 100000000
            
            print(f"{i+1:<4} | {stock['name']:<10} | {stock['price']:<8,} | {wick_pct:<9.2f}% | {trade_amt_ok:<10,.1f}억")
            
    # 4. 자금 배분 계산 검증 (실제 잔고 조회)
    print("\n" + "=" * 60)
    print("💰 [자금 배분 시뮬레이션]")
    print("=" * 60)
    
    balance = bot.api.fetch_balance()
    
    if balance > 0:
        # 실제 로직과 동일한 계산 (70% 예산 / 3종목)
        invest_ratio = 0.70
        max_stocks = jongga_bot.BotConfig.MAX_STOCKS
        
        total_budget = int(balance * invest_ratio)
        per_stock_budget = int(total_budget / max_stocks)
        
        print(f"1️⃣  내 계좌 순자산 : {balance:,} 원")
        print(f"2️⃣  투자 예산 (70%): {total_budget:,} 원")
        print(f"3️⃣  종목당 할당액  : {per_stock_budget:,} 원 (3등분)")
        
        if targets:
            print(f"\n[실제 주문 예정 수량 - 1순위 '{targets[0]['name']}' 기준]")
            # 1매도호가가 필요한데, 여기 리스트엔 없으므로 현재가로 대략 계산
            est_qty = int(per_stock_budget / targets[0]['price'])
            print(f"👉 약 {est_qty:,}주 매수 (지정가 1호가 기준 시 약간 다를 수 있음)")
            
    else:
        print("❌ 잔고 조회 실패 또는 잔고 0원")

    print("\n✅ 테스트 완료.")

if __name__ == "__main__":
    test_real_execution()