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
    获取股票/ETF 的实时快照行情 (性能优化版：带 15s 缓存)
    """
    global SPOT_CACHE_STOCK, SPOT_CACHE_ETF, STOCK_TIMESTAMP, ETF_TIMESTAMP
    import akshare as ak
    
    original_symbol = symbol.strip().upper()
    is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
    
    if is_china_market:
        code = ''.join(filter(str.isdigit, original_symbol))
        is_etf = code.startswith(('15', '51', '56', '58'))
        now = time.time()
        
        try:
            if is_etf:
                if SPOT_CACHE_ETF is None or (now - ETF_TIMESTAMP > CACHE_TTL):
                    SPOT_CACHE_ETF = ak.fund_etf_spot_em()
                    ETF_TIMESTAMP = now
                df_spot = SPOT_CACHE_ETF
                row = df_spot[df_spot['代码'] == code]
            else:
                if SPOT_CACHE_STOCK is None or (now - STOCK_TIMESTAMP > CACHE_TTL):
                    # 股票快照使用 stock_zh_a_spot (带时间戳)
                    SPOT_CACHE_STOCK = ak.stock_zh_a_spot()
                    STOCK_TIMESTAMP = now
                df_spot = SPOT_CACHE_STOCK
                row = df_spot[df_spot['代码'] == (code if code.startswith('bj') else original_symbol.replace('.SS', 'sh').replace('.SZ', 'sz').lower())]
                if row.empty: # 兜底逻辑：如果拼凑代码失败，搜索纯代码
                     row = df_spot[df_spot['代码'].str.contains(code)]

            if not row.empty:
                # 提取时间戳
                quote_time = ""
                if is_etf:
                    # ETF: '更新时间' 为 14:55:54+0800 格式
                    raw_time = str(row['更新时间'].iloc[0])
                    if ' ' in raw_time:
                         quote_time = raw_time.split(' ')[1][:5]
                else:
                    # 股票: '时间戳' 为 15:00:11 格式
                    quote_time = str(row['时间戳'].iloc[0])[:5]

                if is_etf:
                    return {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'time': quote_time,
                        'open': float(row['开盘价'].iloc[0]),
                        'close': float(row['最新价'].iloc[0]),
                        'high': float(row['最高价'].iloc[0]),
                        'low': float(row['最低价'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'prev_close': float(row['昨收'].iloc[0])
                    }
                else:
                    return {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'time': quote_time,
                        'open': float(row['今开'].iloc[0]),
                        'close': float(row['最新价'].iloc[0]),
                        'high': float(row['最高'].iloc[0]),
                        'low': float(row['最低'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'prev_close': float(row['昨收'].iloc[0])
                    }
        except Exception as e:
            print(f"获取国内实时行情失败: {e}")
    else:
        try:
            ticker = yf.Ticker(original_symbol)
            hist = ticker.history(period="1d")
            info = ticker.info
            if not hist.empty:
                return {
                    'date': datetime.now().strftime('%Y-%m-%d'),
                    'time': datetime.now().strftime('%H:%M'),
                    'open': float(hist['Open'].iloc[-1]),
                    'close': float(hist['Close'].iloc[-1]),
                    'high': float(hist['High'].iloc[-1]),
                    'low': float(hist['Low'].iloc[-1]),
                    'volume': float(hist['Volume'].iloc[-1]),
                    'prev_close': float(info.get('previousClose', hist['Open'].iloc[-1]))
                }
        except Exception as e:
            print(f"获取国际实时行情失败: {e}")
            
    return None

def fetch_intraday_data(symbol):
    """
    获取今日分时数据 (1分钟精度) - 带 15s 缓存
    """
    global INTRADAY_CACHE
    import akshare as ak
    
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
            is_etf = code.startswith(('15', '51', '56', '58'))
            
            print(f"  [Fetcher] 正在拉取 {original_symbol} 分时数据...")
            if is_etf:
                df = ak.fund_etf_hist_min_em(symbol=code, period='1', adjust="qfq")
            else:
                df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', adjust="qfq")
            
            if df is not None and not df.empty:
                today_str = datetime.now().strftime('%Y-%m-%d')
                df['时间项目'] = pd.to_datetime(df['时间'])
                df_today = df[df['时间项目'].dt.strftime('%Y-%m-%d') == today_str]
                
                if df_today.empty:
                    df_today = df.tail(240)
                
                result = [
                    {
                        'time': row['时间项目'].strftime('%H:%M'),
                        'price': float(row['收盘']),
                        'volume': float(row['成交量'])
                    } for _, row in df_today.iterrows()
                ]
                INTRADAY_CACHE[original_symbol] = (now, result)
                return result
        else:
            ticker = yf.Ticker(original_symbol)
            df = ticker.history(period='1d', interval='1m')
            if not df.empty:
                result = [
                    {
                        'time': idx.strftime('%H:%M'),
                        'price': float(row['Close']),
                        'volume': float(row['Volume'])
                    } for idx, row in df.iterrows()
                ]
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
