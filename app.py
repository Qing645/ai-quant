from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError
import pandas as pd
import os
import json
from typing import Optional
from datetime import datetime
import database
from database import SessionLocal, BacktestRun, TradeLog, Watchlist, init_db

import data_fetcher
import feature_engineer
import model_trainer
import backtest_engine
import auth
from auth import get_current_user
from sqlalchemy.orm import Session

app = FastAPI(title="Local AI Quant API")

# 初始化数据库
init_db()

# 允许跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

@app.get("/api/health")
def health_check():
    return {"status": "healthy"}

@app.post("/api/auth/send-code")
async def send_code(email: str = Query(...), db: Session = Depends(database.get_db)):
    """生成验证码并模拟发送"""
    import random
    from datetime import datetime, timedelta
    
    # 简单的邮箱格式校验
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
async def register(email: str = Query(...), password: str = Query(...), code: str = Query(...), db: Session = Depends(database.get_db)):
    """用户注册 (基于邮件验证码)"""
    from datetime import datetime
    try:
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
async def login(email: str = Query(...), password: str = Query(...), db: Session = Depends(database.get_db)):
    """用户登录 (支持邮箱)"""
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
    prediction_days: int = 10,
    stop_loss: float = -0.05,
    grace_period: int = 3,
    current_user: database.User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    一键运行完整量化管线
    """
    try:
        # 标准化日期格式
        start = start.replace("/", "-")
        end = end.replace("/", "-")
        
        # 修正 yfinance 排他性：将 end 日期加 1 天以包含 endDate 当天的数据
        from datetime import datetime, timedelta
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        fetch_end = (end_dt + timedelta(days=1)).strftime("%Y-%m-%d")
        
        # 1. 下载数据
        data_fetcher.fetch_data(symbol, start, fetch_end, DATA_FILE)
        
        # 2. 特征工程 (传入动态预测窗口)
        raw_df = pd.read_csv(DATA_FILE)
        processed_df = feature_engineer.prepare_features(raw_df, prediction_window=prediction_days)
        processed_df.to_csv(PROCESSED_FILE, index=False)
        
        # 3. 模型训练
        model_trainer.train_model(PROCESSED_FILE, MODEL_FILE)
        
        # 4. 专业回测 (传入止损和宽限期与用户ID)
        backtest_engine.run_backtest(
            BACKTEST_FILE, 
            METRICS_FILE, 
            TRADES_FILE,
            stop_loss=stop_loss,
            grace_period=grace_period,
            symbol=symbol,
            user_id=current_user.id
        )
        
        return {"message": "Pipeline completed successfully", "symbol": symbol}
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_detail)

@app.get("/api/data/chart")
def get_chart_data():
    """
    获取图表展示数据
    """
    from fastapi.responses import Response
    import math
    
    if not os.path.exists(BACKTEST_FILE):
        raise HTTPException(status_code=404, detail="Backtest data not found.")
    
    df = pd.read_csv(BACKTEST_FILE)
    # 替换 Inf/-Inf 为 NaN，然后清洗为 None
    df = df.replace([float('inf'), float('-inf')], float('nan'))
    
    # 手动将每行数据转成 Python 原生类型，避免 numpy float64 导致序列化失败
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
    """获取标的分时数据，并附加昨收价信息"""
    try:
        data = data_fetcher.fetch_intraday_data(symbol)
        quote = data_fetcher.fetch_realtime_quote(symbol)
        prev_close = quote.get('prev_close', 0) if quote else 0
        return {"data": data, "prev_close": prev_close}
    except Exception as e:
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
        print(f"翻译失败: {e}")
    return text

@app.get("/api/realtime/check")
async def check_realtime_signal(symbol: str = "159915.SZ"):
    """
    实时扫描：结合历史数据与即时价格，给出此时此刻的 AI 诊断
    """
    import joblib
    import numpy as np
    
    if not os.path.exists(MODEL_FILE) or not os.path.exists(DATA_FILE):
        return {"status": "error", "message": "模型或历史数据未就绪，请先运行回测。"}
        
    try:
        # 1. 获取实时行情
        quote = data_fetcher.fetch_realtime_quote(symbol)
        if not quote:
            return {"status": "error", "message": "无法获取实时行情"}
            
        # 2. 读取最近的历史数据 (至少需要 60 天来计算特征)
        hist_df = pd.read_csv(DATA_FILE)
        
        # 3. 将实时点拼接到历史数据末端
        # 如果实时点日期与历史最后一天相同，则替换最后一天，否则追加
        if hist_df.iloc[-1]['date'] == quote['date']:
            hist_df.iloc[-1, hist_df.columns.get_loc('close')] = quote['close']
            hist_df.iloc[-1, hist_df.columns.get_loc('high')] = max(hist_df.iloc[-1]['high'], quote['high'])
            hist_df.iloc[-1, hist_df.columns.get_loc('low')] = min(hist_df.iloc[-1]['low'], quote['low'])
            hist_df.iloc[-1, hist_df.columns.get_loc('volume')] = quote['volume']
        else:
            new_row = pd.DataFrame([quote])
            hist_df = pd.concat([hist_df, new_row], ignore_index=True)
            
        # 4. 重新计算特征 (实时行情下，特征会受到最新价格博弈影响)
        processed_df = feature_engineer.prepare_features(hist_df.copy())
        
        # 5. 加载模型并推理
        model = joblib.load(MODEL_FILE)
        feature_cols = [
            'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'sma_50_dist', 'bb_width', 'bb_p',
            'vol_ratio', 'obv_roc', 'atr_ratio', 'roc', 'ema_dev', 'vpt_roc'
        ]
        
        # 检查特征是否对齐
        X_latest = processed_df[feature_cols].tail(1)
        prob = model.predict_proba(X_latest)[:, 1][0]
        
        # 获取阈值参考 (取最后 60 天预测概率的 80 分位作为动态基准)
        full_probs = model.predict_proba(processed_df[feature_cols])[:, 1]
        threshold = np.percentile(full_probs[-60:], 80)
        if threshold < 0.35: threshold = 0.35
        
        signal = 1 if prob >= threshold else 0
        
        return {
            "status": "success",
            "symbol": symbol,
            "current_price": round(quote['close'], 3),
            "change_pct": round(((quote['close'] - quote.get('prev_close', quote['open'])) / quote.get('prev_close', quote['open'])) * 100, 2) if quote.get('prev_close', quote['open']) != 0 else 0,
            "prev_close": round(quote.get('prev_close', quote['open']), 3),
            "ai_confidence": round(float(prob), 4),
            "threshold_ref": round(float(threshold), 4),
            "signal": signal,
            "action": "BUY (建议买入)" if signal == 1 else "HOLD/SELL (持币或减仓)",
            "updated_at": datetime.now().strftime("%H:%M:%S")
        }
        
    except Exception as e:
        return {"status": "error", "message": f"实时诊断失败: {str(e)}"}

@app.get("/api/stock/info")
def get_stock_info(symbol: str):
    """
    获取股票元数据并自动翻译业务摘要
    """
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
                elif any(ord(c) < 128 for c in str(raw_name)):
                    # 退回翻译逻辑
                    name = _translate_to_chinese(raw_name)
        else:
            has_english = any(ord(c) < 128 for c in str(raw_name))
            if is_a_share and has_english:  # fail-safe
                name = _translate_to_chinese(raw_name)

        currency = info.get("currency", "USD")
        if currency == "CNY": currency = "人民币 (CNY)"
        
        return {
            "name": name,
            "sector": sector,
            "industry": industry,
            "currency": currency,
            "exchange": info.get("exchange", "未知交易所"),
            "summary": summary
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
    """获取所有自选股"""
    items = db.query(Watchlist).filter(Watchlist.user_id == current_user.id).all()
    return [{"symbol": item.symbol, "added_at": item.added_at} for item in items]

@app.post("/api/watchlist")
async def add_to_watchlist(symbol: str, current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """添加股票到自选"""
    symbol = symbol.upper()
    try:
        # 检查是否已存在
        existing = db.query(Watchlist).filter(Watchlist.symbol == symbol, Watchlist.user_id == current_user.id).first()
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
    finally:
        db.close()

@app.delete("/api/watchlist/{symbol}")
async def remove_from_watchlist(symbol: str, current_user: database.User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """从自选移除股票"""
    symbol = symbol.upper()
    try:
        item = db.query(Watchlist).filter(Watchlist.symbol == symbol, Watchlist.user_id == current_user.id).first()
        if not item:
            raise HTTPException(status_code=404, detail="自选中未找到该标或无权操作")
        
        db.delete(item)
        db.commit()
        return {"message": "移除成功"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
