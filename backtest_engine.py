import pandas as pd
import numpy as np
import json
import os
from database import SessionLocal, BacktestRun, TradeLog, init_db

def save_backtest_to_db(symbol, config, metrics, trades, user_id=None):
    """持久化回测结果与流水"""
    init_db()
    db = SessionLocal()
    try:
        # 1. 记录回测总成绩
        run = BacktestRun(
            user_id=user_id,
            symbol=symbol,
            config_json=json.dumps(config),
            metrics_json=json.dumps(metrics)
        )
        db.add(run)
        db.flush() # 获取生成的 run.id
        
        # 2. 记录每一笔交易
        log_records = []
        for t in trades:
            log = TradeLog(
                run_id=run.id,
                symbol=symbol,
                date=t['date'],
                type=t['type'],
                price=t['price'],
                reason=t.get('reason', 'Signal')
            )
            log_records.append(log)
        
        db.bulk_save_objects(log_records)
        db.commit()
        print(f"回测结果已入库 (UserID: {user_id}, RunID: {run.id}, Trades: {len(log_records)})")
    except Exception as e:
        db.rollback()
        print(f"回测结果入库失败: {e}")
    finally:
        db.close()

def run_backtest(data_path, output_metrics_path="metrics.json", output_trades_path="trades.json", stop_loss=-0.05, grace_period=3, symbol="UNKNOWN", user_id=None):
    """
    运行策略回测并计算专业绩效指标
    """
    df = pd.read_csv(data_path)
    if 'date' not in df.columns and 'Date' in df.columns:
        df['date'] = df['Date']
        
    initial_capital = 10000.0
    capital = initial_capital
    position = 0.0
    sell_signal_count = 0 
    entry_price = 0.0
    
    portfolio_values = []
    trades = []
    
    # 强制转换参数类型
    stop_loss = float(stop_loss)
    grace_period = int(grace_period)
    
    for i in range(len(df)):
        current_price = float(df.iloc[i]['close'])
        signal = int(df.iloc[i]['predicted_signal'])
        current_date = str(df.iloc[i]['date'])
        
        # 优化交易逻辑 4.0 (波段保护)
        if signal == 1:
            if position == 0:
                # 买入
                position = capital / current_price
                entry_price = current_price
                capital = 0
                sell_signal_count = 0
                trades.append({
                    "date": current_date,
                    "type": "BUY",
                    "price": round(current_price, 2),
                    "remaining_capital": round(capital, 2),
                    "reason": "AI Signal"
                })
            else:
                # 持仓中看到买入信号，重置卖出计数器
                sell_signal_count = 0
                
        elif signal == 0 and position > 0:
            # 卖出判断：引入宽限期与硬止损
            sell_signal_count += 1
            
            # 条件 1: 止损触发 (使用动态参数)
            stop_loss_triggered = current_price < entry_price * (1 + stop_loss)
            # 条件 2: 趋势反转确认 (使用动态参数)
            trend_reversal = sell_signal_count >= grace_period
            
            if stop_loss_triggered or trend_reversal:
                reason = "Stop Loss" if stop_loss_triggered else "Trend Reversal"
                # 卖出执行
                capital = position * current_price
                position = 0
                sell_signal_count = 0
                trades.append({
                    "date": current_date,
                    "type": "SELL",
                    "price": round(current_price, 2),
                    "remaining_capital": round(capital, 2),
                    "reason": reason
                })
        else:
            # 信号为 0 且无持仓，重置
            sell_signal_count = 0
            
        current_value = capital + (position * current_price)
        portfolio_values.append(current_value)
    
    df['portfolio_value'] = portfolio_values
    
    # --- 计算绩效指标 ---
    returns = pd.Series(portfolio_values).pct_change().dropna()
    
    # 1. 累计收益
    total_return = (portfolio_values[-1] - initial_capital) / initial_capital
    
    # 2. 年化收益 (假设一年 252 个交易日)
    annual_return = (1 + total_return) ** (252.0 / len(df)) - 1 if len(df) > 0 else 0
    
    # 3. 夏普比率 (无风险利率假设 3%)
    if len(trades) > 0 and len(returns) > 1:
        risk_free = 0.03 / 252
        excess_returns = returns - risk_free
        std = excess_returns.std()
        if std > 1e-9: # 增加阈值检查，防止极小值导致的溢出
            sharpe_ratio = np.sqrt(252) * excess_returns.mean() / std
        else:
            sharpe_ratio = 0
    else:
        sharpe_ratio = 0
    
    # 4. 最大回撤
    peak = pd.Series(portfolio_values).cummax()
    drawdown = (pd.Series(portfolio_values) - peak) / peak
    max_drawdown = drawdown.min()
    
    # 5. 胜率 & 盈亏比
    if len(trades) >= 2:
        profits = []
        losses = []
        for i in range(1, len(trades), 2): # 假设 SELL 紧跟在 BUY 之后
             if trades[i]['type'] == 'SELL':
                 trade_return = (trades[i]['price'] - trades[i-1]['price']) / trades[i-1]['price']
                 if trade_return > 0:
                     profits.append(trade_return)
                 else:
                     losses.append(abs(trade_return))
        
        win_rate = len(profits) / (len(profits) + len(losses)) if (len(profits) + len(losses)) > 0 else 0
        
        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else (float('inf') if avg_profit > 0 else 0)
    else:
        win_rate = 0
        profit_loss_ratio = 0

    metrics = {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 2),
        "max_drawdown": round(float(max_drawdown) * 100, 2),
        "win_rate": round(win_rate * 100, 2),
        "profit_loss_ratio": round(float(profit_loss_ratio), 2) if profit_loss_ratio != float('inf') else "∞",
        "final_value": round(portfolio_values[-1], 2),
        "trade_count": len(trades)
    }
    
    # 准备持久化配置
    config = {
        "stop_loss": stop_loss,
        "grace_period": grace_period
    }
    
    # 保存结果到数据库 (新持久化层)
    save_backtest_to_db(symbol, config, metrics, trades, user_id=user_id)
        
    # 保存结果到文件 (保持旧版本兼容)
    with open(output_metrics_path, 'w') as f:
        json.dump(metrics, f)
    with open(output_trades_path, 'w') as f:
        json.dump(trades, f)
        
    df.to_csv(data_path, index=False)
    print(f"回测完成。夏普比率: {metrics['sharpe_ratio']}, 最大回撤: {metrics['max_drawdown']}%")
    return metrics

if __name__ == "__main__":
    try:
        run_backtest("backtest_data.csv")
    except FileNotFoundError:
        print("请检查 backtest_data.csv 是否存在。")
