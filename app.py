from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel
import pandas as pd
import os
import json
import numpy as np
import asyncio
from typing import List, Dict, Optional
from datetime import datetime
import database
from database import SessionLocal, BacktestRun, TradeLog, Watchlist, init_db

import data_fetcher
import feature_engineer
import model_trainer
import backtest_engine
import backtest_analyzer
import market_insight
import auth
from auth import get_current_user
from sqlalchemy.orm import Session

app = FastAPI(title="AI Quant API")

# 初始化数据库
init_db()

class SendCodeRequest(BaseModel):
    email: str

class RegisterRequest(BaseModel):
    email: str
    password: str
    code: str

class LoginRequest(BaseModel):
    email: str
    password: str

# 允许跨域访问
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 基础数据路径
DATA_FILE = "stock_data.csv"
PROCESSED_FILE = "processed_data.csv"
BACKTEST_FILE = "backtest_data.csv"
MODEL_FILE = "quant_model.joblib"
METRICS_FILE = "metrics.json"
TRADES_FILE = "trades.json"

# --- 全局状态缓存 (用于实时信号翻转告警与性能优化) ---
LAST_SIGNALS = {} # {symbol: last_signal_int}
MODEL_CACHE = None
DATA_CACHE = None
CACHE_TIMESTAMP = 0
CACHE_EXPIRE = 120 # 数据缓存 2 分钟 (对于 30 秒轮询足够)

# 洞察数据缓存 (缓存 5 分钟)
INSIGHT_CACHE = {"data": None, "ts": 0}
INSIGHT_TTL = 300 

def _validate_symbol(raw: str) -> str:
    symbol = raw.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="请提供有效的股票代码")
    if ".." in symbol or "/" in symbol or "\\" in symbol:
        raise HTTPException(status_code=400, detail="股票代码格式不正确")
    for ch in symbol:
        if not (ch.isalnum() or ch in "._-"):
            raise HTTPException(status_code=400, detail="股票代码格式不正确")
    return symbol

@app.get("/api/health")
def health_check():
    return {"status": "healthy"}

@app.post("/api/auth/send-code")
async def send_code(payload: SendCodeRequest, db: Session = Depends(database.get_db)):
    """生成验证码并模拟发送"""
    import random
    from datetime import datetime, timedelta
    
    # 简单的邮箱格式校验
    email = payload.email
    if "@" not in email:
        raise HTTPException(status_code=400, detail="邮箱格式不正确")
    
    # 生成 6 位验证码
    code = f"{random.randint(100000, 999999)}"
    expires_at = datetime.now() + timedelta(minutes=10)
    
    # 存储/更新验证码
    vc = db.query(database.VerificationCode).filter(database.VerificationCode.email == email).first()
    if vc:
        vc.code = code
        vc.expires_at = expires_at
    else:
        vc = database.VerificationCode(email=email, code=code, expires_at=expires_at)
        db.add(vc)
    
    db.commit()
    
    # 模拟发送 (打印到终端)
    print("\n" + "="*50)
    print(f"【DEBUG 邮件验证码】发送至: {email}")
    print(f"验证码内容: {code}")
    print(f"有效期至: {expires_at.strftime('%H:%M:%S')}")
    print("="*50 + "\n")
    
    return {"message": "验证码已发送，请查看终端输出"}

@app.post("/api/auth/register")
async def register(payload: RegisterRequest, db: Session = Depends(database.get_db)):
    """用户注册 (基于邮件验证码)"""
    from datetime import datetime
    try:
        email = payload.email
        password = payload.password
        code = payload.code
        # 1. 验证码校验
        vc = db.query(database.VerificationCode).filter(
            database.VerificationCode.email == email,
            database.VerificationCode.code == code
        ).first()
        
        if not vc or vc.expires_at < datetime.now():
            raise HTTPException(status_code=400, detail="验证码无效或已过期")
        
        # 2. 检查用户是否已存在
        existing_user = db.query(database.User).filter(database.User.email == email).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="该邮箱已注册")
        
        # 3. 创建用户 (用户名默认为邮箱前缀)
        username = email.split("@")[0]
        hashed_password = auth.get_password_hash(password)
        new_user = database.User(username=username, email=email, hashed_password=hashed_password)
        db.add(new_user)
        
        # 4. 注册成功后清理验证码
        db.delete(vc)
        db.commit()
        return {"message": "注册成功"}
    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")

