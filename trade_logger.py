# trade_logger.py
import csv
import os
import datetime

# 📂 로그 저장 경로 설정
LOG_DIR = "logs"
BUY_LOG_FILE = f"{LOG_DIR}/buy_log.csv"
SELL_LOG_FILE = f"{LOG_DIR}/sell_log.csv"

def initialize_logs():
    """
    로그 파일이 존재하는지 확인하고, 없을 경우에만 새로 생성하여 헤더를 작성합니다.
    (이미 존재하면 건너뛰므로 덮어쓰지 않습니다.)
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    # 1. 매수 로그 확인
    if not os.path.exists(BUY_LOG_FILE):
        # 파일이 없을 때만 'w'(쓰기) 모드로 열어서 헤더 작성
        with open(BUY_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Time", "Code", "Name", "Strategy", "Level", 
                "Buy_Price", "Qty", "Program_Amt_Entry", 
                "Gap_Rate", "Leader_Name"
            ])
        print(f"📁 [Log] 신규 매수 로그 파일 생성: {BUY_LOG_FILE}")

    # 2. 매도 로그 확인
    if not os.path.exists(SELL_LOG_FILE):
        # 파일이 없을 때만 'w'(쓰기) 모드로 열어서 헤더 작성
        with open(SELL_LOG_FILE, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Time", "Code", "Name", "Strategy", "Reason",
                "Buy_Price", "Sell_Price", "Qty", "Profit_Rate(%)", "Hold_Min(분)",
                "Max_Price_During_Hold", "Min_Price_During_Hold",
                "Entry_PG_Amt", "Max_PG_Amt_During_Hold",
                "Exit_PG_Amt"
            ])
        print(f"📁 [Log] 신규 매도 로그 파일 생성: {SELL_LOG_FILE}")

def log_buy(data):
    """매수 데이터 이어쓰기 (Append)"""
    # 혹시 파일이 삭제되었을 경우를 대비해 헤더 체크
    initialize_logs()
    
    try:
        # 'a' 모드(append)는 기존 내용을 유지하고 끝에 추가합니다.
        with open(BUY_LOG_FILE, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                data.get('code'),
                data.get('name'),
                data.get('strategy'),
                data.get('level'),
                data.get('price'),
                data.get('qty'),
                data.get('pg_amt'),
                data.get('gap'),
                data.get('leader')
            ])
    except Exception as e:
        print(f"❌ [Log Error] Buy Log Failed: {e}")

def log_sell(data):
    """매도 데이터 이어쓰기 (Append)"""
    initialize_logs()
    
    try:
        # 'a' 모드(append)로 열기
        with open(SELL_LOG_FILE, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            
            # 수익률 계산 (안전장치 포함)
            buy_p = float(data.get('buy_price', 0))
            sell_p = float(data.get('sell_price', 0))
            profit_rate = ((sell_p - buy_p) / buy_p * 100) if buy_p > 0 else 0

            writer.writerow([
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                data.get('code'),
                data.get('name'),
                data.get('strategy'),
                data.get('reason'),
                buy_p,
                sell_p,
                data.get('qty'),
                round(profit_rate, 2),
                data.get('hold_time_min'),
                data.get('max_price'),  
                data.get('min_price'),  
                data.get('entry_pg'),   
                data.get('max_pg'),     
                data.get('exit_pg')     
            ])
    except Exception as e:
        print(f"❌ [Log Error] Sell Log Failed: {e}")

