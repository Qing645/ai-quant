import yfinance as yf
import pandas as pd
import argparse
import os
from database import SessionLocal, OHLCVData, init_db
from sqlalchemy.dialects.sqlite import insert

def save_to_db(df, symbol):
    """将数据保存到数据库，冲突时更新 (Upsert)"""
    init_db()  # 确保表已创建
    db = SessionLocal()
    try:
        # 准备批量插入数据
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
        
        # 使用 SQLite 的 UPSERT 语法处理重复日期
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
        print(f"数据已同步至数据库 ({len(records)} 条记录)")
    except Exception as e:
        db.rollback()
        print(f"写入数据库失败: {e}")
    finally:
        db.close()

def fetch_data(symbol, start_date, end_date, output_path):
    """
    使用 akshare (国内) 或 yfinance (国际) 下载股票/ETF历史数据并保存为 CSV,
    彻底解决由于除权除息导致的 K 线断层问题。
    """
    import akshare as ak
    import time
    
    original_symbol = symbol.strip().upper()
    print(f"正在准备下载 {original_symbol} 的数据: {start_date} 至 {end_date}...")
    
    # 转换日期格式支持 akshare
    ak_start = start_date.replace("-", "")
    ak_end = end_date.replace("-", "")
    
    data = pd.DataFrame()
    
    try:
        # 判断是否为国内 A 股或 ETF
        is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
        
        if is_china_market:
            print(f"检测到国内标的，切换至 AkShare 高精度前复权 (qfq) 数据源...")
            # 提取 6 位纯数字代码
            code = ''.join(filter(str.isdigit, original_symbol))
            
            if len(code) != 6:
                raise ValueError(f"无效的 A股/ETF 代码格式: {original_symbol}")
                
            # 判断逻辑: 15xxxx, 51xxxx, 56xxxx, 58xxxx 通常是 ETF
            is_etf = code.startswith(('15', '51', '56', '58'))
            
            if is_etf:
                print(f"正在拉取 ETF 数据 (代码: {code})...")
                data = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=ak_start, end_date=ak_end, adjust="qfq")
            else:
                print(f"正在拉取 A股 数据 (代码: {code})...")
                data = ak.stock_zh_a_hist(symbol=code, period="daily", start_date=ak_start, end_date=ak_end, adjust="qfq")
                
            if data is None or data.empty:
                raise ValueError("AkShare 返回空数据，请检查网络或代码是否退市。")
                
            # AkShare 字段映射到英文系统标准
            col_map = {
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume'
            }
            data.rename(columns=col_map, inplace=True)
            
            required_cols = ['date', 'open', 'close', 'high', 'low', 'volume']
            for c in required_cols:
                if c not in data.columns:
                    raise ValueError(f"AkShare 数据缺失核心列: {c}")
                    
            data = data[required_cols]
            
        else:
            # 国际市场，统一转交 yfinance
            print(f"检测到国际标的，使用 Yahoo Finance 默认数据源...")
            if original_symbol.endswith(".SH"):
                 yf_sym = original_symbol[:-3] + ".SS"
            else:
                 yf_sym = original_symbol
                 
            # 方案 A: 批量下载模式 (启用 auto_adjust=True)
            data = yf.download(yf_sym, start=start_date, end=end_date, progress=False, timeout=20, auto_adjust=True)
            
            # 方案 B: 如果方案 A 失败，尝试 Ticker 历史模式
            if data.empty:
                print(f"方案 A (download) 无结果，尝试方案 B (Ticker.history)...")
                ticker = yf.Ticker(yf_sym)
                data = ticker.history(start=start_date, end=end_date)
                
            if data.empty:
                # 方案 C: 尝试最近 1 个月的数据
                print(f"警告: {yf_sym} 在指定范围内无数据，尝试拉取最近 1 个月数据以验证有效性...")
                data = yf.download(yf_sym, period="1mo", progress=False)

            if data.empty:
                raise ValueError(f"无法获取 {yf_sym} 的数据。原因：该代码在 Yahoo Finance 上不可用。")

            # 展平多重索引 (MultiIndex)
            if isinstance(data.columns, pd.MultiIndex):
                new_cols = []
                for col in data.columns:
                    col_name = col[0] if col[0] in ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume'] else str(col[0])
                    new_cols.append(col_name)
                data.columns = new_cols
            
            # 重置索引
            data.reset_index(inplace=True)
            
            # 列名统一转小写
            data.columns = [str(col).lower() for col in data.columns]

            # 统一日期列名为 'date'
            if 'date' not in data.columns:
                for potential in data.columns:
                    if 'time' in potential or 'date' in potential:
                        data.rename(columns={potential: 'date'}, inplace=True)
                        break

        # =======================================================
        # 公共后处理阶段：时间格式强制转换
        # =======================================================
        if 'date' in data.columns:
            data['date'] = pd.to_datetime(data['date']).dt.strftime('%Y-%m-%d')

        # 保存 CSV (保持兼容性)
        data.to_csv(output_path, index=False)
        
        # 同步存入数据库 (持久化)
        save_to_db(data, original_symbol)
        
        print(f"成功获取 {original_symbol} ({'AkShare' if is_china_market else 'Yfinance'}) 数据 ({len(data)} 行)，保存至: {output_path}")
        
    except Exception as e:
        print(f"下载历史数据失败: {e}")
        raise e

