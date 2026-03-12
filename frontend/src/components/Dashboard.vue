<script setup lang="ts">
import { ref, onMounted, nextTick, computed } from "vue";
import * as echarts from "echarts";
import {
  Play,
  TrendingUp,
  Cpu,
  BarChart3,
  Loader2,
  List,
  Activity,
  DollarSign,
  Award,
  ShieldAlert,
  Trash2,
  Star,
  Info,
  Globe2,
  ChevronRight
} from "lucide-vue-next";

const chartRef = ref<HTMLElement | null>(null);
const isLoading = ref(false);
const symbol = ref("");
const startDate = ref("2024-01-01");
const endDate = ref(new Date().toISOString().split("T")[0]);
const metrics = ref({
  total_return: 0,
  annual_return: 0,
  sharpe_ratio: 0,
  max_drawdown: 0,
  win_rate: 0,
  profit_loss_ratio: 0,
  trade_count: 0,
  final_value: 0
});
const trades = ref<any[]>([]);
const stockInfo = ref({
  name: "",
  sector: "",
  industry: "",
  currency: "",
  exchange: "",
  summary: ""
});
const statusMsg = ref("就绪");
const initialCapital = ref(10000); // 初始本金
const predictionDays = ref(5);
const stopLoss = ref(-10); // 百分比显示，发送时除以 100
const gracePeriod = ref(3);
const posRatio = ref(1.0); // 仓位比例 0.1-1.0
const maxAccountDrawdown = ref(25); // 账户熔断阈值 %
const useAtrStop = ref(true); // 是否使用 ATR 动态止损
const lastSignal = ref({ date: "N/A", signal: 0, price: 0, status: "loading" });
const realtimeSignal = ref<any>(null);
const backtestHistory = ref<any[]>([]);
const watchlist = ref<any[]>([]);
const chartMode = ref<"daily" | "intraday">("daily");
const intradayData = ref<any[]>([]);
const prevCloseRef = ref(0); // 独立管理分时图昨收价
const isIntradayLoading = ref(false);
const isWatchlistLoading = ref(false);
const isStockInfoLoading = ref(false);
const isChartDataLoading = ref(false);
const isMetricsLoading = ref(false);
const isTradesLoading = ref(false);
const isSignalLoading = ref(false);
const isHistoryLoading = ref(false);
const analysisReport = ref("");
const marketInsights = ref<any>({ news: [], sectors: [], recommendations: [] });
const isInsightsLoading = ref(false);
let realtimeTimer: any = null;

// 通用带鉴权的请求方法
const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
  const token = localStorage.getItem("token");
  const headers = {
    ...options.headers,
    Authorization: token ? `Bearer ${token}` : ""
  };

  const res = await fetch(url, { ...options, headers });

  if (res.status === 401) {
    // Token 失效或未登录，清理并刷新页面触发 App.vue 的跳转
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    window.location.reload();
    throw new Error("请重新登录");
  }

  return res;
};

let myChart: echarts.ECharts | null = null;

