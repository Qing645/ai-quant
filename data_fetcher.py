import yfinance as yf
import pandas as pd
import argparse
import os
import time
from database import SessionLocal, OHLCVData, init_db
from sqlalchemy.dialects.sqlite import insert
from datetime import datetime

print(">>> [System] data_fetcher.py module loaded.")

# --- 全局快照与分时数据缓存 ---
SPOT_CACHE_STOCK = None
SPOT_CACHE_ETF = None
STOCK_TIMESTAMP = 0
ETF_TIMESTAMP = 0

INTRADAY_CACHE = {} # {symbol: (timestamp, data_list)}
CACHE_TTL = 15  # 缓存有效时间 15 秒

def save_to_db(df, symbol):
    """将数据保存到数据库，冲突时更新 (Upsert)"""
    init_db()
    db = SessionLocal()
    try:
        records = []
        for _, row in df.iterrows():
            record = {
                'symbol': symbol,
                'date': str(row['date']),
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume'])
            }
            records.append(record)
        
        stmt = insert(OHLCVData).values(records)
        stmt = stmt.on_conflict_do_update(
            index_elements=['symbol', 'date'],
            set_={
                'open': stmt.excluded.open,
                'high': stmt.excluded.high,
                'low': stmt.excluded.low,
                'close': stmt.excluded.close,
                'volume': stmt.excluded.volume
            }
        )
        db.execute(stmt)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"写入数据库失败: {e}")
    finally:
        db.close()

def fetch_realtime_quote(symbol):
    """
    获取股票/ETF 的实时快照行情
    增加智能昨收价 (prev_close) 提取逻辑：排除 CSV 中已有的今日日线干扰
    """
    import akshare as ak
    import yfinance as yf
    
    original_symbol = symbol.strip().upper()
    is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # --- A. 智能获取真正的“昨收价” (Previous Close) ---
    prev_close_val = 0.0
    try:
        # 兜底 1: 本地 CSV (排除今日数据)
        data_file = f"data_{original_symbol}.csv"
        if os.path.exists(data_file):
            df_hist = pd.read_csv(data_file)
            if not df_hist.empty:
                df_prev = df_hist[df_hist['date'].astype(str) < today_str]
                if not df_prev.empty:
                    prev_close_val = float(df_prev.iloc[-1]['close'])
                else:
                    prev_close_val = float(df_hist.iloc[0]['open'])
        
        # 兜底 2: yfinance fast_info (极度可靠的实时昨收源)
        if prev_close_val <= 0:
            yf_symbol = original_symbol
            if is_china_market:
                if original_symbol.endswith(".SH"): yf_symbol = original_symbol.replace(".SH", ".SS")
            tk = yf.Ticker(yf_symbol)
            # 使用 fast_info 避免昂贵的 history 请求
            prev_close_val = float(tk.fast_info.get('previous_close', 0))
    except Exception as e:
        print(f"  [Fetcher] 提取昨收失败 ({original_symbol}): {e}")

    # --- B. 获取当前实时价格 ---
    latest_price = 0.0
    now_time = datetime.now().strftime('%H:%M')
    
    # 尝试源 1: AkShare
    if is_china_market:
        code = ''.join(filter(str.isdigit, original_symbol))
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            info_map = dict(zip(info_df['item'], info_df['value']))
            latest_price = float(info_map.get('最新', 0))
        except:
            pass

    # 尝试源 2: yfinance (如果 Ak 失败或不是中国市场)
    if latest_price <= 0:
        try:
            yf_symbol = original_symbol
            if is_china_market and original_symbol.endswith(".SH"):
                yf_symbol = original_symbol.replace(".SH", ".SS")
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="1d")
            if not hist.empty:
                latest_price = float(hist.iloc[-1]['Close'])
        except:
            pass

    # --- C. 组装结果 ---
    if latest_price > 0:
        return {
            'date': today_str,
            'time': now_time,
            'open': latest_price,
            'close': latest_price,
            'high': latest_price,
            'low': latest_price,
            'volume': 0.0,
            'prev_close': prev_close_val # 改动：不在此处做 latest_price 兜底，交给调用者处理
        }
        
    return None