def fetch_intraday_data(symbol):
    """
    获取今日分时数据 (1分钟精度)
    返回格式: [{'time': 'HH:MM', 'price', 'volume'}, ...]
    """
    import akshare as ak
    from datetime import datetime
    import pandas as pd
    
    original_symbol = symbol.strip().upper()
    is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
    
    try:
        if is_china_market:
            code = ''.join(filter(str.isdigit, original_symbol))
            is_etf = code.startswith(('15', '51', '56', '58'))
            
            if is_etf:
                # 获取 ETF 分时数据 (period='1' 表示 1 分钟)
                df = ak.fund_etf_hist_min_em(symbol=code, period='1', adjust="qfq")
            else:
                # 获取 A 股分时数据
                df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', adjust="qfq")
            
            if df is not None and not df.empty:
                # 过滤出当日数据
                today_str = datetime.now().strftime('%Y-%m-%d')
                df['时间项目'] = pd.to_datetime(df['时间'])
                df_today = df[df['时间项目'].dt.strftime('%Y-%m-%d') == today_str]
                
                if df_today.empty:
                    # 如果今日暂无数据 (未开盘)，返回最近的 240 个点 (一交易日)
                    df_today = df.tail(240)
                
                return [
                    {
                        'time': row['时间项目'].strftime('%H:%M'),
                        'price': float(row['收盘']),
                        'volume': float(row['成交量'])
                    } for _, row in df_today.iterrows()
                ]
        else:
            # 国际市场使用 yfinance
            import yfinance as yf
            ticker = yf.Ticker(original_symbol)
            # interval='1m' 获取 1 分钟 K 线
            df = ticker.history(period='1d', interval='1m')
            
            if not df.empty:
                return [
                    {
                        'time': idx.strftime('%H:%M'),
                        'price': float(row['Close']),
                        'volume': float(row['Volume'])
                    } for idx, row in df.iterrows()
                ]
    except Exception as e:
        print(f"获取分时数据失败 ({symbol}): {e}")
        
    return []

def fetch_realtime_quote(symbol):
    """
    获取股票/ETF 的实时快照行情
    返回格式: {'date': 'YYYY-MM-DD', 'open', 'close', 'high', 'low', 'volume'}
    """
    import akshare as ak
    from datetime import datetime
    
    original_symbol = symbol.strip().upper()
    is_china_market = original_symbol.endswith((".SS", ".SZ", ".SH", ".BJ"))
    
    if is_china_market:
        code = ''.join(filter(str.isdigit, original_symbol))
        is_etf = code.startswith(('15', '51', '56', '58'))
        
        try:
            if is_etf:
                df_spot = ak.fund_etf_spot_em()
                row = df_spot[df_spot['代码'] == code]
            else:
                df_spot = ak.stock_zh_a_spot_em()
                row = df_spot[df_spot['代码'] == code]
            
            if not row.empty:
                if is_etf:
                    # ETF 行情列名和股票不同
                    return {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'open': float(row['开盘价'].iloc[0]),
                        'close': float(row['最新价'].iloc[0]),
                        'high': float(row['最高价'].iloc[0]),
                        'low': float(row['最低价'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'prev_close': float(row['昨收'].iloc[0])
                    }
                else:
                    # A 股行情列名
                    return {
                        'date': datetime.now().strftime('%Y-%m-%d'),
                        'open': float(row['开盘'].iloc[0]),
                        'close': float(row['最新价'].iloc[0]),
                        'high': float(row['最高'].iloc[0]),
                        'low': float(row['最低'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'prev_close': float(row['昨收'].iloc[0]) if '昨收' in row.columns else float(row['开盘'].iloc[0])
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="下载股票数据")
    parser.add_argument("--symbol", type=str, default="AAPL", help="股票代码 (例如: AAPL, TSLA, ^GSPC)")
    parser.add_argument("--start", type=str, default="2020-01-01", help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default="2024-01-01", help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--output", type=str, default="stock_data.csv", help="输出文件路径")
    
    args = parser.parse_args()
    fetch_data(args.symbol, args.start, args.end, args.output)
