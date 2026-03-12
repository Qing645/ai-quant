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

def run_backtest(data_path, output_metrics_path="metrics.json", output_trades_path="trades.json", 
                 initial_capital=10000.0, stop_loss=-0.05, grace_period=3, pos_ratio=1.0, max_account_drawdown=0.2, 
                 use_atr_stop=False, symbol="UNKNOWN", user_id=None):
    """
    运行策略回测并计算专业绩效指标 (风控强化版)
    """
    df = pd.read_csv(data_path)
    if 'date' not in df.columns and 'Date' in df.columns:
        df['date'] = df['Date']
        
    initial_capital = float(initial_capital)
    capital = initial_capital
    position = 0.0
    sell_signal_count = 0 
    entry_price = 0.0
    
    portfolio_values = []
    trades = []
    
    # 强制转换参数类型
    stop_loss = float(stop_loss)
    grace_period = int(grace_period)
    pos_ratio = float(pos_ratio)
    max_account_drawdown = float(max_account_drawdown)
    use_atr_stop = str(use_atr_stop).lower() == 'true'
    
    # --- 交易成本配置 ---
    COMMISSION_RATE = 0.00025  # 万 2.5
    MIN_COMMISSION = 5.0      # A 股佣金起步价
    STAMP_DUTY_RATE = 0.001    # 印花税 (仅卖出收取)
    SLIPPAGE_RATE = 0.0005     # 滑点干扰 (0.05%)
    
    # 判断是否为 ETF
    is_etf = any(symbol.startswith(pre) for pre in ['15', '51', '56', '58'])
    if is_etf:
        STAMP_DUTY_RATE = 0.0
        MIN_COMMISSION = 0.0
    
    # --- 策略状态增强 ---
    peak_price_since_entry = 0.0
    account_peak = initial_capital
    is_halted = False # 账户风险熔断状态
    halt_days_remaining = 0 # 冷静期计数器
    
    # 预计算 120 日均线用于趋势择时
    df['ma_120'] = df['close'].rolling(window=120).mean()
    loss_threshold = abs(float(stop_loss))
    
    for i in range(len(df)):
        # 更新熔断冷静期
        if halt_days_remaining > 0:
            halt_days_remaining -= 1
        is_halted = (halt_days_remaining > 0)
        current_price = float(df.iloc[i]['close'])
        signal = int(df.iloc[i]['predicted_signal'])
        current_date = str(df.iloc[i]['date'])
        ma_120 = df.iloc[i]['ma_120']
        atr = float(df.iloc[i].get('atr_20', 0))
        
        # 计算当前账户总资产
        current_value = capital + (position * current_price)
        portfolio_values.append(current_value)
        
        # 1. 账户风险熔断检查
        account_peak = max(account_peak, current_value)
        account_drawdown = (account_peak - current_value) / (account_peak + 1e-8)
        
        if not is_halted and account_drawdown > max_account_drawdown:
            halt_days_remaining = 20 # 20天冷静期
            is_halted = True
            if position > 0:
                # 触发熔断，立即平仓
                exec_price = current_price * (1 - SLIPPAGE_RATE)
                gross_amount = position * exec_price
                commission = max(MIN_COMMISSION, gross_amount * COMMISSION_RATE) if not is_etf else gross_amount * COMMISSION_RATE
                stamp_duty = gross_amount * STAMP_DUTY_RATE
                capital += gross_amount - (commission + stamp_duty) 
                position = 0
                trades.append({
                    "date": current_date,
                    "type": "SELL",
                    "price": round(exec_price, 4),
                    "reason": "Dynamic Circuit Breaker (20d cooling)",
                    "fee": round(commission + stamp_duty, 2)
                })
            # 重置峰值，准备在冷静期后重新计算基准
            account_peak = current_value
        
        if is_halted:
            continue

        # 2. 持仓中更新最高价 (用于移动止损)
        if position > 0:
            peak_price_since_entry = max(peak_price_since_entry, current_price)
            
        # 3. 交易执行逻辑
        if signal == 1:
            # 趋势择时过滤
            trend_ok = not pd.isna(ma_120) and current_price > ma_120
            
            if position == 0 and trend_ok:
                exec_price = current_price * (1 + SLIPPAGE_RATE)
                # 仓位比例控制逻辑：仅投入 capital * pos_ratio 的资金
                invest_amount = capital * pos_ratio
                if invest_amount > MIN_COMMISSION:
                    position = (invest_amount - MIN_COMMISSION if not is_etf else invest_amount) / exec_price
                    real_commission = max(MIN_COMMISSION, invest_amount * COMMISSION_RATE) if not is_etf else invest_amount * COMMISSION_RATE
                    capital = capital - (position * exec_price) - real_commission
                    entry_price = exec_price
                    peak_price_since_entry = exec_price 
                    sell_signal_count = 0
                    trades.append({
                        "date": current_date,
                        "type": "BUY",
                        "price": round(exec_price, 4),
                        "reason": f"AI Signal (Pos:{int(pos_ratio*100)}%)",
                        "fee": round(real_commission, 2)
                    })
            else:
                sell_signal_count = 0
                
        elif position > 0:
            # A. 移动止损 (Trailing Stop)
            trailing_stop_triggered = current_price < peak_price_since_entry * (1 - loss_threshold)
            
            # B. 利润垫保护: 盈利超过 10% 后，回落至 5% 强平 (锁定利润)
            profit_pct = (current_price - entry_price) / (entry_price + 1e-8)
            protect_profit = (profit_pct < 0.05 and peak_price_since_entry > entry_price * 1.10)
            
            # C. AI 信号离场 (含宽限期)
            sell_signal_count += 1
            signal_exit = (signal == 0 and sell_signal_count >= grace_period)
            
            # D. ATR 动态止损 (Adaptive ATR Stop)
            # 规则：价格跌破 entry - 2.5 * ATR 为自适应止损点
            atr_stop_triggered = use_atr_stop and atr > 0 and current_price < (entry_price - 2.5 * atr)
            
            # E. 固定百分比硬止损
            hard_stop = not use_atr_stop and current_price < entry_price * (1 - loss_threshold)

            if trailing_stop_triggered or protect_profit or signal_exit or atr_stop_triggered or hard_stop:
                reason = "Trailing Stop" if trailing_stop_triggered else \
                         ("Protect Profit" if protect_profit else \
                         ("ATR Stop" if atr_stop_triggered else \
                         ("AI Signal" if signal_exit else "Hard Stop")))
                
                exec_price = current_price * (1 - SLIPPAGE_RATE)
                gross_amount = position * exec_price
                commission = max(MIN_COMMISSION, gross_amount * COMMISSION_RATE) if not is_etf else gross_amount * COMMISSION_RATE
                stamp_duty = gross_amount * STAMP_DUTY_RATE
                total_fee = commission + stamp_duty
                
                capital += gross_amount - total_fee # 修复：应该是增加资产，而非覆盖
                position = 0
                sell_signal_count = 0
                trades.append({
                    "date": current_date,
                    "type": "SELL",
                    "price": round(exec_price, 4),
                    "reason": reason,
                    "fee": round(total_fee, 2)
                })
        else:
            sell_signal_count = 0

    # --- 计算绩效指标 ---
    if not portfolio_values: return {}
    
    returns = pd.Series(portfolio_values).pct_change().dropna()
    total_return = (portfolio_values[-1] - initial_capital) / initial_capital
    annual_return = (1 + total_return) ** (252.0 / len(df)) - 1 if len(df) > 252 else total_return
    
    #夏普比率
    sharpe_ratio = 0
    if len(returns) > 1:
        risk_free = 0.03 / 252
        std = returns.std()
        if std > 1e-9:
            sharpe_ratio = np.sqrt(252) * (returns.mean() - risk_free) / std
    
    peak = pd.Series(portfolio_values).cummax()
    drawdown = (pd.Series(portfolio_values) - peak) / peak
    max_dd = drawdown.min()
    
    # 胜率计算
    win_rate = 0
    if len(trades) >= 2:
        trade_returns = []
        for i in range(1, len(trades)):
            if trades[i]['type'] == 'SELL' and trades[i-1]['type'] == 'BUY':
                trade_returns.append((trades[i]['price'] - trades[i-1]['price']) / trades[i-1]['price'])
        if trade_returns:
            win_rate = len([r for r in trade_returns if r > 0]) / len(trade_returns)

    metrics = {
        "total_return": round(total_return * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 2),
        "max_drawdown": round(float(max_dd) * 100, 2),
        "win_rate": round(win_rate * 100, 2),
        "circuit_breaker": is_halted,
        "final_value": round(portfolio_values[-1], 2),
        "trade_count": len(trades)
    }

    # 保存结果 (风控参数入库)
    config = {
        "stop_loss": stop_loss,
        "grace_period": grace_period,
        "pos_ratio": pos_ratio,
        "max_account_drawdown": max_account_drawdown,
        "use_atr_stop": use_atr_stop
    }
    save_backtest_to_db(symbol, config, metrics, trades, user_id=user_id)
    
    # 兼容性文件保存
    with open(output_metrics_path, 'w') as f: json.dump(metrics, f)
    with open(output_trades_path, 'w') as f: json.dump(trades, f)
    
    print(f"回测完成。夏普: {metrics['sharpe_ratio']}, 回撤: {metrics['max_drawdown']}%")
    return metrics

