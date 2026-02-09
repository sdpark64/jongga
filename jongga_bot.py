import requests
import json
import time
import datetime
import boto3
import threading
import logging
import logging.handlers
import sys

# 📂 사용자 파일 임포트
import config
import token_manager
import telegram_notifier
import trade_logger # 👈 추가

# ==============================================================================
# 📝 [로그 시스템 설정] print를 자동으로 로그 파일에 기록하기
# ==============================================================================
def setup_logging():
    # 1. 로거 생성
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # 포맷 설정 (시간 - 레벨 - 메시지)
    formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 2. 파일 핸들러 (output.log에 기록, 10MB마다 새로운 파일 생성, 최대 5개 보관)
    #    -> 이렇게 하면 로그 파일이 무한히 커지는 것을 막아줍니다.
    file_handler = logging.handlers.RotatingFileHandler(
        'output.log', maxBytes=10*1024*1024, backupCount=5, encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 3. 콘솔 핸들러 (화면에도 출력)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    return logger

# 로거 실행
logger = setup_logging()

# 🔥 [핵심 마법] 기존 print 함수를 logger.info로 덮어쓰기 (오버라이딩)
# 이제 코드에서 print("안녕") 하면 -> 로그 파일에 시간과 함께 저장됩니다.
original_print = print
def print(*args, **kwargs):
    # print의 내용을 하나의 문자열로 합침
    msg = " ".join(map(str, args))
    # 로그에 기록 (자동으로 파일+화면 출력)
    logger.info(msg)

# ==============================================================================
# 🕹️ [모드 설정]
# ==============================================================================
MODE = "REAL"   # 실전투자
# MODE = "MOCK"   # 모의투자 (기본값)

if MODE == "REAL":
    config.TELEGRAM_BOT_TOKEN = config.REAL_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.REAL_TELEGRAM_CHAT_ID
else:
    config.TELEGRAM_BOT_TOKEN = config.MOCK_TELEGRAM_BOT_TOKEN
    config.TELEGRAM_CHAT_ID = config.MOCK_TELEGRAM_CHAT_ID

# ==============================================================================
# 1. 봇 설정 (BotConfig)
# ==============================================================================
class BotConfig:
    URL_REAL = "https://openapi.koreainvestment.com:9443"
    URL_MOCK = "https://openapivts.koreainvestment.com:29443"
    
    DELAY_REAL = 0.06
    DELAY_MOCK = 0.60 

    if MODE == "MOCK":
        TR_ID = { "balance": "VTTC8434R", "buy": "VTTC0802U", "sell": "VTTC0801U" }
    else: 
        TR_ID = { "balance": "TTTC8434R", "buy": "TTTC0802U", "sell": "TTTC0801U" }
        
    PROBE_STOCK_CODE = "005930" 
    
# 💰 [자금 및 슬롯 관리]
    MAX_STOCKS = 3        # 최대 매수 종목 수
    SPLIT_BUY_CNT = 4     # 분할 매수 횟수 (3분할)
    
    # 📊 [종목 선정 기준]
    MIN_RATE = 5.0        # 등락률 3% 이상
    MIN_WICK = 0.00        # 윗꼬리 최소 10%
    MAX_WICK = 0.3        # 윗꼬리 최대 30%
    
    # 🛡️ [매도/청산 조건]
    STOP_LOSS_RATE = -0.02      # 손절 -2%
    PARTIAL_PROFIT_RATE = 0.01  # 절반 익절 +2%
    PARTIAL_SELL_RATIO = 0.5    # 절반 매도
    
    TS_TRIGGER_RATE = 0.02      # 트레일링 스탑 발동 +4%
    TS_STOP_GAP = 0.01          # 고점 대비 2% 하락 시 매도
    
    GAP_DOWN_PANIC = -0.02      # 시초가 갭하락 기준 (-2% 이하시 시장가 손절)

    ASSET_WEIGHT = 0.7         # 투자비중

# ==============================================================================
# 2. KIS API 래퍼
# ==============================================================================
class KisApi:
    def __init__(self):
        self.base_headers_real = {
            "content-type": "application/json",
            "appKey": config.REAL_API_KEY,
            "appSecret": config.REAL_API_SECRET
        }
        
        if MODE == "REAL":
            self.base_headers_trade = self.base_headers_real.copy()
        else:
            self.base_headers_trade = {
                "content-type": "application/json",
                "appKey": config.MOCK_API_KEY,
                "appSecret": config.MOCK_API_SECRET
            }
        
        self.condition_seq_map = {}

        self.session = requests.Session()
        self.session.mount('https://', requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10))

    def _throttle(self, type="DATA"):
        if type == "DATA":
            time.sleep(BotConfig.DELAY_REAL)
        else:
            if MODE == "REAL":
                time.sleep(BotConfig.DELAY_REAL)
            else:
                time.sleep(BotConfig.DELAY_MOCK)

    def get_headers(self, tr_id, type="DATA"):
        self._throttle(type)
        if type == "DATA":
            token = token_manager.get_access_token("REAL")
            h = self.base_headers_real.copy()
            h["authorization"] = f"Bearer {token}"
            h["custtype"] = "P"
        else: 
            target = "REAL" if MODE == "REAL" else "MOCK"
            token = token_manager.get_access_token(target)
            h = self.base_headers_trade.copy()
            h["authorization"] = f"Bearer {token}"
        h["tr_id"] = tr_id
        return h

    def fetch_hashkey(self, body_dict):
        try:
            url = f"{BotConfig.URL_REAL}/uapi/hashkey"
            headers = {
                "content-type": "application/json",
                "appKey": config.REAL_API_KEY,
                "appSecret": config.REAL_API_SECRET
            }
            res = requests.post(url, headers=headers, json=body_dict, timeout=5)
            if res.status_code == 200:
                return res.json()['HASH']
            else:
                return None
        except Exception as e:
            print(f"❌ HashKey 에러: {e}")
            return None

    def _safe_int(self, val):
        try:
            if val is None: return 0
            s_val = str(val).strip().replace(',', '')
            if not s_val: return 0
            return int(float(s_val))
        except:
            return 0

    def check_holiday(self, date_str):
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/chk-holiday"
        headers = self.get_headers("CTCA0903R", type="DATA")
        params = {"BASS_DT": date_str, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                for day in res['output']:
                    if day['bass_dt'] == date_str:
                        return day['opnd_yn'] == 'N'
            return False
        except: return False

    def fetch_balance(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.get_headers(BotConfig.TR_ID["balance"], type="TRADE")
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            # [수정 1] 타임아웃 5초 -> 30초로 변경 (안정성 확보)
            res = requests.get(url, headers=headers, params=params, timeout=30).json()
            
            if res['rt_cd'] == '0':
                output2 = res['output2'][0]
                
                # [수정 2] 순자산(nass_amt) 우선 조회 (현금 + 주식평가금 포함)
                nass_amt = self._safe_int(output2.get('nass_amt', 0))
                dnca_tot_amt = self._safe_int(output2.get('dnca_tot_amt', 0)) # 예수금
                tot_evlu_amt = self._safe_int(output2.get('tot_evlu_amt', 0)) # 주식평가
                
                # 확인용 로그 출력
                print(f"💰 [잔고상세] 순자산: {nass_amt:,} | 예수금: {dnca_tot_amt:,} | 평가액: {tot_evlu_amt:,}")
                
                if nass_amt > 0:
                    return nass_amt
                else:
                    return dnca_tot_amt + tot_evlu_amt
        except Exception as e:
            print(f"❌ 잔고 조회 실패: {e}")
        return 0

    def fetch_my_stock_list(self):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self.get_headers(BotConfig.TR_ID["balance"], type="TRADE")
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        params = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "AFHR_FLPR_YN": "N", "OFL_YN": "N", "INQR_DVSN": "02", "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N", "FNCG_AMT_AUTO_RDPT_YN": "N", "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "", "CTX_AREA_NK100": ""
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                my_stocks = {}
                for stock in res['output1']:
                    code = stock['pdno']
                    qty = int(stock['hldg_qty'])              # 보유 수량
                    ord_psbl = int(stock['ord_psbl_qty'])     # 주문 가능 수량
                    
                    if qty > 0:
                        my_stocks[code] = {
                            'qty': qty,
                            'ord_psbl': ord_psbl, # 🔥 중요: 미체결 주문 있으면 이 수량이 줄어듦
                            'name': stock['prdt_name'],
                            'price': float(stock['pchs_avg_pric']), # 🔥 평단가 기준
                            'current_price': float(stock['prpr'])
                        }
                return my_stocks
            else:
                return None
        except Exception as e:
            print(f"❌ 잔고 조회 실패: {e}")
            return None

    def get_condition_seq(self, cond_name):
        if cond_name in self.condition_seq_map:
            return self.condition_seq_map[cond_name]
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-title"
        headers = self.get_headers("HHKST03900300", type="DATA")
        params = { "user_id": config.HTS_ID }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                for item in res['output2']:
                    if item['grp_nm'] == cond_name:
                        self.condition_seq_map[cond_name] = item['seq']
                        print(f"✅ 조건검색식 '{cond_name}' 매핑 완료 (Seq: {item['seq']})")
                        return item['seq']
        except Exception as e:
            print(f"❌ 조건식 목록 조회 실패: {e}")
        return None

    def fetch_condition_stocks(self, cond_name):
        seq = self.get_condition_seq(cond_name)
        if not seq: return []
        url = f"{BotConfig.URL_REAL}/uapi/domestic-stock/v1/quotations/psearch-result"
        headers = self.get_headers("HHKST03900400", type="DATA")
        params = { "user_id": config.HTS_ID, "seq": seq }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=5).json()
            if res['rt_cd'] == '0':
                raw_list = res['output2']
                mapped_list = []
                for item in raw_list:
                    price_val = item.get('price', item.get('stck_prpr', 0))
                    vol_val = item.get('acml_vol', 0)
                    mapped_list.append({
                        'stck_shrn_iscd': item['code'],
                        'hts_kor_isnm': item['name'],
                        'prdy_ctrt': float(item.get('chgrate', 0.0)),
                        'price': self._safe_int(price_val),
                        'vol': self._safe_int(vol_val)
                    })
                return mapped_list
        except Exception as e:
            print(f"❌ 조건검색 '{cond_name}' 조회 실패: {e}")
        return []

    def fetch_price_detail(self, code, name_from_rank=None, lite=False):
        self._throttle() 
        url_price = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
        headers_price = self.get_headers("FHKST01010100", type="DATA")
        params_price = { "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code }

        try:
            # Timeout 10초
            res1 = self.session.get(url_price, headers=headers_price, params=params_price, timeout=10).json()
            if res1['rt_cd'] != '0': return None 
            
            out1 = res1['output']
            final_name = out1.get('rprs_mant_kor_name', out1.get('hts_kor_isnm', name_from_rank))
            if final_name is None: final_name = "이름없음"
            
            program_buy = int(out1.get('pgtr_ntby_qty', 0)) 
            current_price = int(out1.get('stck_prpr', 0))
            
            url_hoga = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
            headers_hoga = self.get_headers("FHKST01010200", type="DATA")
            params_hoga = { "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code }
            
            res2 = self.session.get(url_hoga, headers=headers_hoga, params=params_hoga, timeout=10).json()
            
            ask_rsqn1 = 0
            bid_rsqn1 = 0
            total_ask = 0
            total_bid = 0
            ask_price = current_price # 기본값
            
            if res2['rt_cd'] == '0':
                out2 = res2['output1']
                ask_rsqn1 = int(out2.get('askp_rsqn1', 0)) 
                bid_rsqn1 = int(out2.get('bidp_rsqn1', 0)) 
                total_ask = int(out2.get('total_askp_rsqn', 0)) 
                total_bid = int(out2.get('total_bidp_rsqn', 0))
                
                # ✅ [추가] 1매도호가 가져오기
                ask_price = int(out2.get('askp1', current_price))

            data = {
                'code': code, 
                'name': final_name,
                'price': current_price,
                'ask_price': ask_price, # ✅ 데이터에 추가
                'open': int(out1.get('stck_oprc', 0)),
                'high': int(out1.get('stck_hgpr', 0)),
                'low': int(out1.get('stck_lwpr', 0)),
                'max_price': int(out1.get('stck_mxpr', 0)),
                'rate': float(out1.get('prdy_ctrt', 0.0)),
                'program_buy': program_buy, 
                'total_ask': total_ask,
                'total_bid': total_bid,
                'acml_vol': int(out1.get('acml_vol', 0)),
                'ask_rsqn1': ask_rsqn1,     
                'bid_rsqn1': bid_rsqn1,
                'bid_ask_ratio': 0.0,
                'wick_ratio': 0.0
            }
            
            if data['total_ask'] > 0:
                data['bid_ask_ratio'] = (data['total_bid'] / data['total_ask']) * 100
            elif data['total_bid'] > 0:
                data['bid_ask_ratio'] = 999.0
            
            wick_ratio = 0.0
            if data['high'] > data['open']:
                upper_wick = data['high'] - max(data['price'], data['open'])
                total_candle = data['high'] - data['open']
                wick_ratio = upper_wick / total_candle
            data['wick_ratio'] = wick_ratio

            return data
                
        except Exception:
            pass
        return None

    # ✅ [수정] price 인자 추가 (기본값 0)
    def send_order(self, code, quantity, is_buy=True, price=0):
        base_url = BotConfig.URL_REAL if MODE == "REAL" else BotConfig.URL_MOCK
        acc_no = config.REAL_ACC_NO if MODE == "REAL" else config.MOCK_ACC_NO
        tr_id = BotConfig.TR_ID["buy"] if is_buy else BotConfig.TR_ID["sell"]
        url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        headers = self.get_headers(tr_id, type="TRADE")
        
        # ✅ [수정] 가격이 있으면 지정가("00"), 없으면 시장가("01")
        ord_dvsn = "01"
        ord_unpr = "0"
        
        if price > 0:
            ord_dvsn = "00" # 지정가
            ord_unpr = str(price)

        body = {
            "CANO": acc_no[:8], "ACNT_PRDT_CD": acc_no[-2:],
            "PDNO": code, 
            "ORD_DVSN": ord_dvsn,  # 구분 코드 변경
            "ORD_QTY": str(quantity), 
            "ORD_UNPR": ord_unpr   # 가격 설정
        }
        
        if MODE == "REAL":
            hashkey = self.fetch_hashkey(body)
            if hashkey:
                headers["hashkey"] = hashkey
            else:
                return {'rt_cd': '9999', 'msg1': 'HashKey Generation Failed'}

        try:
            res = requests.post(url, headers=headers, json=body, timeout=30).json()
            return res
        except Exception as e:
            print(f"❌ 주문 전송 실패: {e}")
            return {'rt_cd': '9999', 'msg1': 'Timeout/Error'}

# ==============================================================================
# 3. 봇 메인 로직 (TradingBot)
# ==============================================================================
class TradingBot:
    def __init__(self):
        self.api = KisApi()
        self.portfolio = {}
        
        # 🔒 [필수 수정] 스레드 락 초기화 (이게 없으면 에러 발생)
        self.lock = threading.Lock() 

        # 🚫 매매 제외 리스트 로드
        self.exclude_list = set(config.EXCLUDE_LIST)

        self.is_buy_active = True
        self.last_update_id = 0
        
        # 🚫 금일 매수 금지 (손절했거나 수동매도한 종목)
        self.today_blacklist = set()
        
        self.is_running = True
        self.market_open_time = None # 개장 여부 확인용
        self.last_summary_time = 0
        
        # 분할 매수 상태 관리 { 'code': 매수횟수(0~3) }
        self.buy_progress = {}

    # ------------------------------------------------------------------
    # 📉 [매도 로직] 아침 09:00 ~ 10:00 집중 감시
    # ------------------------------------------------------------------
    def monitor_portfolio(self):
        print("🕵️ 포트폴리오 감시 시작 (잔고 동기화 & 매도 대응)")

        while self.is_running:
            try:
                now = datetime.datetime.now()

                # ==============================================================
                # 🛑 [수정] 휴장일/주말 차단 로직 (이게 없으면 휴일에도 매도 시도함)
                # ==============================================================
                
                # 1. 주말(토/일)이면 스킵
                if now.weekday() >= 5:
                    time.sleep(60) # 1분 대기
                    continue

                # 2. 평일 법정 공휴일 체크 (08:00 ~ 15:30 사이만 체크하여 API 절약)
                # (매 루프마다 API를 호출하면 부하가 걸리므로, 
                #  10분(600초) 단위로 대기하거나, 이미 휴장임이 확인되면 길게 쉽니다.)
                if 8 <= now.hour <= 15:
                    if self.api.check_holiday(now.strftime("%Y%m%d")):
                        # print("⛔ [감시스레드] 오늘은 휴장일입니다. 감시 일시 중지.")
                        time.sleep(600) # 10분간 꿀잠
                        continue
                # ==============================================================
                
                # 1. 잔고 동기화 (사람 vs 봇 싸움 방지)
                real_holdings = self.api.fetch_my_stock_list()
                
                if real_holdings is not None:
                    # [A] 수동 매도 감지 (봇에는 있는데 실제로는 없거나 줄어든 경우)
                    for bot_code in list(self.portfolio.keys()):
                        if bot_code not in real_holdings:
                            print(f"🗑️ [수동청산 감지] {self.portfolio[bot_code]['name']} 목록에서 제거")
                            del self.portfolio[bot_code]
                            self.today_blacklist.add(bot_code) # 재매수 금지
                        # else:
                        #     bot_qty = self.portfolio[bot_code]['qty']
                        #     real_qty = real_holdings[bot_code]['qty']
                        #     if real_qty < bot_qty:
                        #         print(f"📉 [수동축소 감지] {self.portfolio[bot_code]['name']} 수량 조정 ({bot_qty}->{real_qty})")
                        #         self.portfolio[bot_code]['qty'] = real_qty
                        #         if real_qty == 0:
                        #             del self.portfolio[bot_code]
                        #             self.today_blacklist.add(bot_code)
                        else:
                            bot_qty = self.portfolio[bot_code]['qty']
                            real_qty = real_holdings[bot_code]['qty']
                            
                            # ✅ [수정] 수량이 다르다면(줄든 늘든) 무조건 실제 잔고로 동기화
                            if real_qty != bot_qty:
                                # 1. 수량이 늘어난 경우 (추가 매수 / 물타기)
                                if real_qty > bot_qty:
                                    print(f"📈 [수동증가 감지] {self.portfolio[bot_code]['name']} 수량/평단 갱신")
                                    
                                # 2. 수량이 줄어든 경우 (수동 매도)
                                elif real_qty < bot_qty:
                                    print(f"📉 [수동축소 감지] {self.portfolio[bot_code]['name']} 수량 갱신")
                                
                                # ---------------------------------------------------------
                                # 🔥 [핵심] 수량뿐만 아니라 '평단가'도 최신 잔고 기준으로 덮어쓰기
                                # ---------------------------------------------------------
                                self.portfolio[bot_code]['qty'] = real_qty
                                self.portfolio[bot_code]['buy_price'] = real_holdings[bot_code]['price'] 
                                # ---------------------------------------------------------
                                    
                                # 다 팔았으면 목록에서 삭제
                                if real_qty == 0:
                                    del self.portfolio[bot_code]
                                    self.today_blacklist.add(bot_code)

                    # [B] 신규 발견 (재실행 시 복구 or 수동 매수)
                    for real_code, info in real_holdings.items():
                        if real_code in self.exclude_list: continue # 장기보유주는 무시
                        
                        if real_code not in self.portfolio:
                            # 블랙리스트에 있으면(오늘 판거면) 봇이 다시 잡지 않음 (단, 재실행 직후는 예외일 수 있으나 안전을 위해 스킵)
                            if real_code in self.today_blacklist: continue
                            
                            self.portfolio[real_code] = {
                                'name': info['name'],
                                'qty': info['qty'],
                                'buy_price': info['price'], # 평단가
                                'max_profit_rate': 0.0,
                                'has_partial_sold': False,
                                'buy_time': datetime.datetime.now()
                            }
                            print(f"♻️ [관리등록] {info['name']} ({info['qty']}주, 평단 {info['price']:,.0f})")

                # 2. 매도 조건 검사
                now = datetime.datetime.now()
                if not self.portfolio:
                    time.sleep(1)
                    continue

                # ⏰ [타임컷] 10:00 전량 매도
                if now.hour == config.TIME_CUT_HOUR and now.minute >= 0:
                    self.liquidate_all_positions("⏰ 타임컷(10:00)")
                    time.sleep(60) # 중복 실행 방지
                    continue

                for code in list(self.portfolio.keys()):
                    info = self.portfolio[code]
                    
                    # 현재가 조회
                    market_info = self.api.fetch_price_detail(code, info['name'])
                    if not market_info: continue
                    
                    cur_price = market_info['price']
                    buy_price = info['buy_price']
                    profit_rate = (cur_price - buy_price) / buy_price

                    # ========================================================
                    # 🕒 [시간 체크] 장 초반 (09:00 ~ 09:03) 여부 확인
                    # ========================================================
                    is_early_morning = (now.hour == 9 and now.minute < 3)

                    # 🚨 [VI 감지] 09:01까지 거래량 없으면 VI로 간주하고 대기
                    if now.hour == 9 and now.minute <= 1:
                        if market_info['acml_vol'] == 0:
                            # print(f"⏳ [VI대기] {info['name']} 거래량 없음 (VI 발동중 추정)")
                            continue

                    # 📉 [갭하락 칼손절] 장 시작 직후 (-2% 이하 출발 시)
                    if now.hour == 9 and now.minute < 5:
                        if profit_rate <= BotConfig.GAP_DOWN_PANIC:
                            if is_early_morning:
                                # 3분간은 로그만 찍고 매도는 참음
                                if now.second % 10 == 0:
                                    print(f"🛡️ [손절유예] 갭하락({profit_rate*100:.2f}%) 발생했으나 09:03까지 대기")
                            else:
                                # 3분이 지났는데도 회복 못했으면 매도
                                self.sell_stock(code, f"📉갭하락 칼손절({profit_rate*100:.2f}%)")
                                continue

                    # 🛡️ 일반 손절 (-2%)
                    if profit_rate <= BotConfig.STOP_LOSS_RATE:
                        if is_early_morning:
                            if now.second % 10 == 0:
                                print(f"🛡️ [손절유예] 손절가({profit_rate*100:.2f}%) 도달했으나 09:03까지 대기")
                        else:
                            # 3분이 지났으면 얄짤없이 손절
                            self.sell_stock(code, f"💧손절({profit_rate*100:.2f}%)")
                            continue

                    # 💰 [익절] +2% 절반 매도
                    # if not info['has_partial_sold'] and profit_rate >= BotConfig.PARTIAL_PROFIT_RATE:
                    #     # 주문가능수량 확인 (사용자가 매도 걸어놨으면 스킵)
                    #     real_stock = real_holdings.get(code)
                    #     if real_stock and real_stock['ord_psbl'] >= (info['qty'] * 0.5):
                    #         sell_qty = int(info['qty'] * BotConfig.PARTIAL_SELL_RATIO)
                    #         if sell_qty > 0:
                    #             res = self.api.send_order(code, sell_qty, is_buy=False) # 시장가
                    #             if res['rt_cd'] == '0':
                    #                 self.portfolio[code]['qty'] -= sell_qty
                    #                 self.portfolio[code]['has_partial_sold'] = True
                    #                 telegram_notifier.send_telegram_message(f"💰 [부분익절] {info['name']} {sell_qty}주 수익실현")
                    #     else:
                    #         print(f"⚠️ [매도스킵] {info['name']} 주문가능수량 부족(미체결 주문 존재?)")

                    # 절반 익절 (+2%)
                    if not info['has_partial_sold'] and profit_rate >= BotConfig.PARTIAL_PROFIT_RATE:
                        # 주문가능수량 확인
                        real_stock = real_holdings.get(code)
                        
                        # ✅ [수정 포인트] 기준 수량을 info['qty'](봇기록) -> real_stock['qty'](실잔고)로 변경
                        if real_stock:
                            # 현재 실제 총 보유량
                            total_real_qty = real_stock['qty']
                            
                            # 실제 보유량의 50% 계산
                            sell_qty = int(total_real_qty * BotConfig.PARTIAL_SELL_RATIO)
                            
                            # 주문 가능 수량이 충분한지 체크
                            if real_stock['ord_psbl'] >= sell_qty and sell_qty > 0:
                                res = self.api.send_order(code, sell_qty, is_buy=False)
                                if res['rt_cd'] == '0':
                                    # 매도 성공 시 봇 내부 수량도 실제 잔고에서 차감된 값으로 최신화
                                    self.portfolio[code]['qty'] = total_real_qty - sell_qty
                                    self.portfolio[code]['has_partial_sold'] = True
                                    telegram_notifier.send_telegram_message(f"💰 [부분익절] {info['name']} {sell_qty}주 수익실현 (수동합산분 포함)")
                        else:
                            print(f"⚠️ [매도스킵] {info['name']} 잔고 정보 확인 불가")

                    # 🎢 [트레일링 스탑] +4% 이상 갔다가 고점대비 1% 빠지면
                    if profit_rate > info['max_profit_rate']:
                        self.portfolio[code]['max_profit_rate'] = profit_rate
                    
                    max_p = info['max_profit_rate']
                    if max_p >= BotConfig.TS_TRIGGER_RATE:
                        if profit_rate <= (max_p - BotConfig.TS_STOP_GAP):
                            self.sell_stock(code, f"🎢TS익절(최고 {max_p*100:.1f}% -> 현재 {profit_rate*100:.1f}%)")
                            continue

                time.sleep(0.5)

            except Exception as e:
                print(f"❌ 감시 루프 에러: {e}")
                time.sleep(3)

    # ------------------------------------------------------------------
    # 🕵️ [종목 선정 함수] 수정됨: 윗꼬리 작은 순 정렬
    # ------------------------------------------------------------------
    def get_jongga_targets(self):
        # 1. 조건검색식 조회 (거래대금 Top, 프로그램 100억 등 조건 만족군)
        candidates = self.api.fetch_condition_stocks("jongga") 
        if not candidates: 
            print("⚠️ 조건검색 'jongga' 결과 없음")
            return []

        # 2. 필터링 및 정보 수집
        filtered = []
        for stock in candidates:
            code = stock['stck_shrn_iscd']
            name = stock['hts_kor_isnm']
            
            # 잡주 제외
            if any(x in name for x in ["스팩", "ETN", "ETF", "리츠", "우B", "우(", "인버스", "레버리지", "선물", "채권"]) or name.endswith("우"):
                continue
            
            # 블랙리스트/제외종목 체크
            if code in self.today_blacklist: continue
            if code in self.exclude_list: continue
            
            # 상세 정보 조회
            info = self.api.fetch_price_detail(code, name)
            if not info: continue
            
            # [필수 조건 체크]
            # if info['rate'] < BotConfig.MIN_RATE: continue      # 3% 이상 상승
            # ✅ [조건 1] 시가(Open) 대비 상승률 10% 이상 확인
            # (API의 rate는 전일대비이므로, 시가 기준 직접 계산)
            if info['open'] > 0:
                rate_from_open = ((info['price'] - info['open']) / info['open']) * 100
                if rate_from_open < BotConfig.MIN_RATE: continue
            else:
                continue
            # ✅ [조건 3] 윗꼬리 10% ~ 30% 사이 (설정값 사용)
            if not (BotConfig.MIN_WICK <= info['wick_ratio'] <= BotConfig.MAX_WICK):
                continue
            if info['price'] <= info['open']: continue          # 양봉
            if info['wick_ratio'] >= BotConfig.MAX_WICK: continue # 윗꼬리 30% 미만 (안전장치)
            if info['price'] >= info['max_price']: continue     # 상한가 제외
            
            # 프로그램 수급 체크
            pg_amt = info['program_buy'] * info['price']
            if pg_amt <= 0: continue

            trade_amt = info['price'] * info['acml_vol']
            
            # ✅ 리스트에 'wick_ratio'도 함께 저장
            filtered.append({
                'code': code, 
                'name': name, 
                'trade_amt': trade_amt,
                'price': info['price'],
                'wick_ratio': info['wick_ratio'] # 정렬을 위해 저장
            })
            time.sleep(0.1) # API 부하 조절

        # ✅ [조건 4] 거래대금(trade_amt)이 가장 큰 순서로 정렬 (내림차순)
        filtered.sort(key=lambda x: x['trade_amt'], reverse=True)

        # 3. ✅ [핵심 수정] 정렬 기준 변경
        # 기존: 거래대금 많은 순 (reverse=True)
        # 신규: 윗꼬리 비율 작은 순 (reverse=False, 오름차순) -> 0.0(윗꼬리 없음)이 1등
        # filtered.sort(key=lambda x: x['wick_ratio'])
        
        # 상위 N개 선정
        # return filtered[:BotConfig.MAX_STOCKS]
        return filtered[:BotConfig.MAX_STOCKS]

    def liquidate_all_positions(self, reason="장 마감"):
        if not self.portfolio: return
        telegram_notifier.send_telegram_message(f"⏰ [{MODE}] 장 마감 전량 청산")
        for code in list(self.portfolio.keys()):
            self.sell_stock(code, "장 마감(Time-Cut)")
            
    def wait_until_next_morning(self):
        now = datetime.datetime.now()
        tomorrow = now + datetime.timedelta(days=1)
        next_morning = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 8, 50, 0)
        
        wait_seconds = (next_morning - now).total_seconds()
        if wait_seconds > 0:
            msg = f"💤 [{MODE}] 장 종료. 내일 08:50 대기."
            telegram_notifier.send_telegram_message(msg)
            self.portfolio = {}
            self.blacklist = {} # Dict 초기화
            self.daily_buy_cnt = {'MORNING': 0, 'THEME': 0, 'PROGRAM': 0}
            
            self.bought_themes = set()
            self.locked_leaders_time = {}
            self.missing_counts = {}
            
            self.market_open_time = None
            time.sleep(wait_seconds)
            telegram_notifier.send_telegram_message(f"☀️ [{MODE}] 봇 기상! 시장 개장 감시 시작.")

    def wait_for_market_open(self):
        print("🕵️ 시장 개장 감시 시작 (삼성전자 거래량 감시)...")
        while True:
            now = datetime.datetime.now()
            if now.weekday() >= 5:
                telegram_notifier.send_telegram_message("⛔ 주말입니다. 대기 모드 진입.")
                self.wait_until_next_morning()
                return False
            if self.api.check_holiday(now.strftime("%Y%m%d")):
                telegram_notifier.send_telegram_message("⛔ 오늘은 휴장일입니다.")
                self.wait_until_next_morning()
                return False
            if now.hour == 8 and now.minute < 45:
                time.sleep(1) 
                continue

            ref_data = self.api.fetch_price_detail(BotConfig.PROBE_STOCK_CODE)
            vol = ref_data.get('acml_vol', 0) if ref_data else 0
            
            if now.hour == 8 and now.minute >= 45:
                if vol == 0:
                    print(f"   [08:{now.minute}] 거래량 0 (지연 개장 가능성 높음)")
                    time.sleep(30)
                else:
                    print(f"   [08:{now.minute}] 장전 거래량 포착({vol:,}). 09:00 정상 개장 대기.")
                    time.sleep(10)
                continue
            if now.hour == 9:
                if vol > 0:
                    self.market_open_time = now
                    telegram_notifier.send_telegram_message(f"🔔 [정상 개장] 09:00 Market Open!\n(Vol: {vol:,})")
                    return True
                else:
                    if now.minute >= 5:
                        telegram_notifier.send_telegram_message("💤 지연 개장 확인 (Vol=0). 10:00까지 대기합니다.")
                        target_time = datetime.datetime(now.year, now.month, now.day, 9, 59, 50)
                        sleep_sec = (target_time - datetime.datetime.now()).total_seconds()
                        if sleep_sec > 0:
                            time.sleep(sleep_sec)
                        continue
                    else:
                        time.sleep(5)
                        continue
            if 10 <= now.hour < 15:
                self.market_open_time = now.replace(hour=9, minute=0, second=0, microsecond=0)
                telegram_notifier.send_telegram_message(f"🔔 [지연/정상] 10:00 Market Active.\n(Vol: {vol:,})")
                return True
            time.sleep(1)
            
    def sell_stock(self, code, reason):
        if code in self.portfolio:
            qty = self.portfolio[code]['qty']
            cur_price = 0
            
            temp_info = self.api.fetch_price_detail(code)
            # pg_amt_at_sell = 0
            current_pg_qty = 0  # ✅ [필수] 미리 0으로 초기화해둬야 안전함
            if temp_info: 
                cur_price = temp_info['price']
                current_pg_qty = temp_info.get('program_buy', 0) # 👈 [추가됨] 수량 추출
                # pg_amt_at_sell = temp_info['program_buy'] * temp_info['price']

            res = self.api.send_order(code, qty, is_buy=False)
            if res['rt_cd'] == '0':
                name = self.portfolio[code]['name']
                buy_price = self.portfolio[code]['buy_price']
                profit_rate = 0.0
                if buy_price > 0 and cur_price > 0:
                    profit_rate = (cur_price - buy_price) / buy_price * 100
                msg = (f"👋 [{MODE} 매도] {name}\n"
                       f"사유: {reason}\n"
                       f"매도가: {cur_price:,}원 ({profit_rate:+.2f}%)\n"
                       f"📊 PG순매수: {current_pg_qty:,}주\n" # 👈 [추가됨]
                       f"수량: {qty}주")
                telegram_notifier.send_telegram_message(msg)
                # ... (주문 전송 로직) ...

                # API 주문 후 성공했다고 가정하고 로그 기록 (혹은 res['rt_cd'] == '0' 내부로 이동 가능)

                # 👇 [추가] 통계 데이터 추출
                p_data = self.portfolio[code]
                cur_price = temp_info['price'] if temp_info else 0
                exit_pg = temp_info['program_buy'] * temp_info['price'] if temp_info else 0

                # 보유 시간 계산 (분 단위)
                hold_min = 0
                if 'buy_time' in p_data:
                    hold_min = int((datetime.datetime.now() - p_data['buy_time']).total_seconds() / 60)

                trade_logger.log_sell({
                    'code': code, 'name': p_data['name'],
                    'strategy': p_data['strategy'], 'reason': reason,
                    'buy_price': p_data['buy_price'],
                    'sell_price': cur_price,
                    'qty': p_data['qty'],
                    'hold_time_min': hold_min,
                    # 추적해온 데이터 기록
                    'max_price': p_data.get('stats_max_price', 0),
                    'min_price': p_data.get('stats_min_price', 0),
                    'entry_pg': p_data.get('stats_entry_pg', 0),
                    'max_pg': p_data.get('stats_max_pg', 0),
                    'exit_pg': exit_pg
                })
                
                # 블랙리스트 등록. 수동매매와 봇 충돌 방지
                self.today_blacklist.add(code)

                # ✅ [수정] 자물쇠를 걸고 안전하게 삭제
                with self.lock:
                    if code in self.portfolio:
                        del self.portfolio[code]

    # 📡 [신규] 텔레그램 명령 처리 쓰레드 함수
    def telegram_listener(self):
        url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
        
        while self.is_running:
            try:
                # 롱폴링 (timeout=10초 대기)
                params = {'offset': self.last_update_id + 1, 'timeout': 10}
                res = requests.get(url, params=params, timeout=15)
                
                if res.status_code == 200:
                    data = res.json()
                    if not data['ok']: continue

                    for update in data['result']:
                        self.last_update_id = update['update_id']
                        
                        if 'message' not in update or 'text' not in update['message']:
                            continue
                            
                        text = update['message']['text'].strip()
                        chat_id = str(update['message']['chat']['id'])
                        
                        # 내 채팅방 명령만 허용
                        if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
                            continue

                        # === 명령어 처리 로직 ===
                        if text == '/info' or text == 'info':
                            balance = self.api.fetch_balance()
                            msg = f"📊 [현재 상태]\n💰 잔고: {balance:,}원\n🛑 매수활성: {'ON' if self.is_buy_active else 'OFF'}\n\n[보유 종목]"

                            # ✅ [수정] 조회하는 동안 데이터가 변하지 않게 잠금
                            with self.lock:
                                if not self.portfolio:
                                    msg += "\n없음"
                                else:
                                    for c, v in self.portfolio.items():
                                        rate = v.get('max_profit_rate', 0) * 100
                                        msg += f"\n- {v['name']}: {v['qty']}주 (최고 {rate:.1f}%)"

                            telegram_notifier.send_telegram_message(msg)

                        elif text == '/stop' or text == 'stop':
                            self.is_buy_active = False
                            telegram_notifier.send_telegram_message("⛔ [원격제어] 매수 정지! (보유종목 관리는 계속됨)")

                        elif text == '/start' or text == 'start':
                            self.is_buy_active = True
                            telegram_notifier.send_telegram_message("🟢 [원격제어] 매수 재개!")

                        elif text == '/sell' or text == 'sell':
                            telegram_notifier.send_telegram_message("🚨 [원격제어] 긴급 전량 매도 실행!")
                            self.liquidate_all_positions()

            except Exception as e:
                print(f"텔레그램 리스너 에러: {e}")
                time.sleep(5)

    # ------------------------------------------------------------------
    # 🏃 [메인 실행] 15:00 ~ 15:20 매수 집중
    # ------------------------------------------------------------------

    def run(self):
        t_monitor = threading.Thread(target=self.monitor_portfolio)
        t_monitor.daemon = True
        t_monitor.start()
        
        t_telegram = threading.Thread(target=self.telegram_listener)
        t_telegram.daemon = True
        t_telegram.start()

        telegram_notifier.send_telegram_message(f"🚀 [종가베팅 봇] 시작합니다. (개장 확인 대기)")
        
        target_stocks = [] 
        invest_per_stock = 0 
        
        while True:
            try:
                now = datetime.datetime.now()

                if self.market_open_time is None:
                    is_open = self.wait_for_market_open() 
                    if not is_open: continue 
                
                if now.hour == 8 and now.minute == 0 and now.second < 10:
                    self.today_blacklist.clear()
                    self.buy_progress.clear()
                    target_stocks = []
                    self.market_open_time = None 
                    print("🧹 금일 블랙리스트 초기화 & 개장 체크 준비")
                    time.sleep(10)

                if now.hour == 15 and now.minute >= 35:
                    self.wait_until_next_morning() 
                    self.market_open_time = None
                    self.today_blacklist.clear()   # 블랙리스트 초기화
                    self.buy_progress.clear()      # 매수 기록 초기화
                    target_stocks = []             # 타겟 종목 비우기 (매우 중요!)                    
                    print(f"🧹 [일일 리셋] {datetime.datetime.now().strftime('%m/%d')} 새 하루 시작을 위해 변수 초기화 완료")
                    continue

                if now.hour == config.JONGGA_START_HOUR and now.minute < config.JONGGA_BUY_MINUTE:
                    if now.second == 0:
                        print(f"⏳ [{now.strftime('%H:%M:%S')}] 매수 대기 중...")
                    time.sleep(1)
                    continue
                
                if now.hour == config.JONGGA_BUY_HOUR and config.JONGGA_BUY_MINUTE <= now.minute < 20:
                    
                    if now.minute == 19 and now.second >= 50:
                        time.sleep(1)
                        continue

                    # [A] 종목 선정 (아직 안 했으면 최초 1회 실행)
                    if not target_stocks:
                        print("🎯 [Targeting] 종가베팅 종목 선정 및 예산 심사 시작...")
                        
                        # 1. 일단 조건 만족하는 모든 후보를 가져옴 (3개 제한 없음)
                        all_candidates = self.get_jongga_targets()
                        
                        if all_candidates:
                            # 2. 자금 계산 (예수금 / 목표 종목수)
                            balance = self.api.fetch_balance()
                            
                            # 예수금이 너무 적으면 진행 불가
                            if balance < 100000: # 최소 10만원은 있어야 함
                                print("❌ 예수금 부족으로 매수 포기")
                                time.sleep(60)
                                continue

                            # 종목당 총 할당금 (예: 100만원 / 3 = 33만원)
                            invest_per_stock = int(balance * BotConfig.ASSET_WEIGHT / BotConfig.MAX_STOCKS)
                            
                            # 1회 분할 매수 한도액 (예: 33만원 / 3분할 = 11만원)
                            split_limit = int(invest_per_stock / BotConfig.SPLIT_BUY_CNT)
                            
                            print(f"💰 종목당 할당: {invest_per_stock:,}원 (1회 분할한도: {split_limit:,}원)")

                            # 3. 예산 심사 (비싼 종목 거르고 다음 순위 픽업)
                            final_picks = []
                            
                            for stock in all_candidates:
                                # 목표 개수(3개) 다 채웠으면 중단
                                if len(final_picks) >= BotConfig.MAX_STOCKS:
                                    break
                                
                                # 🚨 [핵심] 가격 조건 심사
                                # "주가가 1회 분할한도보다 비싼가?"
                                if stock['price'] > split_limit:
                                    print(f"⏩ [PASS] {stock['name']} ({stock['price']:,}원) -> 분할한도 초과로 제외 (다음 순위 검색)")
                                    continue # 이거 안 사고 다음 종목으로 넘어감
                                
                                # 통과했으면 목록에 추가
                                final_picks.append(stock)

                            # 4. 최종 확정
                            if final_picks:
                                target_stocks = final_picks
                                
                                msg = "🎯 [종가베팅 최종 선정]\n"
                                for t in target_stocks:
                                    msg += f"- {t['name']} ({t['price']:,}원)\n"
                                telegram_notifier.send_telegram_message(msg)
                            else:
                                print("❌ 모든 후보가 예산 초과로 매수 불가")
                                time.sleep(60)
                                continue

                        else:
                            print("❌ 조건 만족 종목 없음")
                            time.sleep(60) 
                            continue

                    if now.second < 50: 
                        current_split_idx = now.minute - config.JONGGA_BUY_MINUTE
                        
                        if 0 <= current_split_idx < BotConfig.SPLIT_BUY_CNT:
                            for stock in target_stocks:
                                code = stock['code']
                                
                                executed_cnt = self.buy_progress.get(code, 0)
                                if executed_cnt > current_split_idx: continue
                                if code in self.today_blacklist: continue
                                
                                info = self.api.fetch_price_detail(code, stock['name'])
                                if not info: continue
                                
                                one_time_money = int(invest_per_stock / BotConfig.SPLIT_BUY_CNT)
                                # 1매도호가 기준으로 수량 계산 (안전하게)
                                qty = int(one_time_money / info['ask_price'])
                                
                                if qty > 0:
                                    # ✅ [수정] price 인자에 1매도호가 전달
                                    res = self.api.send_order(code, qty, is_buy=True, price=info['ask_price'])
                                    if res['rt_cd'] == '0':
                                        self.buy_progress[code] = executed_cnt + 1
                                        telegram_notifier.send_telegram_message(
                                            f"💎 [종가매수 {current_split_idx+1}차] {stock['name']}\n수량: {qty}주 / 가격: {info['ask_price']:,}원 (1호가)"
                                        )
                                        trade_logger.log_buy({
                                            'code': code, 'name': stock['name'], 
                                            'strategy': 'JONGGA', 'level': current_split_idx+1,
                                            'price': info['ask_price'], # 로그도 매수호가로 기록
                                            'qty': qty,
                                            'pg_amt': 0, 'gap': 0, 'leader': ''
                                        })
                        time.sleep(5)

                time.sleep(0.5)

            except Exception as e:
                print(f"Main Loop Error: {e}")
                time.sleep(5)

if __name__ == "__main__":
    bot = TradingBot()
    bot.run()
