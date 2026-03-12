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
    reasons = [t.get('reason', '未知理由') for t in trades if t['type'] == 'SELL']
    if reasons:
        reason_counts = pd.Series(reasons).value_counts()
        report.append("\n#### [REASONS] 核心离场归因统计")
        for r_name, count in reason_counts.items():
            pct = round(count / len(reasons) * 100, 1)
            # 兼容中英文标签
            desc = ""
            if "Hard Stop" in r_name or "止损" in r_name: desc = "固定比例止损"
            elif "Trailing" in r_name or "移动" in r_name: desc = "追踪止盈保护"
            elif "ATR" in r_name: desc = "波动率自适应离场"
            elif "Signal" in r_name or "信号" in r_name: desc = "AI 模型预测翻转"
            elif "Profit" in r_name or "利润" in r_name: desc = "利润垫保护离场"
            elif "Melt" in r_name or "熔断" in r_name: desc = "账户级风险防线"
            
            report.append(f"- **{r_name}**：触发 {count} 次，占比 {pct}%。({desc})")

    # 5. 专家建议
    report.append("\n#### [ADVICE] 专家调优建议")
    advice_list = []
    
    # 针对暴涨前早撤的专项逻辑
    signal_exits = reason_counts.get("AI 信号离场", 0) + reason_counts.get("AI Signal", 0)
    if signal_exits > len(reasons) * 0.6 and total_return < 10:
        advice_list.append("📌 **核心优化**：模型频繁在趋势初期离场。建议检查 `grace_period` 参数，或开启加速期`动态宽限期补偿`，防止被启动前的震荡洗出。")

    # 风险类建议
    if abs(max_dd) > 10:
        advice_list.append("🔴 **风险警示**：最大回撤超过 10%。建议调低 `pos_ratio` 至 0.6 以下，确保极端行情下的本金安全。")
    if win_rate < 45:
        advice_list.append("🟡 **胜率缺陷**：当前胜率不够理想。建议增加 `prediction_days` 训练时长，让模型学习更长周期的特征稳定性。")
    
    # 手法建议
    if "固定百分比硬止损" in reasons or "Hard Stop" in reasons:
        advice_list.append("🟢 **技术建议**：硬性止损触发频繁。建议切换至 `ATR 动态止损` 模式，利用波动率自适应调整间距。")
    
    # 常驻建议
    advice_list.append("🔵 **常规提醒**：回测仅代表历史表现，实盘需关注成交滑点及模型在极端行情下的信号滞后。")
    
    for advice in advice_list:
        report.append(f"- {advice}")
        
    return "\n".join(report)
        
    return "\n".join(report)

if __name__ == "__main__":
    m = {"total_return": 15.5, "sharpe_ratio": 1.2, "max_drawdown": -12.3, "win_rate": 55.0, "trade_count": 24}
    t = [{"type": "SELL", "reason": "Hard Stop"}, {"type": "SELL", "reason": "Trailing Stop"}]
    print(generate_analysis_report(m, t))
