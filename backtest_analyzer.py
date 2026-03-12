import json
import pandas as pd

def generate_analysis_report(metrics, trades):
    """
    基于回测数据生成专业智能分析报告
    """
    report = []
    
    # 1. 总体表现概览
    total_return = metrics.get('total_return', 0)
    sharpe = metrics.get('sharpe_ratio', 0)
    max_dd = metrics.get('max_drawdown', 0)
    
    if total_return > 20:
        perf_status = "卓越"
        perf_msg = "本次策略表现**极佳**，展现了强大的超额收益能力，大幅跑赢市场基准。"
    elif total_return > 0:
        perf_status = "稳健"
        perf_msg = "本次策略表现**稳健**，在控制风险的前提下成功实现正向盈利。"
    else:
        perf_status = "待优化"
        perf_msg = "本次策略目前处于**亏损状态**，净值回撤明显，核心参数亟需根据市场环境进行调校。"
    
    report.append(f"### [SUMMARY] {perf_status}")
    report.append(perf_msg)
    
    # 2. 核心指标面板 (前端会将其渲染为网格)
    report.append("\n#### [METRICS] 风险稳定性评估")
    
    # 夏普评分
    if sharpe > 2:
        sharpe_eval = "极高收益风险比"
    elif sharpe > 1:
        sharpe_eval = "风险收益平衡"
    else:
        sharpe_eval = "效率较低"
    report.append(f"- 夏普比率 | {sharpe} | {sharpe_eval}")
        
    # 回撤评分
    if abs(max_dd) < 10:
        dd_eval = "极低回撤风险"
    elif abs(max_dd) < 20:
        dd_eval = "回撤控制尚可"
    else:
        dd_eval = "回撤压力巨大"
    report.append(f"- 最大回撤 | {max_dd}% | {dd_eval}")

    # 3. 交易行为特征
    report.append("\n#### [ANALYSIS] 交易行为深度透视")
    win_rate = metrics.get('win_rate', 0)
    trade_count = metrics.get('trade_count', 0)
    
    if trade_count > 50:
        freq_advice = "交易**过于频繁**，高昂的摩擦成本可能会严重侵蚀净值。建议增加 `grace_period` (信号平滑) 以过滤市场杂波。"
    elif trade_count < 10:
        freq_advice = "交易期**过于保守**，可能导致错失趋势性机会。建议检查 AI 阈值或尝试缩短预测周期。"
    else:
        freq_advice = "交易频率**适中**，进出场节奏与市场波动匹配度较高。"
    
    report.append(f"- **操作频率**：本次历史区间共执单 {trade_count} 次。{freq_advice}")
    report.append(f"- **获利胜率**：当前胜率为 {win_rate}%。{'胜率较高，具备一定的盈利确定性。' if win_rate > 50 else '胜率较低，主要依靠大额盈利覆盖小额亏损，对止损要求严苛。'}")
    
    # 4. 离场归因
    reasons = [t['reason'] for t in trades if t['type'] == 'SELL']
    if reasons:
        reason_counts = pd.Series(reasons).value_counts()
        report.append("\n#### [REASONS] 核心离场归因统计")
        for r_name, count in reason_counts.items():
            pct = round(count / len(reasons) * 100, 1)
            desc = ""
            if r_name == "Hard Stop":
                desc = "固定比例止损"
            elif r_name == "Trailing Stop":
                desc = "移动保护触发"
            elif r_name == "ATR Stop":
                desc = "波动率自适应止损"
            elif r_name == "AI Signal":
                desc = "策略模型翻转离场"
            elif r_name == "Protect Profit":
                desc = "利润垫锁死离场"
            elif r_name == "Dynamic Circuit Breaker":
                desc = "账户级强行风险熔断"
            
            report.append(f"- **{r_name} ({desc})**：触发 {count} 次，占比 {pct}%。")

    # 5. 专家建议
    report.append("\n#### [ADVICE] 专家调优建议")
    advice_list = []
    
    # 风险类建议 (降低门槛)
    if abs(max_dd) > 10:
        advice_list.append("🔴 **风险警示**：当前最大回撤已超过 10%。建议调低 `pos_ratio` (仓位占比) 至 0.5 左右，并检查是否开启了 `use_atr_stop`。")
    if win_rate < 45:
        advice_list.append("🟡 **逻辑调优**：胜率低于 45%，策略容错率较低。可尝试增加 `prediction_days` 以捕捉更长期的趋势信号。")
    
    # 行为类建议
    if trade_count > 40:
        advice_list.append("⚪ **成本提醒**：交易频率较高。请务必确认 `grace_period` (平滑期) 至少为 3，以减少无效波动引起的调仓损耗。")
    
    # 手法建议
    if "Hard Stop" in reasons and reason_counts.get("Hard Stop", 0) > len(reasons) * 0.3:
        advice_list.append("🟢 **技术建议**：硬止损触发频繁。建议切换为 `ATR 动态止损`，给标的留出更合理的波动空间。")
    
    # 常驻建议 (确保不为空)
    advice_list.append("🔵 **常规提醒**：回测结果未包含实盘滑点与借贷成本，实际执行时请保留 10-15% 的利润冗余。")
    
    for advice in advice_list:
        report.append(f"- {advice}")
        
    return "\n".join(report)

if __name__ == "__main__":
    m = {"total_return": 15.5, "sharpe_ratio": 1.2, "max_drawdown": -12.3, "win_rate": 55.0, "trade_count": 24}
    t = [{"type": "SELL", "reason": "Hard Stop"}, {"type": "SELL", "reason": "Trailing Stop"}]
    print(generate_analysis_report(m, t))
