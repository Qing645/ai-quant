# AI Quant Model

这是一个 AI 量化模型架构，使用 XGBoost 进行股价趋势预测，并集成 AkShare 获取 A 股及 ETF 高精度数据。项目包含后端 FastAPI 接口和前端 Vue3 交互式大盘。

## 🚀 启动指南

### 1. 环境准备

建议使用 Python 3.9+。

#### 后端环境

```bash
# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

#### 前端环境

需要 Node.js 环境（建议 v18+）。

```bash
cd frontend
npm install
```

### 2. 启动服务

项目需要同时启动后端和前端服务。

#### 第一步：启动后端 API (Port: 8000)

```bash
# 在项目根目录下执行
source venv/bin/activate
python app.py
```

#### 第二步：启动前端看板 (Port: 5173)

```bash
# 在另外一个终端窗口中执行
cd frontend
npm run dev
```

### 3. 开始使用

- 打开浏览器访问 `http://localhost:5173`。
- 在控制面板输入股票代码（例如 `159915.SZ` 或 `600519.SH`）。
- 点击“开始回测”，系统将自动完成：数据下载 -> 特征工程 -> 模型训练 -> 策略预测 -> 结果展示。

## 📂 核心模块说明

- `data_fetcher.py`: 集成 AkShare/YFinance 的双引擎数据采集。
- `feature_engineer.py`: 高级特征工程（相对比例特征、动量、波动率及 Quality Labeling 4.0）。
- `model_trainer.py`: XGBoost 模型训练与动态滚动阈值预测。
- `backtest_engine.py`: 包含止损机制与趋势反转判断的回测引擎。
- `app.py`: FastAPI 后端服务，提供全流程自动化管线接口。
- `frontend/`: 基于 Vue3 + ECharts 的响应式量化分析分析看板。
