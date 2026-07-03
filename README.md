# AlphaCouncil2-AI · 中国 A 股量化交易系统

> 面向个人量化研究者的 A 股量化交易系统：数据采集 → 58 因子 → 4 策略 → 事件驱动回测 → 模拟执行 → 风控。
> 模拟盘研究用途，零外部依赖（默认 SQLite），双击即可运行。

---

## 🚀 5 分钟快速开始

### 环境要求
- **Node.js** 18+（前端 + API 服务）
- **Python** 3.10+（量化引擎：因子/策略/回测）

### 三步启动

```bat
:: 1. 首次安装（检查环境 + 装依赖 + 初始化数据）
setup.bat

:: 2. 日常启动（双击即可）
start_all.bat

:: 3. 打开浏览器访问
::    前端: http://localhost:3333
::    后端: http://localhost:3334
```

### 命令行方式（等价）

```bash
# 安装依赖
npm install
pip install -r requirements.txt

# 初始化数据（腾讯日K + AKShare财务）
python scripts/seed.py --limit 50    # 少量测试
python scripts/seed.py               # 全量（约400只，30分钟）

# 启动
node server/index.mjs &              # 后端 3334
npx vite --port 3333                 # 前端 3333
```

---

## 🏗️ 系统架构

> 📐 **详细的系统架构图、工作流程图、五层关系图、调度/决策/执行关系图见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。**

```
┌─────────────────────────────────────────────────┐
│            前端 (React + TypeScript)             │
│   数据浏览 │ 因子引擎 │ 策略运行 │ 交易执行       │
│   风控监控 │ 监控告警                            │
│   端口 3333 (Vite)                              │
└──────────────────┬──────────────────────────────┘
                   │ HTTP REST
┌──────────────────┴──────────────────────────────┐
│         后端 (Node.js, 端口 3334)                │
│   8 个 API 路由 → PersistentRunner 桥接          │
└──────────────────┬──────────────────────────────┘
                   │ stdin/stdout JSON
┌──────────────────┴──────────────────────────────┐
│            Python 量化引擎                       │
│  ┌─────────┬─────────┬─────────┬─────────┐      │
│  │数据层    │因子层    │策略层    │回测层    │      │
│  │腾讯日K   │47因子    │4策略     │事件驱动  │      │
│  │AKShare财务│IC/IR    │多因子    │夏普/回撤 │      │
│  ├─────────┼─────────┼─────────┼─────────┤      │
│  │执行层    │风控层             │          │
│  │模拟下单  │VaR/集中度         │          │
│  └─────────┴───────────────────┘          │
└──────────────────┬──────────────────────────────┘
                   │
            ┌──────┴──────┐
            │ SQLite      │  默认存储
            │ data/       │  data/quant.db
            │ quant.db    │  零外部依赖
            └─────────────┘
```

### 数据流
```
腾讯财经 (日K前复权)  ─┐
                        ├─→ sync_service ─→ SQLite ─→ 因子计算 ─→ 策略信号 ─→ 模拟下单
AKShare (财务指标)    ─┘                    (kline:*, fin:*)
```

---

## 📊 系统能力

| 层 | 能力 | 数量/说明 |
|---|---|---|
| **数据层** | 腾讯日K + AKShare 财务 | 沪深300+创业板+科创板 ~400只，1998年至今 |
| **因子层** | 量价因子 + 技术指标 + 基本面因子 | 58 个（28 量价 + 19 技术 + 11 基本面）|
| **策略层** | 内置策略 | 4 种：单因子排名 / 多因子加权 / 均线交叉 / 布林带 |
| **回测层** | 事件驱动回测 | 滑点/手续费/T+1/整手，输出夏普/回撤/胜率 |
| **执行层** | 模拟交易 | 市价单/限价单，持仓/盈亏追踪（非真实券商）|
| **风控层** | 组合风险 + 系统健康 | VaR/集中度/波动率/暴露度 |

### 58 个因子清单

**量价类（28个）**：动量(ret_1/5/10/20/60)、反转(reversal_3/5/10)、波动(volatility_5/20/60, range_pct)、量价相关(pvcorr_5/10/20, pvbeta_20)、资金流(mfi_14, obv/ad_slope, vwap_dev)、换手(turnover, vol/amt_ratio)、趋势形态(trend_strength, gap, intraday/overnight_ret)

**技术类（19个）**：EMA(12/26)、MACD(dif/dea/hist)、RSI(6/12/24)、KDJ(k/d/j)、BOLL(mid/upper/lower)、ATR、Williams%R、ROC、CCI、BIAS

**基本面类（11个，需 AKShare 财务数据）**：ROE、ROA、毛利率、净利率、营收增速、利润增速、资产负债率、流动比率、存货/应收/总资产周转率。采用前向填充对齐到交易日，使基本面因子能参与截面 IC 评估与多因子策略。

> ⚠️ 基本面因子采用报告期近似（PIT 假设），实盘需加财报发布日滞后，否则存在前视偏差风险。

---

## 🔧 常用操作

### 数据管理
```bash
# 全市场下载（5528只，K线+财务，首次约5小时，baostock源稳定）
python scripts/download_all.py --phase both

# 仅K线（约2小时）
python scripts/download_all.py --phase kline

# 少量测试
python scripts/seed.py --limit 50 --no-financial

# 指定股票
python scripts/seed.py --codes 600519,000001,300750

# 数据健康检查
python quant/data/health.py
```

