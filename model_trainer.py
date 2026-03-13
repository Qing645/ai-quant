import pandas as pd
import xgboost as xgb
from sklearn.metrics import accuracy_score
import joblib
import numpy as np

def _train_ensemble(X_train, y_train, windows):
    models = []
    n = len(X_train)
    for w_size in windows:
        start = max(0, n - w_size)
        X_w = X_train.iloc[start:]
        y_w = y_train.iloc[start:]
        m = xgb.XGBClassifier(
            n_estimators=70,
            max_depth=4,
            learning_rate=0.07,
            subsample=0.8,
            random_state=42,
            eval_metric='logloss'
        )
        m.fit(X_w, y_w)
        models.append(m)
    return models

def train_model(data_path, model_output_path, backtest_output_path="backtest_data.csv"):
    """
    模型训练 4.1 (加速集成版 - 提升覆盖率)
    """
    df = pd.read_csv(data_path)
    
    # 特征列定义 (同步 4.2 爆发力因子)
    feature_cols = [
        'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'volatility', 
        'atr_20', 'body_size', 'upper_shadow', 'vol_ratio', 'bb_p', 'roc',
        'obv_roc', 'vpt_roc', 'vol_spike', 'momentum_accel'
    ]
    
    X = df[feature_cols].copy()
    y = df['target']
    
    mask = X.notna().all(axis=1) & y.notna()
    X_labeled = X[mask]
    y_labeled = y[mask]
    
    # Rolling Ensemble 架构
    windows = [120, 250, 500]
    min_train = min(windows)
    print(f"滚动集成训练启动4.2 - 样本: {len(X_labeled)}")

    # Walk-forward 预测，避免 in-sample 泄漏
    X_full = X[X.notna().all(axis=1)]
    y_full = y.loc[X_full.index]
    probs = pd.Series(index=X_full.index, dtype=float)

    for i in range(min_train, len(X_full)):
        X_train = X_full.iloc[:i]
        y_train = y_full.iloc[:i]
        models = _train_ensemble(X_train, y_train, windows)
        p = 0.0
        for m in models:
            p += m.predict_proba(X_full.iloc[[i]])[:, 1][0]
        probs.iloc[i] = p / len(models)

    # 丢弃未预测的前置窗口
    valid_probs = probs.dropna()
    final_probs = valid_probs.values

    # 策略激进化调整：由 85% -> 72% 进一步捕捉机会
    threshold = np.percentile(final_probs, 72) if len(final_probs) else 0.5
    if threshold < 0.35: threshold = 0.35
    elif threshold > 0.55: threshold = 0.55

    y_pred = (final_probs >= threshold).astype(int)

    if len(valid_probs):
        accuracy = accuracy_score(y_full.loc[valid_probs.index], y_pred)
        print(f"模型集成评估准确率: {accuracy:.2f} | 信号数: {y_pred.sum()}")
    else:
        print("模型集成评估准确率: N/A | 信号数: 0")

    # 保存全量训练模型供实时推理使用
    final_models = _train_ensemble(X_full, y_full, windows)
    joblib.dump(final_models, model_output_path)

    test_df = df.loc[valid_probs.index].copy()
    test_df['predicted_signal'] = y_pred
    test_df['prediction_prob'] = final_probs # 关键：透传概率
    test_df.to_csv(backtest_output_path, index=False)
    print(f"集成完成，{backtest_output_path} 已更新。平均概率已注入。")


if __name__ == "__main__":
    try:
        train_model("processed_data.csv", "quant_model.joblib")
    except FileNotFoundError:
        print("请检查 processed_data.csv 是否存在。")
