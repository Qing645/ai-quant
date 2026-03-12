import pandas as pd
import numpy as np

def prepare_features(df, prediction_window=10):
    """
    特征工程 4.0 (专业量化因子库)
    """
    # 确保列名正确且为小写
    if df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df.columns = [str(col).lower() for col in df.columns]
    
    # --- 基础指标 ---
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=7).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=7).mean()
    rs = gain / (loss + 1e-8)
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()

    # ATR (Average True Range) - 用于风控止损
    high_low = df['high'] - df['low']
    high_pc = (df['high'] - df['close'].shift()).abs()
    low_pc = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_pc, low_pc], axis=1).max(axis=1)
    df['atr_20'] = tr.rolling(window=20, min_periods=5).mean()
    
    # 动量与趋势偏离
    df['roc'] = df['close'].pct_change(periods=10)
    sma_20 = df['close'].rolling(window=20, min_periods=5).mean()
    df['sma_20_dist'] = (df['close'] - sma_20) / (sma_20 + 1e-8)
    
    # --- 新增：专业量化因子 ---
    
    # 1. 历史波动率 (Ann. Volatility 20d)
    df['volatility'] = df['close'].pct_change().rolling(window=20).std() * np.sqrt(252)
    
    # 2. K 线结构特征 (微观动能)
    df['body_size'] = (df['close'] - df['open']).abs() / (df['high'] - df['low'] + 1e-8)
    df['upper_shadow'] = (df['high'] - df[['open', 'close']].max(axis=1)) / (df['high'] - df['low'] + 1e-8)
    
    # 3. 成交量特征增强
    vol_ma_20 = df['volume'].rolling(window=20, min_periods=5).mean()
    df['vol_ratio'] = df['volume'] / (vol_ma_20 + 1e-8)
    
    # 4. 价格位置
    std_20 = df['close'].rolling(window=20, min_periods=5).std()
    bb_upper = sma_20 + (std_20 * 2)
    bb_lower = sma_20 - (std_20 * 2)
    df['bb_p'] = (df['close'] - bb_lower) / (bb_upper - bb_lower + 1e-8)
    
    # 5. 动量特征增强 (从 3.0 召回获利因子)
    obv_raw = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
    df['obv_roc'] = obv_raw.pct_change(periods=10).fillna(0)
    vpt_raw = (df['volume'] * (df['close'].diff() / (df['close'].shift() + 1e-8))).fillna(0).cumsum()
    df['vpt_roc'] = vpt_raw.pct_change(periods=10).fillna(0)
    
    # 6. 生成高质量波段标签 (Sharpe-Oriented Labeling)
    window = int(prediction_window)
    target_up = 0.05 if window >= 10 else 0.035
    target_down = -0.06 # 加大回撤容忍度，捕捉深度蹲坑后的爆发
    
    future_max = df['high'].rolling(window=window, min_periods=1).max().shift(-window)
    future_min = df['low'].rolling(window=window, min_periods=1).min().shift(-window)
    
    up_move = (future_max - df['close']) / (df['close'] + 1e-8)
    down_move = (future_min - df['close']) / (df['close'] + 1e-8)
    
    # 标签生成
    df['target'] = ((up_move > target_up) & (down_move > target_down)).astype(int)
    
    # 特征库全家桶
    feature_cols = [
        'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'volatility', 
        'atr_20', 'body_size', 'upper_shadow', 'vol_ratio', 'bb_p', 'roc',
        'obv_roc', 'vpt_roc'
    ]
    df[feature_cols] = df[feature_cols].bfill().ffill()
    df.replace([np.inf, -np.inf], 0, inplace=True)
    df.dropna(subset=feature_cols, inplace=True)
    
    return df

if __name__ == "__main__":
    try:
        raw_data = pd.read_csv("stock_data.csv")
        processed_data = prepare_features(raw_data)
        processed_data.to_csv("processed_data.csv", index=False)
        print("特征工程完成，已保存至 processed_data.csv")
    except FileNotFoundError:
        print("请先运行 data_fetcher.py 下载数据。")