const formattedReport = computed(() => {
  if (!analysisReport.value) return "";

  const lines = analysisReport.value.split(/\r?\n/);
  let html = "";
  let insideMetrics = false;

  lines.forEach((rawLine) => {
    const line = rawLine.trim();
    if (!line) {
      if (insideMetrics) {
        html += `</div>`;
        insideMetrics = false;
      }
      return;
    }

    // 1. 总体评价总结栏 [SUMMARY]
    if (line.includes("[SUMMARY]")) {
      const statusMatch = line.match(/\[SUMMARY\]\s*(.*)/);
      const status = statusMatch ? statusMatch[1].trim() : "分析中";
      const colorClass =
        status === "卓越"
          ? "text-emerald-400 border-emerald-500/30"
          : status === "稳健"
            ? "text-blue-400 border-blue-500/30"
            : "text-amber-400 border-amber-500/30";
      html += `<div class="mb-8 p-0 bg-white/5 rounded-2xl border ${colorClass} flex items-center justify-between overflow-hidden">
                <div class="px-4 py-3 flex flex-col gap-1">
                  <span class="text-[10px] font-bold opacity-40 uppercase tracking-widest">总体评价状态</span>
                  <span class="text-lg font-black ${colorClass}">${status}</span>
                </div>
                <div class="px-6 py-3 bg-white/5 h-full flex items-center">
                   <Activity class="w-5 h-5 opacity-20" />
                </div>
              </div>`;
      return;
    }

    // 2. 标题处理 (使用正则匹配行首 #)
    if (line.startsWith("####")) {
      insideMetrics = line.includes("[METRICS]");
      const cleanTitle = line.replace(/^####\s*(\[.*?\])?\s*/, "").trim();
      html += `<h4 class="flex items-center gap-2 text-sm font-black text-indigo-300 mt-8 mb-4 uppercase tracking-tighter">
                <span class="w-1.5 h-4 bg-indigo-500 rounded-full"></span> ${cleanTitle}
               </h4>`;
      if (insideMetrics) {
        html += `<div class="grid grid-cols-2 gap-4 mb-6">`;
      }
      return;
    }

    if (line.startsWith("###")) {
      const cleanTitle = line.replace(/^###\s*(\[.*?\])?\s*/, "").trim();
      html += `<h3 class="text-lg font-black text-emerald-400 mt-6 mb-3 uppercase">${cleanTitle}</h3>`;
      return;
    }

    // 3. 指标项处理 (仅在 METRICS 区间)
    if (insideMetrics && line.startsWith("- ")) {
      const parts = line.replace("- ", "").split(" | ");
      if (parts.length >= 3) {
        html += `<div class="p-4 bg-white/5 rounded-2xl border border-white/5 hover:border-indigo-500/20 transition-all">
                  <div class="text-[10px] text-slate-500 font-bold uppercase mb-1">${parts[0]}</div>
                  <div class="flex items-baseline gap-2">
                    <span class="text-lg font-mono font-black text-white">${parts[1]}</span>
                    <span class="text-[10px] text-indigo-400 font-medium">${parts[2]}</span>
                  </div>
                </div>`;
      }
      return;
    } else if (insideMetrics && !line.trim()) {
      html += `</div>`; // 关闭网格
      insideMetrics = false;
      return;
    }

    // 4. 普通列表项和正文
    if (line.startsWith("- ")) {
      const content = line.replace("- ", "");
      html += `<div class="flex gap-3 mb-4 last:mb-0">
                <div class="w-1.5 h-1.5 rounded-full bg-indigo-500/40 mt-2 shrink-0"></div>
                <p class="text-[13px] text-slate-300 leading-relaxed">${content}</p>
              </div>`;
    } else if (line.trim()) {
      html += `<p class="text-sm text-slate-200 leading-loose mb-4">${line}</p>`;
    }
  });

  // 安全关闭可能未关闭的网格
  if (insideMetrics) html += `</div>`;

  // 全局加粗处理
  return html.replace(
    /\*\*(.*?)\*\*/g,
    '<strong class="text-emerald-400 font-bold">$1</strong>'
  );
});

const handleWatchlistClick = async (targetSymbol: string) => {
  symbol.value = targetSymbol;
  if (chartMode.value === "intraday") {
    // 分时模式：仅拉取最新数据和行情
    fetchStockInfo();
    fetchIntradayData();
    fetchRealtimeCheck(); // 触发一次实时获取
  } else {
    // 日线模式：默认重新运行回测管线以获得最新 AI 信号
    runPipeline();
  }
};

const runPipeline = async () => {
  if (!symbol.value.trim()) {
    alert("请输入股票代码 (例如: 159948.SZ)");
    return;
  }
  isLoading.value = true;
  statusMsg.value = `正在下载 ${symbol.value} 数据并运行管线...`;
  try {
    const params = new URLSearchParams({
      symbol: symbol.value,
      start: startDate.value,
      end: endDate.value,
      initial_capital: initialCapital.value.toString(),
      prediction_days: predictionDays.value.toString(),
      stop_loss: (stopLoss.value / 100).toString(),
      grace_period: gracePeriod.value.toString(),
      pos_ratio: posRatio.value.toString(),
      max_account_drawdown: (maxAccountDrawdown.value / 100).toString(),
      use_atr_stop: useAtrStop.value.toString()
    });

    const res = await fetchWithAuth(`/api/run-pipeline?${params.toString()}`, {
      method: "POST"
    });
    const resData = await res.json();
    if (resData.status === "success") {
      analysisReport.value = resData.report || "";
      statusMsg.value = "回测完成，正在同步数据...";
    } else {
      throw new Error(resData.detail || "管线运行失败");
    }

    await Promise.all([
      fetchStockInfo(),
      fetchChartData(),
      fetchMetrics(),
      fetchTrades(),
      fetchLastSignal(),
      fetchHistory()
    ]);
    startRealtimeMonitor();
    statusMsg.value = "已更新";
  } catch (err: any) {
    console.error("Pipeline failed:", err);
    statusMsg.value = `错误: ${err.message}`;
    alert(
      `回测失败: ${err.message}\n提示: 如果样本量过少，请尝试扩大日期范围。`
    );
  } finally {
    isLoading.value = false;
  }
};

const fetchMarketInsights = async () => {
  try {
    isInsightsLoading.value = true;
    const res = await fetchWithAuth("/api/market/insights");
    marketInsights.value = await res.json();
  } catch (err) {
    console.error("获取市场洞察失败", err);
  } finally {
    isInsightsLoading.value = false;
  }
};

const fetchStockInfo = async () => {
  try {
    const res = await fetchWithAuth(`/api/stock/info?symbol=${symbol.value}`);
    stockInfo.value = await res.json();
  } catch (err) {
    console.error("获取股票信息失败", err);
  }
};

const fetchChartData = async () => {
  try {
    isChartDataLoading.value = true;
    const res = await fetchWithAuth("/api/data/chart");
    const data = await res.json();
    renderChart(data);
  } catch (err) {
    console.error("获取图表数据失败", err);
  } finally {
    isChartDataLoading.value = false;
  }
};

const fetchIntradayData = async () => {
  try {
    isIntradayLoading.value = true;
    const res = await fetchWithAuth(
      `/api/data/intraday?symbol=${symbol.value}`
    );
    const resData = await res.json();
    if (resData && Array.isArray(resData.data)) {
      intradayData.value = resData.data;
      if (resData.prev_close !== undefined && resData.prev_close !== null) {
        prevCloseRef.value = parseFloat(resData.prev_close);
      }
    } else {
      intradayData.value = resData;
    }
    renderChart(intradayData.value);
  } catch (err) {
    console.error("获取分时数据失败", err);
  } finally {
    isIntradayLoading.value = false;
  }
};

const setChartMode = (mode: "daily" | "intraday") => {
  chartMode.value = mode;
  if (mode === "daily") {
    fetchChartData();
  } else {
    fetchIntradayData();
  }
};

const fetchMetrics = async () => {
  try {
    isMetricsLoading.value = true;
    const res = await fetchWithAuth("/api/model/metrics");
    metrics.value = await res.json();
  } catch (err) {
    console.error("获取指标失败", err);
  } finally {
    isMetricsLoading.value = false;
  }
};

const fetchTrades = async () => {
  try {
    isTradesLoading.value = true;
    const res = await fetchWithAuth("/api/backtest/trades");
    const data = await res.json();
    trades.value = data.reverse(); // 最新的在上面
  } catch (err) {
    console.error("获取交易日志失败", err);
  } finally {
    isTradesLoading.value = false;
  }
};

const fetchLastSignal = async () => {
  try {
    isSignalLoading.value = true;
    const res = await fetchWithAuth("/api/last-signal");
    lastSignal.value = await res.json();
  } catch (err) {
    console.error("获取最新信号失败", err);
  } finally {
    isSignalLoading.value = false;
  }
};

const isTradingHours = () => {
  const now = new Date();
  const day = now.getDay();
  if (day === 0 || day === 6) return false; // 周末

  const time = now.getHours() * 100 + now.getMinutes();
  // 9:30-11:30, 13:00-15:00
  if ((time >= 930 && time <= 1130) || (time >= 1300 && time <= 1500)) {
    return true;
  }
  return false;
};

const fetchRealtimeCheck = async () => {
  if (!symbol.value) return;
  if (!isTradingHours()) {
    console.log("非交易时间，暂停获取实时行情。");
    return;
  }

  try {
    const res = await fetchWithAuth(
      `/api/realtime/check?symbol=${symbol.value}`
    );
    const data = await res.json();
    if (data.status === "success") {
      realtimeSignal.value = data;
      if (data.prev_close !== undefined && data.prev_close !== null) {
        prevCloseRef.value = parseFloat(data.prev_close);
      }
      // 如果在分时模式，自动刷新分时数据
      if (chartMode.value === "intraday") {
        const iRes = await fetchWithAuth(
          `/api/data/intraday?symbol=${symbol.value}`
        );
        const resData = await iRes.json();
        if (resData && Array.isArray(resData.data)) {
          intradayData.value = resData.data;
          if (resData.prev_close !== undefined && resData.prev_close !== null) {
            prevCloseRef.value = parseFloat(resData.prev_close);
          }
        } else {
          intradayData.value = resData;
        }
        renderChart(intradayData.value);
      }
    }
  } catch (err) {
    console.error("实时诊断失败", err);
  }
};

const startRealtimeMonitor = () => {
  if (realtimeTimer) clearInterval(realtimeTimer);
  fetchRealtimeCheck(); // 立即执行一次
  realtimeTimer = setInterval(fetchRealtimeCheck, 30000); // 30秒轮询
};

const fetchHistory = async () => {
  try {
    isHistoryLoading.value = true;
    const res = await fetchWithAuth("/api/backtest/history");
    backtestHistory.value = await res.json();
  } catch (err) {
    console.error("获取回测历史失败", err);
  } finally {
    isHistoryLoading.value = false;
  }
};

const fetchWatchlist = async () => {
  try {
    const res = await fetchWithAuth("/api/watchlist");
    watchlist.value = await res.json();
  } catch (err) {
    console.error("获取自选失败", err);
  }
};

const toggleWatchlistBySymbol = async (targetSymbol: string) => {
  if (isWatchlistLoading.value) return;
  const upperSymbol = targetSymbol.toUpperCase();
  const isFavorite = watchlist.value.some(
    (w) => w.symbol.toUpperCase() === upperSymbol
  );
  try {
    isWatchlistLoading.value = true;
    statusMsg.value = isFavorite ? "正在取消收藏..." : "正在加入自选...";
    if (isFavorite) {
      await fetchWithAuth(`/api/watchlist?symbol=${upperSymbol}`, {
        method: "DELETE"
      });
      statusMsg.value = "已从自选移除";
    } else {
      await fetchWithAuth(`/api/watchlist?symbol=${upperSymbol}`, {
        method: "POST"
      });
      statusMsg.value = "已加入自选";
    }
    await fetchWatchlist();
  } catch (err) {
    console.error("同步自选失败", err);
    statusMsg.value = "同步自选失败";
  } finally {
    isWatchlistLoading.value = false;
  }
};

const deleteHistory = async (id: number, e: Event) => {
  e.stopPropagation(); // 防止触发点击切换标的
  if (!confirm("确定要删除这条历史记录吗？")) return;
  try {
    const res = await fetchWithAuth(`/api/backtest/history/${id}`, {
      method: "DELETE"
    });
    if (res.ok) {
      await fetchHistory();
    }
  } catch (err) {
    console.error("删除失败", err);
  }
};

const generateIntradayTimes = () => {
  const times = [];
  // 早上 09:30 - 11:30
  for (let h = 9; h <= 11; h++) {
    for (let m = 0; m < 60; m++) {
      if (h === 9 && m < 30) continue;
      if (h === 11 && m > 30) continue;
      times.push(
        `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`
      );
    }
  }
  // 下午 13:00 - 15:00
  for (let h = 13; h <= 15; h++) {
    for (let m = 0; m < 60; m++) {
      if (h === 15 && m > 0) continue;
      times.push(
        `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}`
      );
    }
  }
  return times;
};

const renderChart = (data: any[]) => {
  if (!chartRef.value) return;
  if (!myChart) myChart = echarts.init(chartRef.value);

  const isDaily = chartMode.value === "daily";

  // 判断是否处于交易时间内 (中国 A 股标准，留出 5 分钟数据同步缓冲)
  const isTrading = (() => {
    const now = new Date();
    const day = now.getDay();
    if (day === 0 || day === 6) return false;
    const timeNum = now.getHours() * 100 + now.getMinutes();
    return (
      (timeNum >= 930 && timeNum <= 1135) ||
      (timeNum >= 1300 && timeNum <= 1505)
    );
  })();

  let dates = data.map((d) => (isDaily ? d.date : d.time));

  // 处理序列数据
  const kData = isDaily
    ? data.map((d) => [
        parseFloat(d.open),
        parseFloat(d.close),
        parseFloat(d.low),
        parseFloat(d.high)
      ])
    : [];

  let lineData = isDaily ? [] : data.map((d) => parseFloat(d.price));

  let volumes = data.map((d, i) => ({
    value: parseFloat(d.volume),
    itemStyle: {
      color: isDaily ? (d.close >= d.open ? "#ef4444" : "#10b981") : "#3b82f6"
    }
  }));

  // 分时图全时间轴补全与前向填充逻辑 (LOCF)
  if (!isDaily) {
    const fullTimes = generateIntradayTimes();
    const dataMap = new Map();
    data.forEach((d) => dataMap.set(d.time, d));

    dates = fullTimes;
    const newLineData: any[] = [];
    const newVolumes: any[] = [];
    let lastPrice: number | null = null;
    const lastDataIndex = fullTimes.findLastIndex((t) => dataMap.has(t));

    fullTimes.forEach((t, i) => {
      const d = dataMap.get(t);
      if (d) {
        lastPrice = parseFloat(d.price);
        newLineData.push(lastPrice);
        newVolumes.push({
          value: parseFloat(d.volume),
          itemStyle: {
            color:
              i === 0 || lastPrice >= (newLineData[i - 1] ?? lastPrice)
                ? "#ef4444"
                : "#10b981"
          }
        });
      } else {
        // 前向填充：如果还没到最后一条数据的时间点，则补齐线段
        if (i < lastDataIndex && lastPrice !== null) {
          newLineData.push(lastPrice);
        } else {
          newLineData.push(null);
        }
        newVolumes.push({
          value: null,
          itemStyle: { color: "transparent" }
        });
      }
    });

    lineData = newLineData;
    volumes = newVolumes;
  }

  const isPortfolioMode =
    data.length > 0 && !data[0].open && data[0].portfolio_value !== undefined;

  const portfolio = isDaily ? data.map((d) => d.portfolio_value) : [];
  const ma20 =
    isDaily && !isPortfolioMode ? data.map((d) => d.sma_20 || null) : [];
  const ma50 =
    isDaily && !isPortfolioMode ? data.map((d) => d.sma_50 || null) : [];

  const markPoints: any[] = [];
  if (isDaily && !isPortfolioMode) {
    data.forEach((d, i) => {
      const prevSignal = i > 0 ? data[i - 1].predicted_signal : 0;
      if (d.predicted_signal === 1 && prevSignal === 0) {
        markPoints.push({
          name: "BUY",
          value: "B",
          xAxis: i,
          yAxis: d.low,
          itemStyle: { color: "#10b981" }
        });
      } else if (d.predicted_signal === 0 && prevSignal === 1) {
        markPoints.push({
          name: "SELL",
          value: "S",
          xAxis: i,
          yAxis: d.high,
          itemStyle: { color: "#ef4444" }
        });
      }
    });
  }

  const option: any = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: "#1e293b",
      borderColor: "#334155",
      textStyle: { color: "#e2e8f0" },
      formatter: function (params: any) {
        let res = `<div style="font-weight:bold;margin-bottom:4px;border-bottom:1px solid #334155;padding-bottom:2px;">${params[0].axisValue}</div>`;
        let dataIndex = params[0].dataIndex;

        // --- 核心修复：如果是分时图补全的空白点，仅显示时间，不显示数值和涨幅 ---
        if (!isDaily && lineData[dataIndex] === null) {
          return res;
        }

        let itemData = data[dataIndex];

        let prevClose = isDaily
          ? dataIndex > 0 && data[dataIndex - 1]
            ? data[dataIndex - 1].close
            : data[0]
              ? data[0].open
              : 0
          : prevCloseRef.value || (data[0] ? data[0].price : 0);

        let currentClose = isDaily
          ? itemData
            ? itemData.close
            : 0
          : lineData[dataIndex] !== null
            ? lineData[dataIndex]
            : itemData
              ? itemData.price
              : 0;

        // 转为数值类型，防御性处理可能出现的 string 或 undefined
        const pClose = Number(prevClose);
        const cClose = Number(currentClose);

        if (!isNaN(pClose) && pClose > 0 && !isNaN(cClose)) {
          let changeStr = (((cClose - pClose) / pClose) * 100).toFixed(2);
          let changeNum = Number(changeStr);
          let color = changeNum >= 0 ? "#10b981" : "#ef4444";
          let sign = changeNum > 0 ? "+" : "";
          res += `<div style="margin-bottom: 4px;"><span style="color: ${color}; font-weight: bold; font-size: 13px;">涨幅: ${sign}${changeStr}%</span></div>`;
        }

        params.forEach((item: any) => {
          if (item.seriesName === "实时闪烁") return;
          if (item.seriesName === "K线") {
            res += `<div style="font-size: 12px; margin-top: 4px;">`;
            res += `${item.marker} 开盘: <b>${item.data[1]}</b> &nbsp;&nbsp; ${item.marker} 收盘: <b>${item.data[2]}</b><br/>`;
            res += `${item.marker} 最低: <b>${item.data[3]}</b> &nbsp;&nbsp; ${item.marker} 最高: <b>${item.data[4]}</b>`;
            res += `</div>`;
          } else if (item.seriesName === "分时") {
            res += `${item.marker} 价格: <b>${item.data}</b><br/>`;
          } else if (item.seriesName === "成交量") {
            let vol =
              item.data.value !== undefined ? item.data.value : item.data;
            res += `${item.marker} ${item.seriesName}: <b>${vol}</b><br/>`;
          } else {
            if (
              item.data !== undefined &&
              item.data !== null &&
              !isNaN(item.data)
            ) {
              res += `${item.marker} ${item.seriesName}: <b>${Number(item.data).toFixed(2)}</b><br/>`;
            }
          }
        });
        return res;
      }
    },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    legend: {
      show: isDaily,
      textStyle: { color: "#94a3b8" },
      top: 0,
      data: ["K线", "MA20", "MA50", "成交量", "账户净值"]
    },
    grid: [
      { left: "4%", right: "4%", top: "10%", height: isDaily ? "60%" : "70%" },
      { left: "4%", right: "4%", top: "75%", height: "15%" }
    ],
    xAxis: [
      {
        type: "category",
        data: dates,
        boundaryGap: isDaily,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { color: "#64748b" }
      },
      {
        type: "category",
        gridIndex: 1,
        data: dates,
        boundaryGap: isDaily,
        axisLine: { lineStyle: { color: "#334155" } },
        axisLabel: { show: false }
      }
    ],
    yAxis: [
      {
        scale: true,
        splitLine: { lineStyle: { color: "#1e293b" } },
        axisLabel: { color: "#64748b" }
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLabel: { show: false },
        axisLine: { show: false },
        splitLine: { show: false }
      },
      {
        type: "value",
        show: isDaily,
        name: "净值",
        position: "right",
        splitLine: { show: false },
        axisLabel: { color: "#10b981" }
      }
    ],
    dataZoom: [
      {
        type: "inside",
        xAxisIndex: [0, 1],
        start: isDaily ? (dates.length > 50 ? 70 : 0) : 0,
        end: 100
      },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        bottom: 10,
        start: isDaily ? (dates.length > 50 ? 70 : 0) : 0,
        end: 100,
        backgroundColor: "rgba(30, 41, 59, 0.4)",
        fillerColor: "rgba(59, 130, 246, 0.1)",
        borderColor: "transparent"
      }
    ],
    series: [
      isDaily && !isPortfolioMode
        ? {
            name: "K线",
            type: "candlestick",
            data: kData,
            itemStyle: {
              color: "#ef4444",
              color0: "#10b981",
              borderColor: "#ef4444",
              borderColor0: "#10b981"
            },
            markPoint: {
              symbol: "pin",
              symbolSize: 30,
              data: markPoints,
              label: { show: true, fontSize: 10, color: "#fff" }
            }
          }
        : !isDaily
          ? {
              name: "分时",
              type: "line",
              data: lineData,
              smooth: false,
              symbol: "none",
              lineStyle: { color: "#3b82f6", width: 2 },
              areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: "rgba(59, 130, 246, 0.4)" },
                  { offset: 1, color: "rgba(59, 130, 246, 0)" }
                ])
              }
            }
          : { type: "line", data: [] }, // 组合模式下清空 K 线占位
      {
        name: "MA20",
        type: "line",
        data: isDaily && !isPortfolioMode ? ma20 : [],
        smooth: true,
        lineStyle: { opacity: 0.5, width: 1 },
        symbol: "none"
      },
      {
        name: "MA50",
        type: "line",
        data: isDaily && !isPortfolioMode ? ma50 : [],
        smooth: true,
        lineStyle: { opacity: 0.5, width: 1 },
        symbol: "none"
      },
      {
        name: "成交量",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: !isPortfolioMode ? volumes : [],
        itemStyle: {
          color: (params: any) => {
            const idx = params.dataIndex;
            if (isDaily) {
              const item = kData[idx];
              return item && item[1] > item[0] ? "#ef4444" : "#10b981";
            }
            // 分时图成交量颜色
            if (idx === 0) return "#3b82f6";
            return lineData[idx] >= lineData[idx - 1] ? "#ef4444" : "#10b981";
          }
        }
      },
      {
        name: isPortfolioMode ? "组合权益曲线 (NAV)" : "账户净值",
        type: "line",
        data: isDaily ? portfolio : [],
        yAxisIndex: isPortfolioMode ? 0 : 2, // 组合模式下直接画在主轴
        smooth: true,
        itemStyle: { color: "#10b981" },
        lineStyle: {
          width: 3,
          shadowBlur: 10,
          shadowColor: "rgba(16, 185, 129, 0.3)"
        },
        areaStyle: isPortfolioMode
          ? {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: "rgba(16, 185, 129, 0.2)" },
                { offset: 1, color: "rgba(16, 185, 129, 0)" }
              ])
            }
          : undefined
      },
      // 实时闪烁点 - 仅在分时图模式且交易时间内显示
      {
        name: "实时闪烁",
        type: "effectScatter",
        coordinateSystem: "cartesian2d",
        data:
          !isDaily && lineData.length > 0 && isTrading
            ? [
                [
                  lineData.findLastIndex((v) => v !== null),
                  lineData.filter((v) => v !== null).pop()
                ]
              ]
            : [],
        symbolSize: 8,
        showEffectOn: "render",
        rippleEffect: {
          brushType: "stroke",
          scale: 4,
          period: 4
        },
        itemStyle: {
          color: "#3b82f6",
          shadowBlur: 10,
          shadowColor: "#3b82f6"
        },
        zlevel: 1
      }
    ]
  };
  myChart.setOption(option, true);
};