def run_portfolio_backtest(data_map, output_metrics_path="portfolio_metrics.json", output_trades_path="portfolio_trades.json",
                           initial_capital=10000.0, stop_loss=-0.05, grace_period=3, pos_ratio=1.0, max_account_drawdown=0.2,
                           use_atr_stop=False, user_id=None):
    """
    运行多标的组合回测 (统一本金池版)
    :param data_map: dict {symbol: data_path}
    """
    # 1. 加载并对齐所有数据
    dfs = {}
    all_dates = set()
    for s, path in data_map.items():
        _df = pd.read_csv(path)
        if 'date' not in _df.columns and 'Date' in _df.columns: _df['date'] = _df['Date']
        _df['ma_120'] = _df['close'].rolling(window=120).mean()
        dfs[s] = _df.set_index('date')
        all_dates.update(_df['date'].tolist())
    
    sorted_dates = sorted(list(all_dates))
    
    # 2. 状态初始化
    initial_capital = float(initial_capital)
    capital = initial_capital
    portfolio_state = {s: {"position": 0.0, "entry_price": 0.0, "peak_price": 0.0, "sell_count": 0} for s in data_map}
    
    portfolio_values = []
    all_trades = []
    is_halted = False
    halt_days_remaining = 0  # 冷静期计数器
    account_peak = initial_capital
    loss_threshold = abs(float(stop_loss))
    
    # 交易常数 (根据单标的逻辑对齐)
    COMMISSION_RATE = 0.00025
    STAMP_DUTY_RATE = 0.001
    SLIPPAGE_RATE = 0.0005
    
    for current_date in sorted_dates:
        # 更新熔断冷静期状态
        if halt_days_remaining > 0:
            halt_days_remaining -= 1
        is_halted = (halt_days_remaining > 0)
        
        current_daily_value = capital
        potential_buys = []
        
        # A. 更新身价 & 检查卖出信号
        for s in data_map:
            if current_date not in dfs[s].index: continue
            
            row = dfs[s].loc[current_date]
            price = float(row['close'])
            signal = int(row['predicted_signal'])
            atr = float(row.get('atr_20', 0))
            ma_120 = row['ma_120']
            
            # 兼容 ETF 费用逻辑
            is_etf = any(s.startswith(pre) for pre in ['15', '51', '56', '58'])
            s_stamp = 0.0 if is_etf else STAMP_DUTY_RATE
            s_min_comm = 0.0 if is_etf else 5.0
            
            state = portfolio_state[s]
            if state["position"] > 0:
                current_daily_value += state["position"] * price
                state["peak_price"] = max(state["peak_price"], price)
                
                # 检查卖出条件（熔断后仍可止损/止盈平仓，但不接受新买入）
                trailing_stop = price < state["peak_price"] * (1 - loss_threshold)
                profit_protect = ( (price - state["entry_price"])/state["entry_price"] < 0.05 and state["peak_price"] > state["entry_price"] * 1.10 )
                
                state["sell_count"] = state["sell_count"] + 1 if signal == 0 else 0
                signal_exit = (signal == 0 and state["sell_count"] >= grace_period)
                atr_stop = use_atr_stop and atr > 0 and price < (state["entry_price"] - 2.5 * atr)
                hard_stop = not use_atr_stop and price < state["entry_price"] * (1 - loss_threshold)
                
                if trailing_stop or profit_protect or signal_exit or atr_stop or hard_stop:
                    # 执行卖出（不受熔断状态影响，止损始终生效）
                    reason = "Trailing Stop" if trailing_stop else ("Protect Profit" if profit_protect else ("ATR Stop" if atr_stop else ( "AI Signal" if signal_exit else "Hard Stop")))
                    exec_p = price * (1 - SLIPPAGE_RATE)
                    gross = state["position"] * exec_p
                    comm = max(s_min_comm, gross * COMMISSION_RATE)
                    duty = gross * s_stamp
                    capital += gross - (comm + duty)
                    
                    all_trades.append({
                        "date": current_date, "symbol": s, "type": "SELL", "price": round(exec_p, 4), "reason": reason, "fee": round(comm + duty, 2)
                    })
                    state["position"] = 0.0
            else:
                # 检查买入条件（仅在未熔断时才允许新建仓）
                trend_ok = not pd.isna(ma_120) and price > ma_120
                if signal == 1 and trend_ok and not is_halted:
                    potential_buys.append((s, price, is_etf, s_min_comm))

        # B. 账户风险熔断检查
        portfolio_values.append(current_daily_value)
        account_peak = max(account_peak, current_daily_value)
        account_drawdown = (account_peak - current_daily_value) / (account_peak + 1e-8)
        
        if not is_halted and account_drawdown > max_account_drawdown:
            halt_days_remaining = 20 # 进入 20 个交易日的冷静期
            is_halted = True
            
            # 强制清空组合
            for s in data_map:
                state = portfolio_state[s]
                if state["position"] > 0:
                    row = dfs[s].loc[current_date]
                    p = float(row['close'])
                    is_etf = any(s.startswith(pre) for pre in ['15', '51', '56', '58'])
                    duty = 0 if is_etf else p * state["position"] * STAMP_DUTY_RATE
                    comm = 0 if is_etf else 5.0 
                    capital += (state["position"] * p * (1 - SLIPPAGE_RATE)) - (comm + duty)
                    all_trades.append({
                        "date": current_date, "symbol": s, "type": "SELL", "price": round(p, 4), "reason": "Dynamic Circuit Breaker (20d cooling)", "fee": round(comm + duty, 2)
                    })
                    state["position"] = 0.0
            
            # 关键：熔断触发后重置最高点，确保冷静期结束后是以当前净值为新基准重新计算风险
            account_peak = current_daily_value
                    
        # C. 执行买入 (资金分配：若多个信号，平分可用投资资金)
        if potential_buys and not is_halted:
            # 计算本次可总投入资金
            total_invest_budget = capital * pos_ratio
            for s, p, is_etf, s_min_comm in potential_buys:
                if portfolio_state[s]["position"] > 0: continue # 已持有
                
                # 每个标的分到的预算
                s_budget = total_invest_budget / len(potential_buys)
                if s_budget > s_min_comm + 100: # 至少有 100 元可用
                    exec_p = p * (1 + SLIPPAGE_RATE)
                    s_pos = (s_budget - s_min_comm) / exec_p
                    s_comm = max(s_min_comm, s_budget * COMMISSION_RATE)
                    
                    capital -= (s_pos * exec_p) + s_comm
                    portfolio_state[s].update({"position": s_pos, "entry_price": exec_p, "peak_price": exec_p, "sell_count": 0})
                    all_trades.append({
                        "date": current_date, "symbol": s, "type": "BUY", "price": round(exec_p, 4), "reason": f"Portfolio Entry (Ratio:{int(pos_ratio*100/len(potential_buys))}%)", "fee": round(s_comm, 2)
                    })

    # 4. 计算组合绩效
    if not portfolio_values: return {}
    final_v = portfolio_values[-1]
    total_r = (final_v - initial_capital) / initial_capital
    
    # 简单计算夏普 (基于日收益率)
    rets = pd.Series(portfolio_values).pct_change().dropna()
    sr = 0
    if len(rets) > 1 and rets.std() > 1e-9:
        sr = np.sqrt(252) * (rets.mean() - 0.03/252) / rets.std()
    
    peak = pd.Series(portfolio_values).cummax()
    mdd = ((pd.Series(portfolio_values) - peak) / peak).min()
    
    metrics = {
        "total_return": round(total_r * 100, 2),
        "sharpe_ratio": round(float(sr), 2),
        "max_drawdown": round(float(mdd) * 100, 2),
        "final_value": round(final_v, 2),
        "trade_count": len(all_trades),
        "is_portfolio": True
    }
    
    # 保存结果
    save_backtest_to_db("PORTFOLIO", {"stop_loss": stop_loss, "pos_ratio": pos_ratio}, metrics, all_trades, user_id=user_id)
    with open(output_metrics_path, 'w') as f: json.dump(metrics, f)
    with open(output_trades_path, 'w') as f: json.dump(all_trades, f)
    
    # 新增：保存组合净值曲线 CSV (供前端图表渲染)
    nav_df = pd.DataFrame({
        "date": sorted_dates,
        "portfolio_value": portfolio_values
    })
    nav_df.to_csv("portfolio_nav.csv", index=False)
    
    print(f"组合回测完成。夏普: {metrics['sharpe_ratio']}, 回撤: {metrics['max_drawdown']}%")
    return metrics

if __name__ == "__main__":
    # 示例用法
    try:
        # run_backtest("backtest_data.csv")
        # 组合测试示例
        if os.path.exists("backtest_data.csv"):
            run_portfolio_backtest({"159948.SZ": "backtest_data.csv"})
    except Exception as e:
        print(f"运行失败: {e}")
