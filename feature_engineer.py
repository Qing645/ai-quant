import pandas as pd
import numpy as np

def prepare_features(df, prediction_window=10):
    """
    手动实现技术指标计算，移除 pandas-ta 依赖
    """
    # 确保列名正确且为小写
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    df.columns = [str(col).lower() for col in df.columns]
    
    # 3. 技术指标计算 (增强鲁棒性：使用 min_periods 防止数据过少被丢弃)
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=7).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=7).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # MACD & 动量 (Momentum)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    
    # 新增：价格变化率 (ROC) - 衡量动量
    df['roc'] = df['close'].pct_change(periods=10)
    # 新增：均线偏离度 (EMA Cross Deviation)
    df['ema_short'] = df['close'].ewm(span=9, adjust=False).mean()
    df['ema_long'] = df['close'].ewm(span=26, adjust=False).mean()
    df['ema_dev'] = (df['ema_short'] - df['ema_long']) / df['ema_long']
    
    # 移动平均线 - 转换为相对偏离度 (Distance from Price)
    sma_20 = df['close'].rolling(window=20, min_periods=5).mean()
    sma_50 = df['close'].rolling(window=50, min_periods=5).mean()
    df['sma_20_dist'] = (df['close'] - sma_20) / sma_20
    df['sma_50_dist'] = (df['close'] - sma_50) / sma_50
    
    # 布林带 - 转换为宽度 (Width) 和 价格位置 (B% )
    std_20 = df['close'].rolling(window=20, min_periods=5).std()
    bb_upper = sma_20 + (std_20 * 2)
    bb_lower = sma_20 - (std_20 * 2)
    df['bb_width'] = (bb_upper - bb_lower) / sma_20
    df['bb_p'] = (df['close'] - bb_lower) / (bb_upper - bb_lower + 1e-8)
    
    # 平均真实波幅率 (ATR Ratio) - 适配不同面值
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = tr.rolling(window=14, min_periods=7).mean()
    df['atr_ratio'] = df['atr'] / df['close']
    
    # 4. 成交量特征 (Relative Volume Quality)
    # 成交量相对于均线的比例
    vol_ma_20 = df['volume'].rolling(window=20, min_periods=5).mean()
    df['vol_ratio'] = df['volume'] / (vol_ma_20 + 1e-8)
    
    # 能量潮 (OBV) - 转换为 10 日变化率，避免绝对值无限增大
    obv_raw = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
    df['obv_roc'] = obv_raw.pct_change(periods=10).fillna(0)
    
    # 量价趋势 (VPT) - 同样转换为相对变化
    vpt_raw = (df['volume'] * (df['close'].diff() / df['close'].shift())).fillna(0).cumsum()
    df['vpt_roc'] = vpt_raw.pct_change(periods=10).fillna(0)

    # 5. 生成高质量波段标签 (Quality Labeling 4.0 - 震荡容忍版)
    # 逻辑：未来 N 天最高价涨幅 > target_up 且 期间最低价跌幅 < target_down 的严苛度下降
    window = int(prediction_window)
    # 动态调整门槛：时间越长，要求越高。放宽由于 A 股波动剧烈导致的回撤容忍度 (-2% -> -6%)
    target_up = 0.06 if window >= 10 else 0.04
    target_down = -0.06 if window >= 10 else -0.04
    
    future_max = df['high'].rolling(window=window, min_periods=1).max().shift(-window)
    future_min = df['low'].rolling(window=window, min_periods=1).min().shift(-window)
    
    up_move = (future_max - df['close']) / df['close']
    down_move = (future_min - df['close']) / df['close']
    
    # 核心要求：中线有足够上涨潜力，且底线（期间最大下杀）在可承受的范围（如 -6%）内
    df['target'] = ((up_move > target_up) & (down_move > target_down)).astype(int)
    
    # 兜底：如果样本太少(新股或极度震荡导致连 -6% 都防不住)，退一步只看是否有上涨动能
    if df['target'].sum() < 5:
        print(f"警告：窗口 {window} 的标准样本过少，已退化为仅考虑上涨潜力的宽松标签策略。")
        df['target'] = (up_move > 0.04).astype(int)
    
    # 最终统一处理缺失值
    # 注意：不要对 target 进行 ffill，预测日没有未来标签是正常的
    # 仅对技术指标特征进行填充
    feature_cols = [
        'rsi', 'macd', 'macd_signal', 'sma_20_dist', 'sma_50_dist', 'bb_width', 'bb_p',
        'vol_ratio', 'obv_roc', 'atr_ratio', 'roc', 'ema_dev', 'vpt_roc'
    ]
    df[feature_cols] = df[feature_cols].bfill().ffill()
    df.replace([np.inf, -np.inf], 0, inplace=True) # 处理 pct_change 可能产生的 inf
    
    # 丢弃特征不全的行 (如上市初期)，但保留 target 为空的行用于后续预测
    df.dropna(subset=feature_cols, inplace=True)
    
    # 确保所有特征列为数值型
    for col in feature_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df.dropna(subset=feature_cols, inplace=True)
    
    if df.empty:
        print("警告: 特征工程后数据集为空，可能是因为数据条数少于技术指标所需的窗口长度 (如 50 日均线)。")
    
    return df

if __name__ == "__main__":
    try:
        raw_data = pd.read_csv("stock_data.csv")
        processed_data = prepare_features(raw_data)
        processed_data.to_csv("processed_data.csv", index=False)
        print("特征工程完成，已保存至 processed_data.csv")
    except FileNotFoundError:
        print("请先运行 data_fetcher.py 下载数据。")