### 每日增量更新（收盘后运行）
```bash
# 增量刷新K线（全A股最新交易日，约30分钟）
python scripts/daily_update.py
# 或双击 daily_update.bat

# 含财务刷新（季度任务，约5小时）
python scripts/daily_update.py --financial

# Windows 任务计划（每个交易日17:00自动更新）
schtasks /create /tn "AlphaCouncil每日更新" /tr "python C:\...\scripts\daily_update.py" /sc daily /st 17:00
```

### 因子分析（全市场）
```bash
# 全市场因子有效性评估（5207只，约30分钟，输出 data/factor_evaluation.json）
python scripts/evaluate_factors.py

# 全市场策略扫描（用有效因子选股回测，约20分钟）
python scripts/scan_strategies.py
```
评估结果在「因子引擎 → 市场榜单」面板可视化展示。

### 切换存储后端
默认 SQLite（零依赖）。如需用 Redis：
```bash
# Windows
set QUANT_CACHE=redis
# 或用纯内存（测试用）
set QUANT_CACHE=memory
```

### 后台数据同步（可选）
```bash
# 启动常驻同步服务（每30秒刷新实时行情，每2分钟增量K线）
python quant/data/sync_service.py
```

### 开发验证（改完代码跑一遍）
```bash
# 1. Python 全链路冒烟测试（7层：存储→数据→因子→策略→执行→风控→导入）
python scripts/smoke_test.py

# 2. API 端到端测试（22个action，需后端运行）
python scripts/test_api.py --reset

# 3. UI 性能+报错验证（14个API响应时间 + 8面板渲染，需前后端都运行）
node scripts/ui_verify.mjs
```
改完代码后依次跑这三个，全部通过即可放心。验证套件覆盖：API 响应<3秒、零控制台错误、所有面板有真实数据渲染。

---

## ❓ 常见问题

**Q: 启动后前端显示"正在连接行情..."或数据为空？**
A: 数据库还没初始化。运行 `python scripts/seed.py --limit 50` 灌入数据。

**Q: 腾讯/AKShare 接口偶尔超时？**
A: 正常现象，免费数据源有反爬。seed 脚本已内置重试。多次失败可重跑。

**Q: 端口 3333/3334 被占用？**
A: 关闭残留进程：
```bat
:: 杀掉所有 Node 和量化引擎进程（会杀所有 node/python，慎用）
taskkill /f /im node.exe
taskkill /f /im python.exe
```
更精确的方式（PowerShell，只杀本项目进程）：
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*AlphaCouncil2*runner.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**Q: 改了 Python 代码（因子/策略/引擎）后，前端看到的还是旧结果？**
A: 后端用常驻子进程（PersistentRunner）执行 Python，改代码后需**重启 Node 服务并清理残留的 python 子进程**（否则旧的孤儿进程会继续用旧代码）。重启方法：
```bat
:: 1. 关掉最小化的后端窗口，或执行：
taskkill /f /im node.exe
:: 2. 清理残留 python 引擎进程（同上一条 PowerShell 命令）
:: 3. 重新双击 start_all.bat
```

**Q: 报错 `ImportError: quant.data`？**
A: 确认在项目根目录运行，或设 `PYTHONPATH` 为项目根目录。

**Q: 因子/策略效果不好？**
A: 默认参数未调优。回测亏损是正常的（说明引擎没作弊）。可在策略面板调整因子权重、周期等参数。

---

## 📁 目录结构

```
AlphaCouncil2-AI/
├── server/              # Node.js 后端
│   ├── index.mjs        # 入口
│   ├── router.mjs       # 路由分发
│   └── routes/          # 8 个 API 路由
├── quant/               # Python 量化引擎
│   ├── data/            # 数据层（cache/schema/腾讯源/akshare源）
│   ├── factor/          # 因子层（47因子 + IC评估）
│   ├── strategy/        # 策略层（4策略）
│   ├── backtest/        # 回测层（事件驱动）
│   ├── execution/       # 执行层（模拟下单）
│   └── risk/            # 风控层
├── scripts/             # 运行脚本（seed + 各层 runner）
├── components/          # React 前端面板（6个）
├── data/                # SQLite 数据库（运行后生成）
├── setup.bat            # 首次安装
├── start_all.bat        # 一键启动
└── requirements.txt     # Python 依赖
```

---

## ⚠️ 重要说明

- **本系统仅供量化研究学习**，模拟盘交易，不连接真实券商，不涉及真实资金。
- 实盘交易需券商授权，且涉及法律与资金风险，请咨询券商合规部门。
- 数据源为免费接口（腾讯/AKShare），稳定性与数据深度有限。
- 回测结果不代表实盘表现，请勿据此进行真实投资。

---

## 📝 扩展指南

### 新增因子
在 `quant/factor/price_volume.py` 或 `technical.py` 添加计算函数，加入对应的 `*_FACTORS` 列表，引擎会自动识别。

### 新增策略
在 `quant/strategy/engine.py` 的 `STRATEGY_META` 添加元信息，实现 `_run_xxx()` 方法，加入 handler 字典。

### 新增数据源
参考 `quant/data/tencent_source.py` 或 `akshare_source.py` 的封装模式，实现 fetch 函数 + schema 校验。
