from sqlalchemy import create_engine, Column, Integer, Float, String, Text, DateTime, Index, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# 数据库连接配置 (未来迁移服务器只需更改此 URL)
DB_PATH = "quant.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True)
    email = Column(String(100), unique=True, index=True) # 新增邮箱字段
    hashed_password = Column(String(100))
    created_at = Column(DateTime, default=datetime.now)
    
    watchlist = relationship("Watchlist", back_populates="user")
    backtests = relationship("BacktestRun", back_populates="user")

class VerificationCode(Base):
    """验证码和临时申领表"""
    __tablename__ = "verification_codes"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(100), index=True)
    code = Column(String(10))
    expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)

class OHLCVData(Base):
    """历史与实时价量表"""
    __tablename__ = "ohlcv_data"
    
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), index=True)
    date = Column(String(20), index=True)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    
    # 唯一索引确保不重复存储同一标的同一天的数据
    __table_args__ = (Index('ix_symbol_date', 'symbol', 'date', unique=True),)

class BacktestRun(Base):
    """回测记录表"""
    __tablename__ = "backtest_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    symbol = Column(String(20), index=True)
    timestamp = Column(DateTime, default=datetime.now)
    config_json = Column(Text)  # 保存止损、窗口等配置
    metrics_json = Column(Text) # 保存累计收益、夏普等指标

    user = relationship("User", back_populates="backtests")

class TradeLog(Base):
    """成交流水表"""
    __tablename__ = "trade_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, index=True)
    symbol = Column(String(20))
    date = Column(String(20), index=True)
    type = Column(String(10))  # BUY / SELL
    price = Column(Float)
    reason = Column(String(50)) # AI_SIGNAL / STOP_LOSS / REVERSAL

class Watchlist(Base):
    """自选股表"""
    __tablename__ = "watchlist"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    symbol = Column(String(20), index=True)
    added_at = Column(DateTime, default=datetime.now)
    
    user = relationship("User", back_populates="watchlist")
    
    # 每个用户对同一只股票只能添加一次
    __table_args__ = (Index('ix_user_symbol', 'user_id', 'symbol', unique=True),)

# 初始化数据库
def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    print(f"数据库 {DB_PATH} 初始化成功。")
