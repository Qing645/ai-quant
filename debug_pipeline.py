import os
import pandas as pd
import data_fetcher
import feature_engineer
import model_trainer
import backtest_engine
import traceback

def debug():
    symbol = "159948.SZ,600036.SH"
    start = "2024-01-01"
    end = "2026-03-12"
    prediction_days = 10
    
    symbols = [s.strip().upper() for s in symbol.split(",")]
    symbol_data_map = {}
    
    try:
        for s in symbols:
            print(f"Testing {s}...")
            s_data_file = f"data_{s}.csv"
            s_processed_file = f"processed_{s}.csv"
            s_model_file = f"model_{s}.joblib"
            s_backtest_file = f"backtest_{s}.csv"
            
            # Step 1
            data_fetcher.fetch_data(s, start, end, s_data_file)
            
            # Step 2
            raw_df = pd.read_csv(s_data_file)
            print(f"  Raw data rows: {len(raw_df)}")
            processed_df = feature_engineer.prepare_features(raw_df, prediction_window=prediction_days)
            processed_df.to_csv(s_processed_file, index=False)
            
            # Step 3
            model_trainer.train_model(s_processed_file, s_model_file, s_backtest_file)
            symbol_data_map[s] = s_backtest_file
            
        # Step 4
        print("Running Portfolio Backtest...")
        backtest_engine.run_portfolio_backtest(
            symbol_data_map,
            "debug_metrics.json",
            "debug_trades.json",
            initial_capital=10000.0,
            user_id=1
        )
        print("Debug Success!")
    except Exception:
        print("\n=== DEBUG ERROR TRACEBACK ===")
        traceback.print_exc()

if __name__ == "__main__":
    debug()
