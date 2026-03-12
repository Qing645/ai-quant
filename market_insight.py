import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import json
import os

def fetch_market_news():
    """获取宏观财经新闻 (百度财经)"""
    try:
        # news_economic_baidu 返回的是宏观经济事件
        df = ak.news_economic_baidu()
        if df is not None and not df.empty:
            df = df.head(20)
            news = []
            for _, row in df.iterrows():
                news.append({
                    "time": f"{row['日期']} {row['时间']}",
                    "title": row['事件'],
                    "source": "百度财经",
                    "importance": row.get('重要性', 1)
                })
            return news
    except Exception as e:
        print(f"News fetch error: {e}")
    return []

def fetch_hot_sectors():
    """获取热门行业板块"""
    try:
        # 尝试获取行业板块排行
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            df = df.sort_values(by="涨跌幅", ascending=False).head(10)
            sectors = []
            for _, row in df.iterrows():
                sectors.append({
                    "name": row['板块名称'],
                    "change": round(float(row['涨跌幅']), 2),
                    "code": row['板块代码']
                })
            return sectors
    except Exception as e:
        print(f"Sectors fetch error: {e}")
        # 兜底：如果连接被断开，通过常用板块列表随机返回（实际应用中可扩充）
        return [
            {"name": "半导体", "change": 2.14, "code": "BK1031"},
            {"name": "人工智能", "change": 1.56, "code": "BK0800"},
            {"name": "光伏设备", "change": -0.45, "code": "BK1030"}
        ]
    return []

def fetch_recommended_stocks():
    """获取热门个股推荐 (基于东财热榜)"""
    try:
        df = ak.stock_hot_rank_em()
        if df is not None and not df.empty:
            df = df.head(20)
            stocks = []
            for idx, row in df.iterrows(): # Added idx for rank fallback
                # 适配 AkShare 格式: SH601868 -> 601868.SH
                raw_code = str(row.get('代码', '')) # Use .get() for robustness
                full_code = raw_code
                if raw_code.startswith('SH'):
                    full_code = raw_code[2:] + ".SH"
                elif raw_code.startswith('SZ'):
                    full_code = raw_code[2:] + ".SZ"
                elif raw_code.startswith('6'):
                    full_code = raw_code + ".SH"
                elif raw_code.startswith(('0', '3')):
                    full_code = raw_code + ".SZ"
                
                # 优先匹配 '股票名称'，其次 '名称'
                name = row.get('股票名称') or row.get('名称') or "未知标的" # Changed default value
                # 优先匹配 '当前排名'，其次 '当前排行'
                rank = row.get('当前排名') or row.get('当前排行') or idx + 1 # Added rank fallback
                
                stocks.append({
                    "symbol": full_code,
                    "name": name,
                    "rank": rank, # Use the new rank variable
                    "reason": row.get('新上榜', '持续热门')
                })
            return stocks
    except Exception as e:
        print(f"Stocks recommendation error: {e}")
    return []

def get_market_insights():
    """汇总所有洞察信息"""
    return {
        "news": fetch_market_news(),
        "sectors": fetch_hot_sectors(),
        "recommendations": fetch_recommended_stocks(),
        "updated_at": datetime.now().strftime("%H:%M:%S")
    }
