import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib

def train_model(data_path, model_output_path):
    """
    使用交易特征训练 XGBoost 分类模型
    """
    df = pd.read_csv(data_path)
    
    # 核心特征列 (需与 feature_engineer.py 3.0 保持同步)
    feature_cols = [
        'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'sma_50_dist', 'bb_width', 'bb_p',
        'vol_ratio', 'obv_roc', 'atr_ratio', 'roc', 'ema_dev', 'vpt_roc'
    ]
    
    # 检查特征是否齐全
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        print(f"提醒: 原始数据中缺失特征 {missing}，将尝试仅使用可用特征。可用列: {df.columns.tolist()}")
        feature_cols = [c for c in feature_cols if c in df.columns]

    X = df[feature_cols].copy()
    y = df['target']
    
    print(f"特征处理前样本数: {len(df)}")
    
    # 准备预测全集 (包含没有标签的最新数据)
    mask_features = X.notna().all(axis=1)
    X_full = X[mask_features]
    
    # 准备训练/测试集 (必须有标签)
    mask_train = mask_features & y.notna()
    X_labeled = X[mask_train]
    y_labeled = y[mask_train]
    
    print(f"特征完整样本数: {len(X_full)}, 其中有标签样本数: {len(X_labeled)}")
    
    if len(X_labeled) < 5: 
        msg = f"有效有标签样本量过少 ({len(X_labeled)})，无法训练模型。建议扩大日期范围。"
        print(f"致命错误: {msg}")
        raise ValueError(msg)
    
    # 划分训练集和测试集 (按时间序列)
    train_size = int(len(X_labeled) * 0.8)
    X_train, X_test_labeled = X_labeled.iloc[:train_size], X_labeled.iloc[train_size:]
    y_train, y_test_labeled = y_labeled.iloc[:train_size], y_labeled.iloc[train_size:]
    
    # 最终预测集定义为：全部有特征的样本（包含训练集+测试集+未标注的最新行情）
    # 这样 backtest_data.csv 会覆盖完整历史，让 K 线图从头到尾都显示买卖标记
    X_final_test = X_full  # 全量数据预测
    
    # 初始化并训练模型 (优化版参数)
    model = xgb.XGBClassifier(
        n_estimators=100,      # 增加树的数量
        max_depth=4,           # 允许更深的决策树
        learning_rate=0.05,    # 降低学习率以更精细地拟合
        subsample=0.8,         # 增加子采样防止过拟合
        colsample_bytree=0.8,
        random_state=42,
        use_label_encoder=False,
        eval_metric='logloss'
    )
    
    print(f"训练启动 - 有标签样本: {len(X_labeled)}, 训练集: {len(X_train)}, 测试集: {len(X_test_labeled)}")
    model.fit(X_train, y_train)
    
    import numpy as np
    # 对全量数据预测概率
    probs = model.predict_proba(X_final_test)[:, 1]
    
    # 滚动自适应阈值逻辑：按每 60 天滑动窗口，各自取该区间内预测概率的 Top 20%
    # 好处：无论模型对某段行情整体置信度高还是低，都会在每段时期释放适量信号
    # 避免了全局阈值导致模型对近期行情置信度低而产生空窗期的问题
    window_size = 60  # 每 60 个交易日独立计算阈值
    y_pred = np.zeros(len(probs), dtype=int)
    n = len(probs)
    for i in range(0, n, window_size):
        end = min(i + window_size, n)
        window_probs = probs[i:end]
        # 取本窗口内前 20% 的日期作为买入信号
        local_threshold = np.percentile(window_probs, 80)
        # 安全下限：模型对这段行情最高置信度都 < 0.30，说明彻底无把握，跳过
        if local_threshold < 0.30:
            local_threshold = 0.30
        y_pred[i:end] = (window_probs >= local_threshold).astype(int)
    
    # 单独评估：在有标签的测试集上计算准确率（排除训练集内拟合的虚高准确率）
    probs_labeled = model.predict_proba(X_test_labeled)[:, 1]
    global_threshold = np.percentile(probs_labeled, 80)
    if global_threshold > 0.55: global_threshold = 0.55
    elif global_threshold < 0.30: global_threshold = 0.30
    y_pred_labeled = (probs_labeled >= global_threshold).astype(int)
    accuracy = accuracy_score(y_test_labeled, y_pred_labeled)
    
    print(f"模型评估准确率 (Accuracy): {accuracy:.2f}")
    print(f"生成的买入信号数量: {int(y_pred.sum())}")
    
    # 保存模型
    joblib.dump(model, model_output_path)
    print(f"模型已保存为: {model_output_path}")
    
    # 为回测准备预测结果 (使用 X_full 全量切片，覆盖完整历史)
    test_df = df.loc[X_final_test.index].copy()
    test_df['predicted_signal'] = y_pred
    test_df.to_csv("backtest_data.csv", index=False)
    print(f"预测数据已保存至: backtest_data.csv (包含 {len(test_df)} 条，含最新行情)")

if __name__ == "__main__":
    try:
        train_model("processed_data.csv", "quant_model.joblib")
    except FileNotFoundError:
        print("请检查 processed_data.csv 是否存在。")