onMounted(() => {
  if (symbol.value) {
    fetchStockInfo();
    fetchChartData();
    fetchMetrics();
    fetchTrades();
    fetchLastSignal();
    startRealtimeMonitor();
  }
  fetchMarketInsights();
  fetchHistory();
  fetchWatchlist();
  window.addEventListener("resize", () => myChart?.resize());
});

import { onUnmounted } from "vue";
onUnmounted(() => {
  if (realtimeTimer) clearInterval(realtimeTimer);
});
</script>

<template>
  <div class="space-y-6 relative">
    <!-- 全局 Pipeline 运行遮罩（回测期间禁止所有面板操作） -->
    <div
      v-if="isLoading"
      class="fixed inset-0 z-50 bg-slate-950/40 backdrop-blur-[2px] cursor-not-allowed"
      style="pointer-events: all"
    >
      <div
        class="absolute top-6 left-1/2 -translate-x-1/2 flex items-center gap-3 px-6 py-3 bg-slate-900/90 border border-emerald-500/30 rounded-2xl shadow-2xl shadow-emerald-500/10"
      >
        <Loader2 class="w-5 h-5 animate-spin text-emerald-400" />
        <span class="text-sm font-bold text-emerald-400">{{ statusMsg }}</span>
      </div>
    </div>
    <!-- 股票概况 Header -->
    <div
      v-if="stockInfo.name || symbol.includes(',')"
      class="glass p-6 rounded-[2rem] border border-white/10 flex flex-col md:flex-row justify-between items-start md:items-center gap-4 relative overflow-hidden"
    >
      <div class="relative z-10 w-full">
        <h1
          class="text-3xl font-black tracking-tighter text-white flex flex-wrap items-center gap-3"
        >
          {{ symbol.includes(",") ? "资产组合回测报告" : stockInfo.name }}
          <span
            class="text-sm font-mono px-2 py-0.5 bg-emerald-500/20 text-emerald-400 rounded-md border border-emerald-500/30 uppercase"
            >{{ symbol }}</span
          >
          <div
            v-if="symbol.includes(',')"
            class="flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 shadow-lg shadow-indigo-500/10"
          >
            <Cpu class="w-3.5 h-3.5 text-indigo-400" />
            <span
              class="text-[10px] font-black text-indigo-400 uppercase tracking-widest"
              >Portfolio Engine v2.0</span
            >
          </div>
          <button
            v-if="!symbol.includes(',')"
            @click="toggleWatchlistBySymbol(symbol)"
            :disabled="isWatchlistLoading"
            class="flex items-center gap-2 px-3 py-1.5 rounded-full border transition-all text-xs font-bold"
            :class="[
              watchlist.some((w) => w.symbol === symbol)
                ? 'bg-amber-500/20 border-amber-500/50 text-amber-400'
                : 'bg-white/5 border-white/10 text-slate-400 hover:bg-white/10',
              isWatchlistLoading ? 'opacity-50 cursor-not-allowed' : ''
            ]"
          >
            <Star
              class="w-4 h-4"
              :class="{
                'fill-current': watchlist.some((w) => w.symbol === symbol)
              }"
            />
            {{
              watchlist.some((w) => w.symbol === symbol)
                ? "已在自选"
                : "加入自选"
            }}
          </button>
        </h1>
        <div class="flex gap-4 mt-2 text-slate-400 text-sm">
          <span class="flex items-center gap-1"
            ><Activity class="w-4 h-4 text-blue-400" />
            {{ stockInfo.sector }}</span
          >
          <span class="flex items-center gap-1"
            ><BarChart3 class="w-4 h-4 text-indigo-400" />
            {{ stockInfo.industry }}</span
          >
          <span class="flex items-center gap-1"
            ><DollarSign class="w-4 h-4 text-emerald-400" />
            {{ stockInfo.currency }} / {{ stockInfo.exchange }}</span
          >
        </div>
      </div>
      <div
        class="max-w-md text-slate-500 text-xs leading-relaxed italic relative z-10 hidden lg:block"
      >
        {{ stockInfo.summary }}
      </div>
      <!-- 装饰背景 -->
      <div
        class="absolute -right-20 -top-20 w-64 h-64 bg-blue-600/10 blur-[80px] rounded-full"
      ></div>
    </div>

    <!-- AI 实时决策提醒 -->
    <div
      v-if="lastSignal.date !== 'N/A'"
      class="glass p-4 rounded-2xl border flex flex-col md:flex-row items-center justify-between gap-4 transition-all duration-500 overflow-hidden relative"
      :class="{
        'border-emerald-500/30 bg-emerald-500/5': lastSignal.signal === 1,
        'border-rose-500/30 bg-rose-500/5':
          lastSignal.signal === 0 &&
          trades.length > 0 &&
          trades[0].type === 'BUY',
        'border-white/10':
          lastSignal.signal === 0 &&
          (trades.length === 0 || trades[0].type === 'SELL')
      }"
    >
      <div class="flex items-center gap-4 relative z-10">
        <div
          class="w-12 h-12 rounded-full flex items-center justify-center shadow-lg"
          :class="{
            'bg-emerald-500 shadow-emerald-500/20 text-white':
              lastSignal.signal === 1,
            'bg-rose-500 shadow-rose-500/20 text-white':
              lastSignal.signal === 0 &&
              trades.length > 0 &&
              trades[0].type === 'BUY',
            'bg-slate-700 text-slate-400':
              lastSignal.signal === 0 &&
              (trades.length === 0 || trades[0].type === 'SELL')
          }"
        >
          <TrendingUp v-if="lastSignal.signal === 1" class="w-6 h-6" />
          <ShieldAlert
            v-else-if="
              lastSignal.signal === 0 &&
              trades.length > 0 &&
              trades[0].type === 'BUY'
            "
            class="w-6 h-6"
          />
          <Activity v-else class="w-6 h-6" />
        </div>
        <div>
          <h4
            class="text-xs font-bold uppercase tracking-widest text-slate-500 mb-1 flex items-center gap-1"
          >
            AI 实时决策建议
            <Loader2 v-if="isSignalLoading" class="w-3 h-3 animate-spin" />
          </h4>
          <div class="text-xl font-black flex items-center gap-2">
            <!-- 优先显示实时分时诊断信号 -->
            <template v-if="realtimeSignal">
              <span
                v-if="realtimeSignal.ai_signal === 1"
                class="text-emerald-400 animate-pulse"
              >
                分时看多：建议介入
              </span>
              <span
                v-else-if="realtimeSignal.ai_signal === -1"
                class="text-rose-400 animate-pulse"
              >
                分时看空：建议离场
              </span>
              <span v-else class="text-slate-400"> 分时震荡：保持观望 </span>
            </template>
            <!-- 降级显示回测最后信号 -->
            <template v-else-if="lastSignal.signal === 1">
              <span class="text-emerald-400">长期看多：持仓/买入</span>
            </template>
            <template
              v-else-if="
                lastSignal.signal === 0 &&
                trades.length > 0 &&
                trades[0].type === 'BUY'
              "
            >
              <span class="text-rose-400">长期走弱：逢高减仓</span>
            </template>
            <template v-else>
              <span class="text-slate-300">空仓观望</span>
            </template>
          </div>
        </div>
      </div>
      <div class="text-right relative z-10">
        <div class="text-[10px] text-slate-500 uppercase font-mono mb-1">
          参考价 ({{ lastSignal.date }})
        </div>
        <div class="text-2xl font-mono font-bold text-white">
          ${{ realtimeSignal?.current_price || lastSignal.price }}
        </div>
        <div
          v-if="realtimeSignal"
          class="text-[9px] font-mono text-slate-500 mt-1"
        >
          置信度: {{ (realtimeSignal.ai_confidence * 100).toFixed(1) }}% (刷新于
          {{ realtimeSignal.updated_at }})
        </div>
      </div>
      <!-- 动态波纹背景 -->
      <div
        v-if="lastSignal.signal === 1"
        class="absolute -right-10 -bottom-10 w-32 h-32 bg-emerald-500/10 blur-2xl rounded-full animate-pulse"
      ></div>
    </div>

    <!-- 顶栏指标卡片 -->
    <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3 relative">
      <!-- 加载遮罩 -->
      <div
        v-if="isMetricsLoading"
        class="absolute inset-0 z-10 bg-slate-950/50 backdrop-blur-sm rounded-2xl flex items-center justify-center"
      >
        <Loader2 class="w-5 h-5 animate-spin text-emerald-400" />
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><Award class="w-3 h-3" /> 累计收益</span
        >
        <span
          class="text-lg font-bold font-mono"
          :class="
            metrics.total_return >= 0 ? 'text-emerald-400' : 'text-rose-400'
          "
        >
          {{ metrics.total_return }}%
        </span>
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><Activity class="w-3 h-3" /> 夏普比率</span
        >
        <span class="text-lg font-bold font-mono text-blue-400">{{
          metrics.sharpe_ratio
        }}</span>
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><ShieldAlert class="w-3 h-3" /> 最大回撤</span
        >
        <span class="text-lg font-bold font-mono text-rose-400"
          >{{ metrics.max_drawdown }}%</span
        >
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><TrendingUp class="w-3 h-3" /> 年化收益</span
        >
        <span class="text-lg font-bold font-mono text-emerald-400"
          >{{ metrics.annual_return }}%</span
        >
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><Activity class="w-3 h-3" /> 胜率</span
        >
        <span class="text-lg font-bold font-mono text-amber-400"
          >{{ metrics.win_rate }}%</span
        >
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><BarChart3 class="w-3 h-3" /> 盈亏比</span
        >
        <span class="text-lg font-bold font-mono text-indigo-400">{{
          metrics.profit_loss_ratio
        }}</span>
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><List class="w-3 h-3" /> 交易次数</span
        >
        <span class="text-lg font-bold font-mono text-slate-300">{{
          metrics.trade_count
        }}</span>
      </div>
      <div class="glass p-3 rounded-2xl flex flex-col justify-between">
        <span
          class="text-slate-500 text-[10px] flex items-center gap-1 uppercase tracking-tighter"
          ><DollarSign class="w-3 h-3" /> 最终净值</span
        >
        <span class="text-lg font-bold font-mono text-white"
          >${{ metrics.final_value }}</span
        >
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6 items-stretch">
      <!-- 侧边控制栏 (左侧) -->
      <div class="lg:col-span-2 flex flex-col gap-6">
        <!-- 我的自选 (移至顶部) -->
        <div
          class="glass p-5 rounded-3xl border border-white/5 flex flex-col gap-3 min-h-[140px]"
        >
          <h3
            class="text-sm font-bold flex items-center gap-2 text-slate-400 uppercase tracking-widest"
          >
            <Star class="w-4 h-4 text-amber-400" /> 我的自选
          </h3>
          <div class="flex flex-wrap gap-2 overflow-y-auto pr-2 scrollbar-none">
            <div
              v-if="watchlist.length === 0"
              class="text-slate-600 text-center py-4 text-[10px] italic w-full"
            >
              暂无收藏标的
            </div>
            <div
              v-for="w in watchlist"
              :key="w.symbol"
              class="px-3 py-1.5 bg-white/5 hover:bg-amber-500/10 border border-white/5 hover:border-amber-500/30 rounded-full cursor-pointer transition-all group flex items-center gap-2"
              @click="handleWatchlistClick(w.symbol)"
            >
              <span
                class="text-[10px] font-mono font-bold flex items-center gap-1.5"
              >
                {{ w.symbol }}
                <span
                  v-if="w.name && w.name !== w.symbol"
                  class="text-amber-200/60 font-sans font-medium"
                  >{{ w.name }}</span
                >
              </span>
              <button
                @click.stop="toggleWatchlistBySymbol(w.symbol)"
                class="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400 transition-all"
              >
                <Trash2 class="w-2.5 h-2.5" />
              </button>
            </div>
          </div>
        </div>

        <div class="glass p-6 rounded-3xl border border-white/5">
          <h3 class="text-xl font-semibold mb-6 flex items-center gap-2">
            <Cpu class="w-5 h-5 text-emerald-400" /> 控制面板
          </h3>
          <div class="space-y-4">
            <div>
              <label
                class="block text-[10px] text-slate-500 mb-2 uppercase tracking-widest font-bold"
                >股票代码</label
              >
              <input
                v-model="symbol"
                type="text"
                class="w-full bg-slate-950 border border-white/10 rounded-xl px-4 py-3 text-sm focus:outline-none focus:border-emerald-500 transition-all uppercase font-mono"
              />
            </div>
            <div>
              <label
                class="block text-[10px] text-slate-500 mb-2 uppercase tracking-widest font-bold"
                >回测时间</label
              >
              <div class="space-y-2">
                <input
                  v-model="startDate"
                  type="date"
                  class="w-full bg-slate-950 border border-white/10 rounded-xl px-4 py-2 text-xs focus:outline-none focus:border-emerald-500 transition-all text-slate-300"
                />
                <input
                  v-model="endDate"
                  type="date"
                  class="w-full bg-slate-950 border border-white/10 rounded-xl px-4 py-2 text-xs focus:outline-none focus:border-emerald-500 transition-all text-slate-300"
                />
              </div>
            </div>

            <p
              class="text-[10px] text-slate-500 text-center font-mono uppercase tracking-tighter"
            >
              Status: {{ statusMsg }}
            </p>
          </div>
        </div>

        <!-- 策略微调面板 -->
        <div class="glass p-6 rounded-3xl border border-white/5 flex-1 flex flex-col">
          <h3 class="text-xl font-semibold mb-6 flex items-center gap-2 shrink-0">
            <ShieldAlert class="w-5 h-5 text-indigo-400" /> 策略配置
          </h3>
          <div class="space-y-6 flex-1 flex flex-col">
            <!-- 初始本金 -->
            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-emerald-400 uppercase font-bold tracking-widest cursor-help"
                    >初始本金 (¥)</label
                  >
                  <Info
                    class="w-3 h-3 text-emerald-400/60 hover:text-emerald-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      模拟交易时的投入本金。影响账户净值变化规模与交易数量的计算。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-emerald-400">{{
                  initialCapital.toLocaleString()
                }}</span>
              </div>
              <input
                v-model.number="initialCapital"
                type="range"
                min="1000"
                max="1000000"
                step="1000"
                class="w-full h-1.5 bg-slate-700/50 rounded-lg appearance-none cursor-pointer accent-emerald-500 hover:accent-emerald-400 transition-all"
              />
            </div>

            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-slate-500 uppercase font-bold tracking-widest cursor-help"
                    >预测周期 (天)</label
                  >
                  <Info
                    class="w-3 h-3 text-slate-600 hover:text-indigo-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      控制 AI
                      预测的时间跨度。较长的周期适合捕捉大级别趋势（波段），较短周期则对日内波动更敏感。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-indigo-400"
                  >{{ predictionDays }}d</span
                >
              </div>
              <input
                v-model.number="predictionDays"
                type="range"
                min="5"
                max="30"
                step="1"
                class="w-full accent-indigo-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-slate-500 uppercase font-bold tracking-widest cursor-help"
                    >移动止损 (%)</label
                  >
                  <Info
                    class="w-3 h-3 text-slate-600 hover:text-rose-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      基于持仓期间最高点进行回撤保护。例如设置
                      -10%，则当价格从买入后的最高点回落 10%
                      时，系统将立即清仓，保护利润。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-rose-400"
                  >{{ stopLoss }}%</span
                >
              </div>
              <input
                v-model.number="stopLoss"
                type="range"
                min="-20"
                max="-1"
                step="1"
                class="w-full accent-rose-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-slate-500 uppercase font-bold tracking-widest cursor-help"
                    >信号平滑 (天)</label
                  >
                  <Info
                    class="w-3 h-3 text-slate-600 hover:text-emerald-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      买入/卖出信号的忍耐窗口。例如设置为
                      3，表示系统需要连续确认数天信号的稳定性，避免因短期剧烈波动而频繁进出。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-emerald-400"
                  >{{ gracePeriod }}d</span
                >
              </div>
              <input
                v-model.number="gracePeriod"
                type="range"
                min="1"
                max="10"
                step="1"
                class="w-full accent-emerald-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <!-- 新增：风控深化配置项 -->
            <div class="space-y-3 pt-2 border-t border-white/5">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-indigo-400 uppercase font-bold tracking-widest cursor-help"
                    >仓位占比</label
                  >
                  <Info
                    class="w-3 h-3 text-indigo-400/60 hover:text-indigo-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      单次交易所能投入的资金占当前总可支配本金的比例。例如设置为
                      50%，则每次买入仅投入一半仓位，降低系统性风险。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-indigo-400"
                  >{{ (posRatio * 100).toFixed(0) }}%</span
                >
              </div>
              <input
                v-model.number="posRatio"
                type="range"
                min="0.1"
                max="1.0"
                step="0.1"
                class="w-full accent-indigo-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div class="space-y-3">
              <div class="flex justify-between items-center">
                <div class="flex items-center gap-2 group/tip relative">
                  <label
                    class="text-[10px] text-amber-400 uppercase font-bold tracking-widest cursor-help"
                    >账户熔断阀值</label
                  >
                  <Info
                    class="w-3 h-3 text-amber-400/60 hover:text-amber-400 transition-colors cursor-help"
                  />
                  <!-- Premium Tooltip -->
                  <div
                    class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                  >
                    <p class="text-[10px] text-slate-300 leading-relaxed">
                      最终风控红线。一旦整个账户的累计回撤超过该阈值（基于最高点资产），系统将瞬间平仓止损并锁定交易，防止极端深度损失。
                    </p>
                    <div
                      class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                    ></div>
                  </div>
                </div>
                <span class="text-xs font-mono text-amber-400"
                  >{{ maxAccountDrawdown }}%</span
                >
              </div>
              <input
                v-model.number="maxAccountDrawdown"
                type="range"
                min="5"
                max="50"
                step="5"
                class="w-full accent-amber-500 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer"
              />
            </div>

            <div
              class="flex items-center justify-between p-3 bg-slate-800/30 rounded-xl border border-white/5"
            >
              <div class="flex items-center gap-2 group/tip relative">
                <label
                  class="text-[10px] text-slate-400 uppercase font-bold tracking-widest cursor-help"
                  >启用 ATR 动态止损</label
                >
                <Info
                  class="w-3.5 h-3.5 text-slate-500 hover:text-blue-400 transition-colors cursor-help"
                />

                <!-- Premium Tooltip -->
                <div
                  class="absolute bottom-full left-0 mb-2 w-48 p-2 bg-slate-800 border border-white/10 rounded-xl shadow-2xl opacity-0 invisible group-hover/tip:opacity-100 group-hover/tip:visible transition-all duration-300 z-50 pointer-events-none"
                >
                  <p
                    class="text-[10px] text-slate-300 leading-relaxed font-medium"
                  >
                    <span class="text-blue-400 font-bold">ATR 动态止损：</span>
                    基于市场波动率 (ATR)
                    自动调整。波动剧烈时给持仓更多空间，行情平稳时快速锁利。
                  </p>
                  <div
                    class="absolute -bottom-1 left-4 w-2 h-2 bg-slate-800 border-r border-b border-white/10 rotate-45"
                  ></div>
                </div>
              </div>
              <button
                @click="useAtrStop = !useAtrStop"
                class="w-10 h-5 rounded-full relative transition-all duration-300"
                :class="useAtrStop ? 'bg-blue-500' : 'bg-slate-700'"
              >
                <div
                  class="absolute top-1 left-1 w-3 h-3 bg-white rounded-full transition-all duration-300"
                  :class="useAtrStop ? 'translate-x-5' : 'translate-x-0'"
                ></div>
              </button>
            </div>

            <p class="text-[9px] text-slate-600 leading-relaxed italic">
              *
              调整参数后需重新点击回测以生效。较长的预测周期有助于捕捉波段趋势，而较小的止损位能保护本金安全。
            </p>

            <button
              @click="runPipeline"
              :disabled="isLoading"
              class="w-full mt-auto py-4 px-4 rounded-2xl font-bold transition-all flex items-center justify-center gap-2 group overflow-hidden relative shadow-2xl shrink-0"
              :class="
                isLoading
                  ? 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-emerald-600 to-teal-500 text-white hover:scale-[1.02] active:scale-95 shadow-emerald-500/20'
              "
            >
              <div
                v-if="!isLoading"
                class="absolute inset-0 bg-white/10 translate-y-full group-hover:translate-y-0 transition-transform duration-300"
              ></div>
              <Loader2 v-if="isLoading" class="w-5 h-5 animate-spin" />
              <Play v-else class="w-5 h-5 fill-current" />
              {{ isLoading ? "模型计算中..." : "启动波段回测" }}
            </button>
          </div>
        </div>
      </div>

      <!-- 主图表区 (中间) -->
      <div class="lg:col-span-7 flex flex-col gap-6 h-full">
        <div
          class="glass p-6 rounded-[2rem] h-[600px] border border-white/5 relative bg-slate-900/40 backdrop-blur-3xl overflow-hidden"
        >
          <div class="flex justify-between items-center mb-8 relative z-10">
            <div>
              <h3
                class="text-2xl font-bold tracking-tight mb-1 flex items-center gap-2"
              >
                <TrendingUp class="w-6 h-6 text-emerald-400" /> 策略回测报告
                <Loader2
                  v-if="isChartDataLoading || isIntradayLoading"
                  class="w-4 h-4 text-emerald-400 animate-spin"
                />
              </h3>
              <p class="text-slate-500 text-xs font-mono">
                基于 XGBoost 动态趋势预测模型
              </p>
            </div>
            <div
              class="flex bg-slate-800/50 p-1 rounded-xl border border-white/5"
            >
              <button
                @click="setChartMode('daily')"
                :disabled="isChartDataLoading || isIntradayLoading"
                class="px-4 py-1.5 rounded-lg text-xs font-bold transition-all"
                :class="[
                  chartMode === 'daily'
                    ? 'bg-emerald-500 text-white shadow-lg shadow-emerald-500/20'
                    : 'text-slate-400 hover:text-white',
                  isChartDataLoading || isIntradayLoading
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer'
                ]"
              >
                日线模式
              </button>
              <button
                @click="setChartMode('intraday')"
                :disabled="isChartDataLoading || isIntradayLoading"
                class="px-4 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-2"
                :class="[
                  chartMode === 'intraday'
                    ? 'bg-blue-500 text-white shadow-lg shadow-blue-500/20'
                    : 'text-slate-400 hover:text-white',
                  isChartDataLoading || isIntradayLoading
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer'
                ]"
              >
                <div
                  v-if="isIntradayLoading"
                  class="w-2 h-2 bg-white rounded-full animate-pulse"
                ></div>
                分时图
              </button>
            </div>
            <div class="flex gap-2 items-center">
              <div
                v-if="chartMode === 'intraday' && intradayData"
                class="flex items-center gap-3 mr-4 px-4 py-1.5 bg-slate-800/80 border border-white/5 rounded-2xl shadow-inner group"
              >
                <div class="flex flex-col items-end">
                  <div class="flex items-center gap-2">
                    <span
                      class="text-[10px] text-slate-500 font-bold uppercase tracking-widest group-hover:text-blue-400 transition-colors"
                      >最新价</span
                    >
                    <span
                      class="text-lg font-black font-mono text-white leading-none"
                    >
                      {{
                        (intradayData as any).length > 0
                          ? (intradayData as any)[
                              (intradayData as any).length - 1
                            ].price
                          : realtimeSignal?.current_price || "0.00"
                      }}
                    </span>
                  </div>
                  <div
                    v-if="prevCloseRef || realtimeSignal?.prev_close"
                    class="flex items-center gap-1 mt-0.5"
                  >
                    <span class="text-[9px] text-slate-600 font-medium"
                      >涨跌幅</span
                    >
                    <span
                      class="text-xs font-bold font-mono"
                      :class="{
                        'text-emerald-400':
                          (((intradayData as any).length > 0
                            ? (intradayData as any)[
                                (intradayData as any).length - 1
                              ].price
                            : realtimeSignal?.current_price || 0) -
                            (prevCloseRef || realtimeSignal?.prev_close)) /
                            (prevCloseRef || realtimeSignal?.prev_close) >=
                          0,
                        'text-rose-400':
                          (((intradayData as any).length > 0
                            ? (intradayData as any)[
                                (intradayData as any).length - 1
                              ].price
                            : realtimeSignal?.current_price || 0) -
                            (prevCloseRef || realtimeSignal?.prev_close)) /
                            (prevCloseRef || realtimeSignal?.prev_close) <
                          0
                      }"
                    >
                      {{
                        (
                          ((((intradayData as any).length > 0
                            ? (intradayData as any)[
                                (intradayData as any).length - 1
                              ].price
                            : realtimeSignal?.current_price || 0) -
                            (prevCloseRef || realtimeSignal?.prev_close || 1)) /
                            (prevCloseRef || realtimeSignal?.prev_close || 1)) *
                          100
                        ).toFixed(2)
                      }}%
                    </span>
                  </div>
                </div>
              </div>
              <div
                class="px-3 py-1 bg-blue-500/10 border border-blue-500/20 rounded-full text-[10px] text-blue-400 uppercase font-bold tracking-widest"
              >
                {{
                  chartMode === "daily" ? "Historical Model" : "Live Scanner"
                }}
              </div>
            </div>
          </div>

          <div ref="chartRef" class="w-full h-[500px]"></div>

          <!-- 背景装饰 -->
          <div
            class="absolute -top-24 -right-24 w-96 h-96 bg-emerald-500/5 blur-[100px] rounded-full pointer-events-none"
          ></div>
          <div
            class="absolute -bottom-24 -left-24 w-96 h-96 bg-blue-500/5 blur-[100px] rounded-full pointer-events-none"
          ></div>
        </div>

        <!-- AI 策略诊断报告 -->
        <div
          v-if="analysisReport"
          class="glass p-6 rounded-[2rem] border border-white/5 relative overflow-hidden bg-slate-900/40 backdrop-blur-3xl flex-1 flex flex-col w-full"
        >
          <div class="flex justify-between items-center mb-8 relative z-10">
            <div>
              <h3
                class="text-2xl font-bold tracking-tight mb-1 flex items-center gap-2"
              >
                <Activity class="w-6 h-6 text-emerald-400" /> AI
                策略深度诊断报告
              </h3>
              <p class="text-slate-500 text-xs font-mono">
                PRO STRATEGY ANALYSIS & RECOMMENDATIONS
              </p>
            </div>
          </div>

          <div
            class="relative z-10 text-slate-300 leading-relaxed selection:bg-emerald-500/30"
            v-html="formattedReport"
          ></div>

          <!-- 背景光效 -->
          <div
            class="absolute -top-12 -right-12 w-64 h-64 bg-emerald-500/5 blur-[80px] rounded-full pointer-events-none"
          ></div>
          <div
            class="absolute -bottom-12 -left-12 w-64 h-64 bg-blue-500/5 blur-[80px] rounded-full pointer-events-none"
          ></div>
        </div>
      </div>

      <!-- 右侧市场洞察栏 (右侧) -->
      <div class="lg:col-span-3 flex flex-col gap-6 h-full">
        <div
          class="glass p-6 rounded-[2rem] border border-white/5 flex flex-col gap-6 overflow-hidden flex-1"
        >
          <h3 class="text-xl font-black flex items-center gap-2 shrink-0">
            <Globe2 class="w-5 h-5 text-indigo-400" /> 市场洞察
          </h3>

          <!-- 个股热荐 -->
          <div class="flex flex-col min-h-0">
            <h4
              class="text-[10px] text-slate-500 uppercase font-bold tracking-widest mb-3 shrink-0"
            >
              全网热度 TOP 20
            </h4>
            <div
              class="space-y-1.5 overflow-y-auto pr-2 scrollbar-thin max-h-[350px]"
            >
              <div
                v-for="stock in marketInsights.recommendations"
                :key="stock.symbol"
                class="group/item flex items-center justify-between p-3 rounded-2xl bg-white/5 border border-white/5 hover:border-amber-500/30 hover:bg-amber-500/5 transition-all cursor-pointer"
                @click="handleWatchlistClick(stock.symbol)"
              >
                <div class="flex flex-col">
                  <span
                    class="text-xs font-bold text-white group-hover/item:text-amber-400 transition-colors"
                    >{{ stock.name }}</span
                  >
                  <span class="text-[9px] font-mono text-slate-600">{{
                    stock.symbol
                  }}</span>
                </div>
                <div class="flex items-center gap-2">
                  <span
                    class="text-[10px] font-mono text-slate-400 tabular-nums"
                    >#{{ stock.rank }}</span
                  >
                  <ChevronRight
                    class="w-4 h-4 text-slate-800 group-hover/item:text-white transition-all transform group-hover/item:translate-x-1"
                  />
                </div>
              </div>
            </div>
          </div>

          <!-- 热门板块 -->
          <div>
            <h4
              class="text-[10px] text-slate-500 uppercase font-bold tracking-widest mb-4"
            >
              热门板块排行
            </h4>
            <div class="grid grid-cols-2 gap-2">
              <div
                v-for="sector in marketInsights.sectors"
                :key="sector.code"
                class="p-2.5 bg-white/5 rounded-2xl border border-white/5 flex flex-col items-center hover:bg-white/10 transition-colors"
              >
                <span class="text-[10px] font-bold text-slate-400 mb-1">{{
                  sector.name
                }}</span>
                <span
                  class="text-xs font-mono font-black"
                  :class="
                    sector.change >= 0 ? 'text-emerald-400' : 'text-rose-400'
                  "
                >
                  {{ sector.change >= 0 ? "+" : "" }}{{ sector.change }}%
                </span>
              </div>
            </div>
          </div>

          <!-- 财经要闻 -->
          <div class="flex flex-col min-h-0">
            <h4
              class="text-[10px] text-slate-500 uppercase font-bold tracking-widest flex items-center justify-between mb-3 shrink-0"
            >
              财经要闻
              <span class="text-slate-700 font-mono text-[8px]">{{
                marketInsights.updated_at
              }}</span>
            </h4>
            <div
              class="space-y-2 overflow-y-auto pr-2 scrollbar-thin max-h-[573px]"
            >
              <div
                v-if="isInsightsLoading"
                class="text-center py-10 opacity-30"
              >
                <Loader2 class="w-6 h-6 animate-spin mx-auto" />
              </div>
              <div
                v-else
                v-for="(item, idx) in marketInsights.news"
                :key="idx"
                class="p-3 bg-white/5 rounded-2xl border border-white/5 hover:border-indigo-500/30 transition-all group"
              >
                <div class="flex items-center gap-2 mb-1.5">
                  <span
                    class="text-[8px] font-mono px-1.5 py-0.5 bg-indigo-500/10 text-indigo-400 rounded"
                    >BAIDU</span
                  >
                  <span class="text-[8px] text-slate-600 font-mono">{{
                    item.time.split(" ")[1]
                  }}</span>
                </div>
                <p
                  class="text-[11px] text-slate-300 leading-relaxed font-medium group-hover:text-amber-200 transition-colors line-clamp-2"
                >
                  {{ item.title }}
                </p>
              </div>
            </div>
          </div>

          <button
            @click="fetchMarketInsights"
            class="w-full py-3 bg-white/5 hover:bg-white/10 border border-white/10 rounded-2xl text-[10px] text-slate-500 font-bold uppercase tracking-widest transition-all mt-auto shrink-0 flex items-center justify-center gap-2"
          >
            <Activity class="w-3 h-3" /> 点击刷新洞察数据
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.glass {
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
}

.scrollbar-none::-webkit-scrollbar {
  display: none;
}
.scrollbar-none {
  -ms-overflow-style: none;
  scrollbar-width: none;
}

.scrollbar-thin::-webkit-scrollbar {
  height: 6px;
  width: 6px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.2);
}
</style>