@app.post("/api/auth/login")
async def login(payload: LoginRequest, db: Session = Depends(database.get_db)):
    """用户登录 (支持邮箱)"""
    email = payload.email
    password = payload.password
    user = db.query(database.User).filter(database.User.email == email).first()
    if not user or not auth.verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    
    access_token = auth.create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer", "username": user.username}

@app.post("/api/run-pipeline")
async def run_pipeline(
    symbol: str = "AAPL", 
    start: str = "2020-01-01", 
    end: str = "2024-01-01",
    initial_capital: float = 10000.0,
    prediction_days: int = 10,
    stop_loss: float = -0.05,
    grace_period: int = 3,
    pos_ratio: float = 1.0,
    max_account_drawdown: float = 0.2,
    use_atr_stop: bool = False,
    current_user: database.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    一键运行完整量化管线 (支持逗号分隔的多个标的批量处理)
    """
    try:
        # 清理旧的组合数据
        if os.path.exists("portfolio_nav.csv"):
            os.remove("portfolio_nav.csv")
            
        # 支持批量处理
        symbols = [_validate_symbol(s) for s in symbol.split(",") if s.strip()]
        if not symbols:
            raise HTTPException(status_code=400, detail="请提供有效的股票代码")
            
        success_list = []
        symbol_data_map = {} # 用于存储多标的数据路径映射
        
        # 标准化日期格式
        start = start.replace("/", "-")
        end = end.replace("/", "-")
        
        # 修正 yfinance 排他性
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        fetch_end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
        for s in symbols:
            try:
                print(f"\n>>>> 正在为 {s} 启动量化管线分步任务...")
                # 为不同标的分离文件路径，防止覆盖
                s_data_file = f"data_{s}.csv"
                s_processed_file = f"processed_{s}.csv"
                s_model_file = f"model_{s}.joblib"
                s_backtest_file = f"backtest_{s}.csv"
                
                # 1. 下载数据
                data_fetcher.fetch_data(s, start, fetch_end, s_data_file)
                
                # 2. 特征工程
                if not os.path.exists(s_data_file): continue
                raw_df = pd.read_csv(s_data_file)
                if raw_df.empty: continue
                
                processed_df = feature_engineer.prepare_features(raw_df, prediction_window=prediction_days)
                if processed_df.empty: continue
                processed_df.to_csv(s_processed_file, index=False)
                
                # 3. 模型训练
                model_trainer.train_model(s_processed_file, s_model_file, s_backtest_file)
                
                symbol_data_map[s] = s_backtest_file
                success_list.append(s)
            except Exception as inner_e:
                print(f"  [Error] 标的 {s} 处理失败，跳过: {inner_e}")
                continue

        # 检查是否至少有一个标的处理成功
        if not success_list:
            raise HTTPException(status_code=404, detail="所选标的均无法获取有效数据，请检查代码或扩大日期范围。")
            
        # 兼容单标的模式的旧缓存路径逻辑
        if len(symbols) == 1:
            import shutil
            s = symbols[0]
            shutil.copy(f"backtest_{s}.csv", BACKTEST_FILE)
            shutil.copy(f"model_{s}.joblib", MODEL_FILE)
            global MODEL_CACHE, DATA_CACHE
            MODEL_CACHE = None
            DATA_CACHE = None
            
        # 4. 执行回测 (单标的 vs 组合模式)
        if len(symbols) == 1:
            s = symbols[0]
            backtest_engine.run_backtest(
                symbol_data_map[s], 
                METRICS_FILE, 
                TRADES_FILE,
                initial_capital=initial_capital,
                stop_loss=stop_loss,
                grace_period=grace_period,
                pos_ratio=pos_ratio,
                max_account_drawdown=max_account_drawdown,
                use_atr_stop=use_atr_stop,
                symbol=s,
                user_id=current_user.id
            )
        else:
            print(f"\n>>>> 启动组合回测模式: {symbols}")
            backtest_engine.run_portfolio_backtest(
                symbol_data_map,
                METRICS_FILE,
                TRADES_FILE,
                initial_capital=initial_capital,
                stop_loss=stop_loss,
                grace_period=grace_period,
                pos_ratio=pos_ratio,
                max_account_drawdown=max_account_drawdown,
                use_atr_stop=use_atr_stop,
                user_id=current_user.id
            )
            
        # 5. 生成智能分析报告
        try:
            with open(METRICS_FILE, 'r') as f: m_data = json.load(f)
            with open(TRADES_FILE, 'r') as f: t_data = json.load(f)
            report_md = backtest_analyzer.generate_analysis_report(m_data, t_data)
            with open("analysis_report.md", "w") as f: f.write(report_md)
        except Exception as e:
            print(f"  [Error] Analysis generation failed: {e}")
            report_md = "报告生成失败，请检查回测数据。"

        return {
            "status": "success", 
            "symbols": success_list,
            "report": report_md
        }
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_detail)

@app.get("/api/data/chart")
def get_chart_data():
    """
    获取图表展示数据 (支持单标的 K 线与组合 NAV 曲线)
    """
    from fastapi.responses import Response
    import math
    
    # 优先检查是否存在组合回测数据
    target_file = "portfolio_nav.csv" if os.path.exists("portfolio_nav.csv") else BACKTEST_FILE
    
    if not os.path.exists(target_file):
        raise HTTPException(status_code=404, detail="Backtest data not found.")
    
    df = pd.read_csv(target_file)
    # 替换 Inf/-Inf 为 NaN
    df = df.replace([float('inf'), float('-inf')], float('nan'))
    
    records = []
    for row in df.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                clean[k] = None
            elif hasattr(v, 'item'):  # numpy scalar -> python native
                clean[k] = v.item()
            else:
                clean[k] = v
        records.append(clean)
    
    return Response(content=json.dumps(records), media_type="application/json")

@app.get("/api/model/metrics")
def get_model_metrics():
    """
    获取量化评估指标
    """
    if not os.path.exists(METRICS_FILE):
        return {
            "total_return": 0, "annual_return": 0, "sharpe_ratio": 0,
            "max_drawdown": 0, "win_rate": 0, "profit_loss_ratio": 0,
            "trade_count": 0, "final_value": 0
        }
    
    with open(METRICS_FILE, 'r') as f:
        return json.load(f)

@app.get("/api/data/intraday")
async def get_intraday_data(symbol: str):
    """获取标的分时数据，并附加实时最新价格对齐 (Live Tick-to-Min)"""
    try:
        symbol = _validate_symbol(symbol)
        data = data_fetcher.fetch_intraday_data(symbol)
        quote = data_fetcher.fetch_realtime_quote(symbol)
        
        if not quote:
            return {"data": data, "prev_close": 0}
            
        # 实时补点逻辑：将“实时秒级行情”合并入“分钟历史序列”
        # 优先使用行情自带的时间戳，如果缺失则回退到系统时间 (HH:MM)
        from datetime import datetime
        now_time = quote.get('time') or datetime.now().strftime("%H:%M")
        
        # 确保时间格式为 HH:MM (处理 15:00:11 -> 15:00)
        if len(now_time) > 5:
            now_time = now_time[:5]
            
        if data:
            last_point = data[-1]
            if last_point['time'] == now_time:
                # 如果当前分钟已在序列中，更新为最新成交价
                last_point['price'] = quote['close']
            else:
                # 手动追加一个实时点
                data.append({
                    'time': now_time,
                    'price': quote['close'],
                    'volume': 0 
                })
        else:
            # 如果序列为空，直接加入一个实时点
            data = [{
                'time': now_time,
                'price': quote['close'],
                'volume': 0
            }]
            
        return {"data": data, "prev_close": quote.get('prev_close', 0)}
    except Exception as e:
        print(f"分时数据对齐失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/backtest/trades")
async def get_trade_logs():
    """
    获取详细交易日志
    """
    if not os.path.exists(TRADES_FILE):
        return []
    
    with open(TRADES_FILE, 'r') as f:
        return json.load(f)

@app.get("/api/last-signal")
def get_last_signal():
    """
    获取最新的 AI 预测信号（用于今日操作提醒）
    """
    if not os.path.exists(BACKTEST_FILE):
        return {"date": "N/A", "signal": 0, "price": 0, "status": "no_data"}
    
    try:
        df = pd.read_csv(BACKTEST_FILE)
        if df.empty:
            return {"date": "N/A", "signal": 0, "price": 0, "status": "empty"}
        
        last_row = df.iloc[-1]
        return {
            "date": str(last_row.get("date", "N/A")),
            "signal": int(last_row.get("predicted_signal", 0)),
            "price": round(float(last_row.get("close", 0)), 2),
            "status": "success"
        }
    except Exception as e:
        return {"error": str(e), "status": "error"}

def _translate_to_chinese(text: str) -> str:
    """
    轻量级翻译助手：利用公共接口将英文简介转为中文
    """
    if not text or len(text) < 5: return ""
    import requests
    import urllib.parse
    
    # 对文本进行处理，短文本(如名称)直接翻译，长文本(如简介)切分
    if '.' in text and len(text) > 50:
        paragraphs = text.split('.')[:2]
        main_text = ". ".join(paragraphs) + "."
    else:
        main_text = text
        
    import urllib.parse
    encoded_text = urllib.parse.quote(main_text)
    
    url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=zh-CN&dt=t&q={encoded_text}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            res_json = res.json()
            # 拼接翻译后的句子
            translated = "".join([sent[0] for sent in res_json[0] if sent[0]])
            return translated
    except Exception as e:
        print(f"数据获取失败: {e}")
        return ""

@app.get("/api/market/insights")
async def get_market_insights():
    """获取市场洞察：新闻、板块、推荐"""
    global INSIGHT_CACHE
    import time
    now = time.time()
    
    if INSIGHT_CACHE["data"] and now - INSIGHT_CACHE["ts"] < INSIGHT_TTL:
        return INSIGHT_CACHE["data"]
        
    try:
        data = market_insight.get_market_insights()
        INSIGHT_CACHE = {"data": data, "ts": now}
        return data
    except Exception as e:
        print(f"Insight error: {e}")
        return {"news": [], "sectors": [], "recommendations": [], "error": str(e)}

@app.get("/api/realtime/check")
async def check_realtime_signal(symbol: str = "159915.SZ"):
    """
    实时扫描：结合历史数据与即时价格，给出此时此刻的 AI 诊断
    """
    global MODEL_CACHE, DATA_CACHE, CACHE_TIMESTAMP
    import joblib
    import numpy as np
    import time
    
    # 1. 模型缓存检查
    if MODEL_CACHE is None:
        if os.path.exists(MODEL_FILE):
            MODEL_CACHE = joblib.load(MODEL_FILE)
        else:
            return {"status": "error", "message": "模型未就绪"}
            
    try:
        # 2. 获取实时行情
        symbol = _validate_symbol(symbol)
        quote = data_fetcher.fetch_realtime_quote(symbol)
        if not quote:
            return {"status": "error", "message": "无法获取实时行情"}
            
        # 3. 历史数据读取 (PM 重大更新：强制读取该标的的专属回测文件)
        symbol_backtest = f"backtest_{symbol}.csv"
        target_csv = symbol_backtest if os.path.exists(symbol_backtest) else BACKTEST_FILE
        
        print(f"  [PM Core] 正在从 {target_csv} 加载战略信号基准...")
        hist_df = pd.read_csv(target_csv)
        
        # 4. 实时点热更新
        if not hist_df.empty and str(hist_df.iloc[-1]['date']) == str(quote['date']):
            for col in ['close', 'high', 'low', 'volume']:
                if col in hist_df.columns:
                    if col == 'high':
                        hist_df.iloc[-1, hist_df.columns.get_loc(col)] = max(hist_df.iloc[-1]['high'], quote['high'])
                    elif col == 'low':
                        hist_df.iloc[-1, hist_df.columns.get_loc(col)] = min(hist_df.iloc[-1]['low'], quote['low'])
                    else:
                        hist_df.iloc[-1, hist_df.columns.get_loc(col)] = quote[col]
        else:
            new_row = pd.DataFrame([quote])
            hist_df = pd.concat([hist_df, new_row], ignore_index=True)
            
        # 5. 特征预计算
        processed_df = feature_engineer.prepare_features(hist_df.tail(100).copy())
        
        # 6. 模型推理
        model = MODEL_CACHE
        feature_cols = [
            'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'volatility', 
            'atr_20', 'body_size', 'upper_shadow', 'vol_ratio', 'bb_p', 'roc',
            'obv_roc', 'vpt_roc', 'vol_spike', 'momentum_accel'
        ]
        X_latest = processed_df[feature_cols].tail(1)
        
        if isinstance(model, list):
            probs = [m.predict_proba(X_latest)[0, 1] for m in model]
            prob = float(np.mean(probs))
            print(f"  [Ensemble] 实时诊断共识度: {prob:.4f}")
        else:
            prob = float(model.predict_proba(X_latest)[0, 1])

        # 判定
        threshold = 0.5
        signal = 1 if prob >= threshold else 0
        
        # --- [PM Sprint 10.0] 跨周期信号共识深度审计 ---
        is_divergent = False
        daily_signal = None
        if not hist_df.empty:
            # 查找最后一个具有预测信号的日线点
            valid_days = hist_df[hist_df['predicted_signal'].notna()]
            if not valid_days.empty:
                daily_signal = int(valid_days.iloc[-1]["predicted_signal"])
        
        # 结果组装与场景研判
        ai_signal = 1 if prob >= threshold else -1
        is_smart_guard = False
        
        if daily_signal == 0:
            if prob >= 0.5:
                is_divergent = True
                action_msg = "战略背离：日线看空，暂不接飞刀"
                ai_signal = -1  # 强制长线压制截断短线多头
            elif prob > 0.3:
                is_divergent = True # 轻微多空分歧也作为黄字预警
                action_msg = "战略防护：日线处空仓期，建议观望"
                ai_signal = -1
            else:
                is_divergent = False
                action_msg = "战略共识：长短线均看空，保持空仓状态"
            is_smart_guard = True
        elif daily_signal == 1:
            if prob < 0.3:
                is_divergent = True
                action_msg = "战略背离：分时下挫过快，注意阶段回调"
            elif prob < 0.5:
                is_divergent = False
                action_msg = "分时震荡：长线看多，可寻觅逢低吸纳机会"
            else:
                is_divergent = False
                action_msg = "战略共识：长短线均看多，建议持仓或加仓"
                is_smart_guard = (prob >= 0.8)
        else:
            if prob >= 0.8:
                action_msg = "强烈看多 (Strong Buy)"
                is_smart_guard = True
            elif prob >= 0.5:
                action_msg = "建议买入 (Buy)"
            elif prob >= 0.3:
                action_msg = "震荡观望 (Hold)"
            else:
                action_msg = "建议离场 (Sell)"

        return {
            "status": "success",
            "symbol": symbol,
            "current_price": round(float(quote['close']), 3),
            "ai_confidence": round(float(prob), 4),
            "ai_signal": ai_signal, # 对齐前端
            "signal": signal,       # 保持向下兼容
            "action": action_msg,
            "is_smart_guard": is_smart_guard,
            "is_divergent": is_divergent,
            "daily_signal_ref": daily_signal,
            "updated_at": datetime.now().strftime("%H:%M:%S")
        }
        
    except Exception as e:
        return {"status": "error", "message": f"实时诊断失败: {str(e)}"}

@app.get("/api/stock/info")
def get_stock_info(symbol: str, db: Session = Depends(database.get_db)):
    """
    获取股票元数据并自动翻译业务摘要 (带数据库缓存)
    """
    symbol = symbol.strip().upper()
    
    # 1. 优先尝试从数据库读取缓存
    cached = db.query(database.StockMetadata).filter(database.StockMetadata.symbol == symbol).first()
    if cached:
        # 核心防御：如果 A 股缓存了英文名，强制标记失效以触发重新下载并修正
        is_a_share = symbol.lower().endswith((".sh", ".sz", ".ss", ".bj"))
        bad_keywords = ["China", "Energy", "Engineering", "Corporation", "Ltd", "Co."]
        is_bad_cache = is_a_share and any(bad in cached.name for bad in bad_keywords)
        
        if not is_bad_cache:
            return {
                "name": cached.name,
                "sector": cached.sector,
                "industry": cached.industry,
                "currency": cached.currency,
                "exchange": cached.exchange,
                "summary": cached.summary,
                "from_cache": True
            }

    # 常用板块和行业翻译映射
    TRANSLATIONS = {
        "Technology": "信息技术",
        "Healthcare": "医疗保健",
        "Financial Services": "金融服务",
        "Energy": "能源",
        "Consumer Defensive": "必需消费品",
        "Consumer Cyclical": "非必需消费品",
        "Industrials": "工业制造",
        "Utilities": "公用事业",
        "Basic Materials": "基础材料",
        "Real Estate": "房地产",
        "Communication Services": "通讯服务",
        "Financial": "金融",
        "Building Materials": "建筑材料",
        "Gold": "黄金",
        "Precious Metals": "贵金属",
        "Mining": "矿产开发",
        "Metal & Mining": "金属与采矿"
    }

    target_symbol = symbol
    is_a_share = symbol.lower().endswith((".sh", ".sz", ".ss", ".bj"))
    
    if symbol.lower().endswith(".sh"):
        target_symbol = symbol[:-3].upper() + ".SS"
    elif symbol.lower().endswith(".sz"):
        target_symbol = symbol[:-3].upper() + ".SZ"

    try:
        import yfinance as yf
        ticker = yf.Ticker(target_symbol)
        info = ticker.info
        
        raw_sector = info.get("sector", "未知板块")
        raw_industry = info.get("industry", "未知行业")
        
        # 简单翻译处理
        sector = TRANSLATIONS.get(raw_sector, raw_sector)
        industry = TRANSLATIONS.get(raw_industry, raw_industry)
        
        # 提取业务简介并翻译
        raw_summary = info.get("longBusinessSummary", "")
        summary = _translate_to_chinese(raw_summary) if raw_summary else "暂无公司业务简介。"
        
        # 获取名称
        raw_name = info.get("longName") or info.get("shortName") or symbol
        name = raw_name
        
        # 如果是 A股/ETF，尝试用 akshare 获取确切名称
        if is_a_share:
            import akshare as ak
            code = ''.join(filter(str.isdigit, symbol))
            if len(code) == 6:
                found_name = None
                # 判断是否为 ETF
                if code.startswith(('15', '51', '56', '58')):
                    try:
                        df_etf = ak.fund_etf_spot_em()
                        match = df_etf[df_etf['代码'] == code]
                        if not match.empty:
                            found_name = match.iloc[0]['名称']
                            sector = "ETF基金"
                            industry = "场内基金"
                    except:
                        pass
                if not found_name:
                    try:
                        df_stock = ak.stock_zh_a_spot_em()
                        match = df_stock[df_stock['代码'] == code]
                        if not match.empty:
                            found_name = match.iloc[0]['名称']
                    except:
                        pass
                
                if found_name:
                    name = found_name
                else:
                    # 最后的防御：如果 AkShare 失败且依然是英文名，强制翻译一次
                    if any(bad in name for bad in ["China", "Energy", "Engineering", "Corporation", "Ltd", "Inc"]):
                        name = _translate_to_chinese(name) or name
        
        currency = info.get("currency", "USD")
        if currency == "CNY": currency = "人民币 (CNY)"
        exchange = info.get("exchange", "未知交易所")

        # 2. 写入/更新缓存 (使用查询更新模式以适配 SQLite 唯一索引)
        try:
            existing_meta = db.query(database.StockMetadata).filter(database.StockMetadata.symbol == symbol).first()
            if existing_meta:
                existing_meta.name = name
                existing_meta.sector = sector
                existing_meta.industry = industry
                existing_meta.currency = currency
                existing_meta.exchange = exchange
                existing_meta.summary = summary
                existing_meta.updated_at = datetime.now()
            else:
                new_meta = database.StockMetadata(
                    symbol=symbol,
                    name=name,
                    sector=sector,
                    industry=industry,
                    currency=currency,
                    exchange=exchange,
                    summary=summary
                )
                db.add(new_meta)
            db.commit()
        except Exception as db_err:
            print(f"缓存持久化失败: {db_err}")
            db.rollback()

        return {
            "name": name,
            "sector": sector,
            "industry": industry,
            "currency": currency,
            "exchange": exchange,
            "summary": summary,
            "from_cache": False
        }
    except Exception as e:
        print(f"获取股票信息失败: {e}")
        return {"name": symbol, "sector": "N/A", "industry": "N/A", "summary": "无法获取详细信息。"}

@app.get("/api/backtest/history")
async def get_backtest_history(symbol: Optional[str] = None, current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """从数据库获取历史回测记录"""
    try:
        query = db.query(BacktestRun).filter(BacktestRun.user_id == current_user.id)
        if symbol:
            query = query.filter(BacktestRun.symbol == symbol)
        
        runs = query.order_by(BacktestRun.timestamp.desc()).limit(10).all()
        
        history = []
        for run in runs:
            history.append({
                "id": run.id,
                "symbol": run.symbol,
                "timestamp": run.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "config": json.loads(run.config_json) if run.config_json else {},
                "metrics": json.loads(run.metrics_json) if run.metrics_json else {}
            })
        return history
    finally:
        pass # db depends handles session

@app.delete("/api/backtest/history/{run_id}")
async def delete_backtest_run(run_id: int, current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """从数据库删除指定的回测记录"""
    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id, BacktestRun.user_id == current_user.id).first()
        if not run:
            raise HTTPException(status_code=404, detail="记录不存在或无权删除")
        
        # 删除关联的交易流水
        db.query(TradeLog).filter(TradeLog.run_id == run_id).delete()
        # 删除回测记录本身
        db.delete(run)
        db.commit()
        return {"message": "删除成功"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        pass

@app.get("/api/watchlist")
async def get_watchlist(current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """获取所有自选股 (包含中文名称)"""
    from database import StockMetadata
    
    # 使用 outerjoin 关联元数据缓存表
    results = db.query(database.Watchlist, StockMetadata.name).\
        outerjoin(StockMetadata, database.Watchlist.symbol == StockMetadata.symbol).\
        filter(database.Watchlist.user_id == current_user.id).all()
        
    return [
        {
            "symbol": item.symbol, 
            "name": name or item.symbol, 
            "added_at": item.added_at
        } for item, name in results
    ]

@app.post("/api/watchlist")
async def add_to_watchlist(symbol: str, current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """添加股票到自选"""
    from sqlalchemy import func
    symbol = symbol.strip().upper()
    try:
        # 检查是否已存在 (大小写不敏感检查)
        existing = db.query(database.Watchlist).filter(
            func.upper(database.Watchlist.symbol) == symbol, 
            database.Watchlist.user_id == current_user.id
        ).first()
        if existing:
            return {"message": "已在自选中"}
        
        item = Watchlist(symbol=symbol, user_id=current_user.id)
        db.add(item)
        db.commit()
        return {"message": "添加成功"}
    except IntegrityError:
        db.rollback()
        return {"message": "已在自选中"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/watchlist")
async def remove_from_watchlist(symbol: str = Query(...), current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """从自选移除股票 (Query参数增强版)"""
    from sqlalchemy import func
    original_symbol = symbol
    clean_symbol = symbol.strip().upper()
    
    try:
        # 调试日志：确认上下文
        all_mine = db.query(database.Watchlist).filter(database.Watchlist.user_id == current_user.id).all()
        log_msg = f"\n[DEBUG] {datetime.now()} | UserID: {current_user.id} | Symbol: '{clean_symbol}' | Mine: {[i.symbol for i in all_mine]}"
        print(log_msg)
        with open("/tmp/debug_quant.log", "a") as f:
            f.write(log_msg + "\n")

        # 1. 尝试精确大写匹配
        item = db.query(database.Watchlist).filter(
            func.upper(database.Watchlist.symbol) == clean_symbol, 
            database.Watchlist.user_id == current_user.id
        ).first()
        
        # 2. 如果没找到，尝试含糊匹配 (处理可能存在的后缀不一，如 159948.sz vs 159948)
        if not item:
            search_pattern = clean_symbol.split('.')[0] + "%"
            print(f"[DEBUG] 精确匹配失败，尝试前缀匹配: {search_pattern}")
            item = db.query(database.Watchlist).filter(
                database.Watchlist.symbol.ilike(search_pattern),
                database.Watchlist.user_id == current_user.id
            ).first()

        if not item:
            print(f"[DEBUG] 最终仍未找到匹配项。")
            raise HTTPException(status_code=404, detail=f"自选中未找到标的 {clean_symbol} 或无权操作")
        
        db.delete(item)
        db.commit()
        print(f"[DEBUG] 成功移除: {item.symbol}")
        return {"message": "移除成功"}
    except HTTPException as he:
        raise he
    except Exception as e:
        db.rollback()
        print(f"[DEBUG] 移除异常: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