def fetch_intraday_data(symbol):
    """
    获取今日分时数据 (1分钟精度) - 双源备份
    """
    global INTRADAY_CACHE
    import akshare as ak
    import yfinance as yf
    
    original_symbol = symbol.strip().upper()
    is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
    now = time.time()
    
    if original_symbol in INTRADAY_CACHE:
        cache_ts, cache_data = INTRADAY_CACHE[original_symbol]
        if now - cache_ts < CACHE_TTL:
            return cache_data

    try:
        if is_china_market:
            code = ''.join(filter(str.isdigit, original_symbol))
            try:
                # 判定标的类型，动态切换接口 (股票 vs ETF)
                if original_symbol.startswith(("15", "51", "56", "58")):
                    df = ak.fund_etf_hist_min_em(symbol=code, period='1')
                else:
                    df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', start_date='09:30:00')
                
                if df is not None and not df.empty:
                    today_str = datetime.now().strftime('%Y-%m-%d')
                    # 统一时间列处理
                    time_col = '时间' if '时间' in df.columns else df.columns[0]
                    df['时间项目'] = pd.to_datetime(df[time_col])
                    df_today = df[df['时间项目'].dt.strftime('%Y-%m-%d') == today_str]
                    if df_today.empty: df_today = df.tail(240)
                    
                    price_col = '收盘' if '收盘' in df.columns else 'close'
                    vol_col = '成交量' if '成交量' in df.columns else 'volume'
                    
                    result = [{'time': row['时间项目'].strftime('%H:%M'), 'price': float(row[price_col]), 'volume': float(row[vol_col])} for _, row in df_today.iterrows()]
                    INTRADAY_CACHE[original_symbol] = (now, result)
                    return result
            except Exception as ak_e:
                # 静默处理频繁出现的连接中断，避免日志过载
                pass 

        # --- yfinance 备用 (支持全球包含 A 股) ---
        yf_symbol = original_symbol
        if is_china_market:
            if original_symbol.endswith(".SH"): yf_symbol = original_symbol.replace(".SH", ".SS")
        
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period='1d', interval='1m')
        if not df.empty:
            result = [{'time': idx.strftime('%H:%M'), 'price': float(row['Close']), 'volume': float(row['Volume'])} for idx, row in df.iterrows()]
            INTRADAY_CACHE[original_symbol] = (now, result)
            return result
            
    except Exception as e:
        print(f"获取分时数据失败 ({symbol}): {e}")
    return []


def fetch_data(symbol, start_date, end_date, output_path):
    """历史数据拉取"""
    import akshare as ak
    original_symbol = symbol.strip().upper()
    ak_start = start_date.replace("-", "")
    ak_end = end_date.replace("-", "")
    data = pd.DataFrame()
    
    try:
        is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
        if is_china_market:
            code = ''.join(filter(str.isdigit, original_symbol))
            is_etf = code.startswith(('15', '51', '56', '58'))
            if is_etf:
                data = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=ak_start, end_date=ak_end, adjust="qfq")
            else:
                data = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=ak_start, end_date=ak_end, adjust="qfq")
            
            if data is not None and not data.empty:
                data.rename(columns={'日期': 'date', '开盘': 'open', '收盘': 'close', '最高': 'high', '最低': 'low', '成交量': 'volume'}, inplace=True)
                data = data[['date', 'open', 'close', 'high', 'low', 'volume']]
        else:
            data = yf.download(original_symbol, start=start_date, end=end_date, progress=False, auto_adjust=True)
            if not data.empty:
                data.reset_index(inplace=True)
                data.columns = [str(col).lower() for col in data.columns]
                if 'date' not in data.columns:
                    for c in data.columns:
                        if 'time' in c or 'date' in c:
                            data.rename(columns={c: 'date'}, inplace=True)
                            break
        
        if not data.empty:
            data['date'] = pd.to_datetime(data['date']).dt.strftime('%Y-%m-%d')
            data.to_csv(output_path, index=False)
            save_to_db(data, original_symbol)
            print(f"下载存盘完成: {output_path} ({len(data)} 行)")
    except Exception as e:
        print(f"下载失败: {e}")
        raise e

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", type=str, default="AAPL")
    parser.add_argument("--start", type=str, default="2020-01-01")
    parser.add_argument("--end", type=str, default="2024-01-01")
    parser.add_argument("--output", type=str, default="stock_data.csv")
    args = parser.parse_args()
    fetch_data(args.symbol, args.start, args.end, args.output)
