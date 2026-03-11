import pandas as pd
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import joblib
import numpy as np

def train_model(data_path, model_output_path, backtest_output_path="backtest_data.csv"):
    """
    模型训练 4.1 (加速集成版 - 提升覆盖率)
    """
    df = pd.read_csv(data_path)
    
    # 特征列定义 (同步 4.1 召回的 OBV/VPT)
    feature_cols = [
        'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'volatility', 
        'body_size', 'upper_shadow', 'vol_ratio', 'bb_p', 'roc',
        'obv_roc', 'vpt_roc'
    ]
    
    X = df[feature_cols].copy()
    y = df['target']
    
    mask = X.notna().all(axis=1) & y.notna()
    X_labeled = X[mask]
    y_labeled = y[mask]
    
    # Rolling Ensemble 架构
    windows = [120, 250, 500]
    models = []
    
    print(f"滚动集成训练启动4.1 - 样本: {len(X_labeled)}")
    
    for w_size in windows:
        train_idx = X_labeled.index[max(0, len(X_labeled) - w_size):]
        X_w = X_labeled.loc[train_idx]
        y_w = y_labeled.loc[train_idx]
        
        m = xgb.XGBClassifier(
            n_estimators=60,
            max_depth=4,
            learning_rate=0.08,
            subsample=0.8,
            random_state=42,
            eval_metric='logloss'
        )
        m.fit(X_w, y_w)
        models.append(m)

    # 预测全量有效样本
    X_full = X[X.notna().all(axis=1)]
    final_probs = np.zeros(len(X_full))
    
    for m in models:
        final_probs += m.predict_proba(X_full)[:, 1]
    
    final_probs /= len(models)
    
    # 策略激进化调整：由 85% -> 75% 提升捕捉率 (增加交易频率以博取更高累计收益)
    threshold = np.percentile(final_probs, 75)
    if threshold < 0.35: threshold = 0.35
    elif threshold > 0.55: threshold = 0.55
    
    y_pred = (final_probs >= threshold).astype(int)
    
    accuracy = accuracy_score(y_labeled, models[-1].predict(X_labeled))
    print(f"模型集成评估准确率: {accuracy:.2f} | 信号数: {y_pred.sum()}")
    
    joblib.dump(models, model_output_path)
    
    test_df = df.loc[X_full.index].copy()
    test_df['predicted_signal'] = y_pred
    test_df.to_csv(backtest_output_path, index=False)
    print(f"集成完成，{backtest_output_path} 已更新。阈值: {threshold:.3f}")


if __name__ == "__main__":
    try:
        train_model("processed_data.csv", "quant_model.joblib")
    except FileNotFoundError:
        print("请检查 processed_data.csv 是否存在。")
