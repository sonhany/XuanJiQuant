<p align="center">
  <img src="Logo/logo_horizontal.svg" width="360" alt="璇玑 XUANJI" />
</p>

<h1 align="center">璇玑 XUANJI · AI 自主进化 A 股量化模拟盘系统</h1>

<p align="center">
  <em>璇玑玉衡，以齐七政 ——《尚书·舜典》</em>
</p>

<p align="center">
  <a href="#2-5-分钟快速开始">快速开始</a> ·
  <a href="#3-整体架构总览">架构总览</a> ·
  <a href="#9-ai-自主系统架构">AI 自主系统</a> ·
  <a href="Logo/璇玑XUANJI品牌设计展示.html">品牌手册</a> ·
  <a href="AI自主架构流程图/AI自主量化系统完整架构图.html">架构流程图</a>
</p>

---

> 本项目是一个面向本地研究与模拟盘验证的 A 股量化系统，覆盖 **数据采集 → 因子计算 → 策略回测 → 模拟执行 → 风控监控 → AI 自主调度/复盘** 的完整闭环。
>
> 默认使用本地 SQLite 作为状态总线和缓存，前端、后端、Python 量化引擎均可在本机一键启动。

## 品牌释义

**璇玑（XUANJI）** 取自《尚书·舜典》「璇玑玉衡，以齐七政」。

- **璇玑** 为上古天文测算玉器，是人类最早的「计算装置」——以七政（日月五星）对应系统的七层架构，寓意以精准推演驾驭市场万象。
- **Logo** 为七角星轮 + 金环 + 金钻中心：
  - **七角星** = 七政 / 七层架构（数据 · 因子 · 策略 · 回测 · 执行 · 风控 · AI 自主调度）
  - **金环** = 璇玑玉衡，硬风控与审计的约束边界
  - **金钻中心** = AI 自主决策中枢
  - **色彩**：青玉（`#0D7A5F → #05412F`，稳健）+ 鎏金（`#D4A531 → #9A7510`，决策）+ 朱砂（风控警示）

> 完整品牌设计手册见 [`Logo/璇玑XUANJI品牌设计展示.html`](Logo/璇玑XUANJI品牌设计展示.html)，Logo 矢量文件见 [`Logo/`](Logo/) 目录。

---

## 目录

1. [项目定位与核心原则](#1-项目定位与核心原则)
2. [5 分钟快速开始](#2-5-分钟快速开始)
3. [整体架构总览](#3-整体架构总览)
4. [运行时链路](#4-运行时链路)
5. [目录结构说明](#5-目录结构说明)
6. [前端架构](#6-前端架构)
7. [Node 后端架构](#7-node-后端架构)
8. [Python 量化核心架构](#8-python-量化核心架构)
9. [AI 自主系统架构](#9-ai-自主系统架构)
10. [状态总线与数据产物](#10-状态总线与数据产物)
11. [API 与面板对应关系](#11-api-与面板对应关系)
12. [常用运行命令](#12-常用运行命令)
13. [配置项与环境变量](#13-配置项与环境变量)
14. [开发、验证与排错](#14-开发验证与排错)
15. [扩展指南](#15-扩展指南)
16. [风险提示](#16-风险提示)

详细流程图与 Mermaid 架构图另见：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 1. 项目定位与核心原则

### 1.1 项目定位

AlphaCouncil2-AI 是一个本地运行的 A 股量化研究与模拟盘系统：

- **研究用途**：用于学习、研究、回测、因子评估、模拟交易和 AI 决策实验。
- **模拟盘用途**：不连接真实券商，不触达真实资金。
- **本地优先**：默认 SQLite，降低部署门槛；Node + Python + React 均运行在本机。
- **AI 可审计**：AI 只在白名单工具、硬风控和审计记录约束下工作。

### 1.2 核心原则

| 原则 | 说明 |
|---|---|
| 硬风控优先 | AI 决策不能绕过风控门禁，风控失败时不交易。 |
| 白名单执行 | 自动动作必须在 `ai_tools.json` 白名单内。 |
| 可审计 | 关键调度、AI 决策、模拟盘动作写入 SQLite KV 状态总线。 |
| 可回滚 | AI 自我改进默认只生成提案，不直接修改生产代码。 |
| 本地隔离 | 默认监听本机地址，控制面请求需要本机、JSON Content-Type 和 token。 |

---

## 2. 5 分钟快速开始

### 2.1 环境要求

- **Node.js 18+**：前端 Vite 与本地 Node API。
- **Python 3.10+**：量化引擎、AI Agent、数据同步脚本。
- **Windows / Git Bash / PowerShell**：项目当前主要面向 Windows 本地运行。

### 2.2 首次安装

Windows 下可直接双击或命令行运行：

```bat
setup.bat
```

该脚本会检查 Node/Python、安装依赖，并按提示初始化少量数据。

等价手动命令：

```bash
npm install
pip install -r requirements.txt
python scripts/seed.py --limit 50 --no-financial
```

### 2.3 日常启动

Windows 下双击：

```bat
start_all.bat
```

或手动分别启动后端与前端：

```bash
# 后端 API，默认 http://localhost:3334
npm run dev:api

# 前端 Vite，默认 http://localhost:3333
npm run dev
```

访问：

- 前端控制台：<http://localhost:3333>
- 后端服务：<http://localhost:3334>

### 2.4 如果启动后无数据

先初始化少量测试数据：

```bash
python scripts/seed.py --limit 50 --no-financial
```

然后刷新前端页面。

---

## 3. 整体架构总览

系统采用四段式本地架构：

```text
React/Vite 前端 3333
  ↓ HTTP /api 代理
Node HTTP API 3334
  ↓ PersistentRunner / spawn Python
Python Runner + 量化核心 + AI Agent
  ↓ create_cache()
SQLite KV 状态总线 data/quant.db
```

### 3.1 总体分层

```text
┌──────────────────────────────────────────────────────────────┐
│ 前端 React + TypeScript + Vite                                │
│ App.tsx + components/*.tsx                                    │
│ 驾驶舱 / 数据浏览 / 因子引擎 / 策略运行 / 执行 / 模拟盘 / 风控 / 告警 │
│ 默认端口: 3333                                                │
└─────────────────────────────┬────────────────────────────────┘
                              │ /api/*
┌─────────────────────────────▼────────────────────────────────┐
│ Node HTTP API                                                  │
│ server/index.mjs + server/router.mjs + server/routes/*.mjs     │
│ 鉴权 / CORS / 静态文件 / 路由分发 / Python 进程管理 / Watchdog     │
│ 默认端口: 3334                                                │
└─────────────────────────────┬────────────────────────────────┘
                              │ stdin/stdout JSON 或 spawn
┌─────────────────────────────▼────────────────────────────────┐
│ Python Runner / AI Agent / 量化核心                            │
│ scripts/*_runner.py + scripts/ai_*.py + quant/*                │
│ 数据 / 因子 / 策略 / 回测 / 执行 / 风控 / AI 自主调度              │
└─────────────────────────────┬────────────────────────────────┘
                              │ cache.get/set
┌─────────────────────────────▼────────────────────────────────┐
│ SQLite KV 状态总线                                             │
│ data/quant.db                                                  │
│ K线、股票池、执行状态、模拟盘状态、AI 决策、日志、告警、报告        │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 核心模块地图

| 层级 | 目录/文件 | 作用 |
|---|---|---|
| 前端入口 | `index.tsx`, `App.tsx` | React 挂载、Tab 导航、指数行情条。 |
| 前端面板 | `components/*.tsx` | 各业务面板，调用 `/api/*`。 |
| 本地 API | `server/index.mjs`, `server/router.mjs` | HTTP 服务、路由、鉴权、静态文件。 |
| 后端路由 | `server/routes/*.mjs` | data/factor/strategy/execution/risk/alerts/market/sync/paper。 |
| 进程管理 | `server/persistent_runner.mjs`, `server/*_manager.mjs`, `server/watchdog.mjs` | Python 常驻 Runner、模拟盘 daemon、AI scheduler、后台更新、看门狗。 |
| Runner | `scripts/*_runner.py` | Node 与 Python 量化核心之间的 JSON action 桥。 |
| 量化核心 | `quant/data`, `quant/factor`, `quant/strategy`, `quant/backtest`, `quant/execution`, `quant/risk` | 数据、因子、策略、回测、执行和风控。 |
| AI 系统 | `scripts/ai_*.py`, `ai_manifest.json`, `ai_tools.json` | 五层 AI Agent、自主调度、工具白名单、总控与验证。 |
| 数据目录 | `data/` | SQLite 数据库、因子/策略预计算结果、运行产物。 |
| 文档目录 | `docs/` | 架构图、Web 与阶段映射等文档。 |

---

## 4. 运行时链路

### 4.1 普通前端查询链路

以前端因子市场榜单为例：

```text
FactorPanel.tsx
  → fetch('/api/factor', { action: 'market_eval' })
  → server/router.mjs
  → server/routes/factor.mjs
  → PersistentRunner('scripts/factor_runner.py')
  → scripts/factor_runner.py
  → quant.factor.FactorEngine 或 data/factor_evaluation.json
  → JSON 返回前端
```

### 4.2 数据浏览链路

```text
DbPanel.tsx
  → /api/data action=stocks/klines/realtime_prices/watchlist_get
  → server/routes/data.mjs
  → scripts/data_runner.py
  → quant.data.cache / quant.data.loader / scripts.market_data
  → data/quant.db
```

### 4.3 策略回测链路

```text
StrategyPanel.tsx
  → /api/strategy action=run
  → scripts/strategy_runner.py
  → quant.strategy.StrategyEngine
  → quant.factor.FactorEngine
  → quant.backtest.BacktestSimulator
  → 返回 signals + backtest 指标
```

### 4.4 模拟交易链路

```text
PaperPanel 或 AI 调度器
  → /api/paper action=run_now 或 paper_trade_once 工具
  → scripts/paper_trader.py --once
  → 读取 ai:decision:latest / paper:config
  → StrategyEngine 生成目标池
  → LLM 个股复核，可选
  → 事前风控
  → scripts/execution_runner.py action_place_order
  → 写 execution:state / paper:status / paper:daily
```

### 4.5 AI 自主闭环链路

```text
DashboardPanel / PaperPanel
  → /api/paper action=ai_scheduler_start
  → server/ai_scheduler_manager.mjs
  → scripts/ai_scheduler.py --daemon
  → 按交易时段运行轻巡检或盘后重巡检
  → scripts/ai_loop.py
     1. global_context 全球动态
     2. L1 ai_data_agent 数据层
     3. L2 ai_factor_agent 因子工厂
     4. L3 ai_strategy_agent 策略工厂
     5. L4 ai_execution_agent 执行建议
     6. L5 ai_risk_agent 风控门禁
     7. ai_operator 总控建议
     8. ai_stock_screener 全市场选股
     9. ai_verifier 自我验证
  → 写 ai:decision:latest
  → 风控和验证通过时，触发受控模拟盘交易
```

---

## 5. 目录结构说明

```text
AlphaCouncil2-AI/
├── App.tsx                         # 前端主应用，Tab 导航与 LiveIndexBar
├── index.tsx                       # React 入口
├── index.html                      # Vite HTML 入口
├── package.json                    # Node/Vite 依赖与脚本
├── requirements.txt                # Python 依赖
├── vite.config.ts                  # Vite 配置，/api 代理到 3334
├── setup.bat                       # 首次安装脚本
├── start_all.bat                   # 一键启动前后端
├── daily_update.bat                # 每日增量更新入口
├── ai_manifest.json                # AI 系统使命、硬约束、指标与审核策略
├── ai_tools.json                   # AI 可执行工具白名单与风控要求
│
├── components/                     # React 面板组件
│   ├── DashboardPanel.tsx          # AI 驾驶舱
│   ├── DbPanel.tsx                 # 数据浏览、自选股、数据同步
│   ├── FactorPanel.tsx             # 因子引擎、因子评估、因子榜单
│   ├── StrategyPanel.tsx           # 策略运行、回测、市场扫描
│   ├── ExecutionPanel.tsx          # 模拟账户、订单、成交、持仓
│   ├── PaperPanel.tsx              # 模拟盘、AI 控制台、日报、LLM 使用量
│   ├── RiskPanel.tsx               # 组合风险、系统健康
│   └── AlertPanel.tsx              # 告警规则、告警列表、确认/处理
│
│
├── server/                         # Node 本地后端
│   ├── index.mjs                   # HTTP 服务入口，启动 watchdog
│   ├── router.mjs                  # 路由分发、鉴权、CORS、静态文件
│   ├── config.mjs                  # 环境变量、端口、token、Python 路径
│   ├── http-utils.mjs              # JSON/body/static/logging 辅助
│   ├── persistent_runner.mjs       # 常驻 Python Runner 管理
│   ├── paper_manager.mjs           # 模拟盘 daemon 管理
│   ├── ai_scheduler_manager.mjs    # AI 自主调度器 daemon 管理
│   ├── update_manager.mjs          # 后台数据更新任务管理
│   ├── watchdog.mjs                # 进程保活与自愈
│   └── routes/
│       ├── data.mjs                # /api/data
│       ├── factor.mjs              # /api/factor
│       ├── strategy.mjs            # /api/strategy
│       ├── execution.mjs           # /api/execution
│       ├── risk.mjs                # /api/risk
│       ├── alerts.mjs              # /api/alerts
│       ├── market.mjs              # /api/market 与指数行情
│       ├── sync.mjs                # /api/sync 数据更新/同步
│       └── paper.mjs               # /api/paper 模拟盘与 AI 聚合 API
│
├── scripts/                        # Python 运行脚本、Runner、AI Agent、验证工具
│   ├── data_runner.py              # 数据 API Runner
│   ├── factor_runner.py            # 因子 API Runner
│   ├── strategy_runner.py          # 策略 API Runner
│   ├── execution_runner.py         # 执行 API Runner
│   ├── risk_runner.py              # 风控 API Runner
│   ├── alert_runner.py             # 告警 API Runner
│   ├── paper_runner.py             # /api/paper 高频只读状态 Runner
│   ├── paper_trader.py             # 模拟盘执行器
│   ├── ai_scheduler.py             # AI 自主调度器
│   ├── ai_loop.py                  # 五层 AI 闭环与统一决策
│   ├── ai_operator.py              # AI 总控建议
│   ├── ai_data_agent.py            # L1 数据层 Agent
│   ├── ai_factor_agent.py          # L2 因子工厂
│   ├── ai_strategy_agent.py        # L3 策略工厂
│   ├── ai_execution_agent.py       # L4 执行建议/复盘
│   ├── ai_risk_agent.py            # L5 风控门禁
│   ├── ai_verifier.py              # 自我验证器
│   ├── ai_action_executor.py       # 白名单工具执行器
│   ├── ai_stock_screener.py        # 全市场 AI 选股
│   ├── ai_memory.py                # 经验记忆沉淀
│   ├── ai_self_improver.py         # 自我改进提案
│   ├── global_context.py           # 全球市场/宏观上下文
│   ├── market_data.py              # 实时行情/市场数据辅助
│   ├── seed.py                     # 初始化少量或指定股票数据
│   ├── download_all.py             # 全市场批量下载
│   ├── daily_update.py             # 每日增量更新
│   ├── evaluate_factors.py         # 全市场因子评估
│   ├── scan_strategies.py          # 全市场策略扫描
│   ├── precompute_snapshot.py      # 因子快照预计算
│   ├── smoke_test.py               # Python 全链路冒烟测试
│   ├── test_api.py                 # API 端到端测试
│   └── ui_verify.mjs               # UI 验证脚本
│
├── quant/                          # Python 量化核心
│   ├── data/                       # 数据源、缓存、schema、loader、同步服务
│   ├── factor/                     # 因子引擎、技术因子、量价因子、基本面因子、IC
│   ├── strategy/                   # 策略引擎与内置策略
│   ├── backtest/                   # 事件驱动回测
│   ├── execution/                  # 执行层核心
│   └── risk/                       # 风险引擎
│
├── data/                           # SQLite、预计算结果、运行产物（本地生成，不入库）
└── docs/                           # 架构文档
```

---

## 6. 前端架构

### 6.1 前端入口

- `index.tsx`：React 挂载入口。
- `App.tsx`：主应用，维护当前 Tab，渲染侧边栏与当前面板。
- `vite.config.ts`：开发服务器端口 `3333`，将 `/api` 代理到 `http://localhost:3334`。

### 6.2 面板列表

| Tab | 组件 | 主要用途 |
|---|---|---|
| 驾驶舱 | `DashboardPanel.tsx` | AI 自主调度器、五层状态、看门狗、LLM 用量总览。 |
| 数据浏览 | `DbPanel.tsx` | 股票池、K 线、自选股、实时行情、数据同步。 |
| 因子引擎 | `FactorPanel.tsx` | 因子元信息、单因子评估、全市场评估、因子选股。 |
| 策略运行 | `StrategyPanel.tsx` | 策略元信息、运行回测、全市场策略扫描。 |
| 交易执行 | `ExecutionPanel.tsx` | 模拟账户、订单、成交、持仓、止盈止损。 |
| 模拟盘 | `PaperPanel.tsx` | 模拟盘配置、启动/停止、手动执行、日志、日报、AI 控制台。 |
| 风控监控 | `RiskPanel.tsx` | 组合风险、系统健康、风控检查。 |
| 监控告警 | `AlertPanel.tsx` | 告警统计、规则、列表、确认、静默、处理。 |

### 6.3 API 调用风格

前端通常使用相对路径调用 API：

```ts
fetch(`${API_BASE}/api/paper`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}),
  },
  body: JSON.stringify({ action: 'status' }),
});
```

其中：

- `VITE_API_BASE`：可覆盖 API base，默认空字符串。
- `VITE_ALPHACOUNCIL_API_TOKEN`：前端发送到后端的控制面 token。
- 开发模式下，`/api/*` 由 Vite 代理到 Node 后端 `3334`。

---

## 7. Node 后端架构

### 7.1 后端入口

`server/index.mjs` 负责：

- 创建 HTTP server。
- 加载 `createRouter()`。
- 默认监听 `127.0.0.1:3334`。
- 启动后延迟开启 `watchdog`，定期保活关键进程。

### 7.2 路由分发

`server/router.mjs` 是统一入口：

| 路径 | 路由文件 | 说明 |
|---|---|---|
| `GET /api/data` | `routes/data.mjs` | 兼容 GET 数据查询。 |
| `GET /api/data/klines` | `routes/data.mjs` | 兼容旧 K 线路径。 |
| `GET /api/market/indices` | `routes/market.mjs` | 顶部指数行情。 |
| `POST /api/data` | `routes/data.mjs` | 数据层 API。 |
| `POST /api/factor` | `routes/factor.mjs` | 因子层 API。 |
| `POST /api/strategy` | `routes/strategy.mjs` | 策略层 API。 |
| `POST /api/execution` | `routes/execution.mjs` | 执行层 API。 |
| `POST /api/risk` | `routes/risk.mjs` | 风控 API。 |
| `POST /api/alerts` | `routes/alerts.mjs` | 告警 API。 |
| `POST /api/market` | `routes/market.mjs` | 实时行情、板块、北向等。 |
| `POST /api/sync` | `routes/sync.mjs` | 数据同步与更新任务。 |
| `POST /api/paper` | `routes/paper.mjs` | 模拟盘 + AI 聚合 API。 |

### 7.3 控制面鉴权

后端区分只读 action 与控制 action：

- 只读 action 允许直接访问。
- 控制 action 需要满足：
  1. 请求来自本机。
  2. `Content-Type` 包含 `application/json`。
  3. Origin 在允许列表内。
  4. 请求头 `X-AlphaCouncil-Token` 或 body.token 匹配 `ALPHACOUNCIL_API_TOKEN`。

相关逻辑位于 `server/router.mjs`。

### 7.4 PersistentRunner

`server/persistent_runner.mjs` 用于降低 Python 冷启动成本。

工作方式：

```text
Node route
  → PersistentRunner.ensure()
  → 启动 scripts/xxx_runner.py 常驻子进程
  → Node 向 stdin 写一行 JSON，附带 __id
  → Python 处理 action
  → Python stdout 返回一行 JSON，带同样 __id
  → Node 按 __id 匹配响应并返回 HTTP
```

适合高频、短耗时查询，例如：

- `data_runner.py`
- `factor_runner.py`
- `strategy_runner.py`
- `execution_runner.py`
- `risk_runner.py`
- `alert_runner.py`
- `paper_runner.py`

### 7.5 进程管理与看门狗

| 文件 | 职责 |
|---|---|
| `paper_manager.mjs` | 启停 `scripts/paper_trader.py` daemon，维护模拟盘进程状态。 |
| `ai_scheduler_manager.mjs` | 启停 `scripts/ai_scheduler.py --daemon`，维护 AI 自主调度器状态。 |
| `update_manager.mjs` | 后台触发 `scripts/daily_update.py`。 |
| `watchdog.mjs` | 定期检查 paper trader、AI scheduler、PersistentRunner，必要时自愈。 |

---

## 8. Python 量化核心架构

### 8.1 Runner 层

Runner 是 Node API 和 Python 核心之间的 action 适配层。

| Runner | 主要 action | 主要依赖 |
|---|---|---|
| `scripts/data_runner.py` | `stocks`, `klines`, `stats`, `realtime_prices`, `indices`, `watchlist_*` | `quant.data.cache`, `quant.data.loader`, `scripts.market_data` |
| `scripts/factor_runner.py` | `meta`, `factors`, `evaluate`, `evaluate_all`, `market_eval`, `factor_stocks` | `quant.factor.FactorEngine`, `data/factor_evaluation.json` |
| `scripts/strategy_runner.py` | `meta`, `run`, `backtest`, `batch_evaluate`, `factor_ic_detail`, `market_scan` | `quant.strategy.StrategyEngine`, `quant.backtest.BacktestSimulator` |
| `scripts/execution_runner.py` | `all`, `status`, `positions`, `orders`, `trades`, `place_order`, `fill_order`, `cancel_order`, `check_stops`, `reset` | `execution:state`, `execution:stops` |
| `scripts/risk_runner.py` | `portfolio_risk`, `system_health`, `check`, `system_log` | `quant.risk.RiskEngine` |
| `scripts/alert_runner.py` | `list`, `rules`, `stats`, `check`, `acknowledge`, `resolve`, `silence`, `update_rule` | 告警状态与规则 |
| `scripts/paper_runner.py` | `status`, `progress`, `log`, `report`, `ai_all_status`, `ai_scheduler_status`, `llm_usage` 等 | SQLite KV 高频只读状态 |

### 8.2 数据层：`quant/data`

| 文件 | 说明 |
|---|---|
| `cache.py` | 默认 SQLite KV 缓存，也支持 Redis/Memory。 |
| `schema.py` | K 线与数据字段规范。 |
| `loader.py` | 从缓存加载股票池与 K 线为 DataFrame。 |
| `tencent_source.py` | 腾讯数据源封装。 |
| `akshare_source.py` | AKShare 财务/特色数据源封装。 |
| `baostock_source.py` | Baostock 数据源封装。 |
| `sync_service.py` | 常驻同步服务。 |
| `health.py` | 数据健康检查。 |

默认缓存位置：

```text
data/quant.db
```

核心 key 示例：

```text
stock:universe
stock:name:<code>
kline:<code>:d
kline:<code>:intraday
stock:realtime:<code>
watchlist:default
```

### 8.3 因子层：`quant/factor`

`FactorEngine` 统一计算技术因子、量价因子和基本面因子，并支持多股票批量计算与 IC 评估。

#### 当前内置 58 个因子

| 类别 | 数量 | 因子 |
|---|---:|---|
| 技术因子 | 19 | `ema_12`, `ema_26`, `macd_dif`, `macd_dea`, `macd_hist`, `rsi_6`, `rsi_12`, `rsi_24`, `kdj_k`, `kdj_d`, `kdj_j`, `boll_mid`, `boll_upper`, `boll_lower`, `atr_14`, `williams_r_14`, `roc_10`, `cci_20`, `bias_20` |
| 量价因子 | 28 | `ret_1`, `ret_5`, `ret_10`, `ret_20`, `ret_60`, `reversal_3`, `reversal_5`, `reversal_10`, `volatility_5`, `volatility_20`, `volatility_60`, `range_pct`, `pvcorr_5`, `pvcorr_10`, `pvcorr_20`, `pvbeta_20`, `mfi_14`, `obv_slope_10`, `ad_slope_10`, `vwap_dev_20`, `turnover_5`, `turnover_20`, `vol_ratio_5`, `amt_ratio_5`, `trend_strength`, `gap_pct`, `intraday_ret`, `overnight_ret` |
| 基本面因子 | 11 | `roe`, `roa`, `gross_margin`, `net_margin`, `revenue_growth`, `profit_growth`, `debt_ratio`, `current_ratio`, `inventory_turnover`, `receivable_turnover`, `asset_turnover` |

> 注意：基本面因子需要财务数据，且实盘使用时必须处理财报发布日期滞后，否则存在前视偏差风险。

### 8.4 策略层：`quant/strategy`

当前内置 4 类策略：

| 策略名 | 中文名 | 说明 |
|---|---|---|
| `factor_rank` | 单因子排名 | 多股截面按因子 Z-Score 排序；单股模式按阈值交易。 |
| `multi_factor` | 多因子加权 | 多个因子 Z-Score 加权求和，生成交易信号。 |
| `ma_cross` | 均线交叉 | 短期均线上穿长期均线买入，下穿卖出。 |
| `bb_reversion` | 布林带回归 | 价格触及下轨买入，触及上轨卖出。 |

策略输出 signals 后进入 `quant.backtest.BacktestSimulator` 做事件驱动回测。

### 8.5 回测层：`quant/backtest`

`BacktestSimulator` 负责：

- 事件驱动回测。
- 账户资金曲线。
- 手续费、滑点、仓位比例。
- 收益、夏普、最大回撤、胜率等指标。

### 8.6 执行层：`quant/execution` 与 `scripts/execution_runner.py`

模拟执行状态主要由 `scripts/execution_runner.py` 管理：

- 账户现金。
- 持仓。
- 订单。
- 成交。
- 止损/止盈状态。
- A 股规则近似：T+1、整手、手续费、印花税、过户费、滑点、涨跌停约束。

核心状态 key：

```text
execution:state
execution:stops
```

### 8.7 风控层：`quant/risk`

风控层负责：

- 组合风险计算。
- 持仓集中度。
- 波动率与 VaR 类指标。
- 系统健康检查。
- 系统日志/异常状态。

---

## 9. AI 自主系统架构

AI 系统围绕 `ai_manifest.json` 和 `ai_tools.json` 运行。

### 9.1 AI 硬约束

`ai_manifest.json` 定义使命和硬约束，关键约束包括：

- 不得绕过硬风控规则。
- 不得执行未在 `ai_tools.json` 白名单内的动作。
- 不得直接执行 LLM 生成的任意 shell 命令或代码。
- 不得删除交易、风控、回测、审计日志。
- 不得自动启用未经验证的新因子、新策略或代码修改。
- 不得默认连接实盘交易接口。
- 代码自我更新只能生成提案和验证建议，默认不直接修改生产代码。

### 9.2 工具白名单

`ai_tools.json` 当前包含：

| 工具 | 风险 | 自动执行 | 说明 |
|---|---|---|---|
| `refresh_data` | medium | 是 | 同步股票池并增量刷新 K 线。 |
| `evaluate_factors` | medium | 是 | 重新计算因子评估快照。 |
| `run_factor_factory` | medium | 是 | 运行 AI 因子工厂。 |
| `run_strategy_factory` | medium | 是 | 运行 AI 策略工厂。 |
| `run_stock_screener` | medium | 是 | 全市场因子打分和 AI 复核选股。 |
| `run_risk_monitor` | low | 是 | 运行 L5 风控监控和自我验证。 |
| `run_verifier` | low | 是 | 运行统一自我验证器。 |
| `paper_trade_once` | high | 是，但需风控通过 | 执行一次受控模拟盘交易循环。 |
| `memory_compact` | low | 是 | 压缩 AI 经验记忆。 |
| `self_improve_propose` | high | 否 | 生成代码/策略改进提案，不直接修改生产代码。 |

### 9.3 L0 + L1-L5 架构

| 层 | 模块 | 职责 |
|---|---|---|
| L0 总控 | `ai_loop.py`, `ai_operator.py` | 编排五层、汇总决策、写 `ai:decision:latest`。 |
| L1 数据层 | `ai_data_agent.py` | 数据完整性、新鲜度、自动补数。 |
| L2 因子工厂 | `ai_factor_agent.py` | 生成候选因子、验证 IC/IR、Shadow → Approved。 |
| L3 策略工厂 | `ai_strategy_agent.py` | 生成策略配置、自动回测、与基线对比。 |
| L4 执行层 | `ai_execution_agent.py` | 执行建议、订单质量分析、执行复盘。 |
| L5 风控层 | `ai_risk_agent.py` | 硬风控门禁、自我验证、禁止异常交易。 |

### 9.4 自主调度器

`scripts/ai_scheduler.py` 是 AI 系统的主心跳。

运行模式：

| 模式 | 时间 | 行为 |
|---|---|---|
| `intraday` | 交易日 09:30-15:00 | 轻巡检：全球动态、数据新鲜度、L5 风控、止盈止损检查。 |
| `postclose` | 交易日 15:00-23:59 | 重巡检：数据更新、因子评估、AI 闭环、必要时触发模拟盘。 |
| `idle` | 夜间/非交易日 | 低频巡检：全球动态、数据新鲜度。 |

常用入口：

```bash
python scripts/ai_scheduler.py --daemon
python scripts/ai_scheduler.py --once
python scripts/ai_scheduler.py --status
```

### 9.5 AI 闭环

`scripts/ai_loop.py` 负责单轮完整 AI 闭环，并通过 `ai:loop:lock` 防止并发。

典型步骤：

1. 收集全球实时动态。
2. 运行 L1 数据层检查。
3. 运行 L2 因子工厂。
4. 运行 L3 策略工厂。
5. 运行 L4 执行建议。
6. 运行 L5 风控验证。
7. 运行 AI Operator 总控。
8. 运行全市场 AI 选股。
9. 形成统一决策并写入 `ai:decision:latest`。
10. 运行自我验证器。
11. 经验沉淀。
12. 在允许时通过白名单工具触发 `paper_trade_once`。

### 9.6 模拟盘执行器

`scripts/paper_trader.py` 负责真正的模拟盘执行。

执行前会读取：

- `paper:config`：模拟盘配置。
- `ai:decision:latest`：AI 统一决策。
- `execution:state`：当前账户与持仓。

关键保护：

- `paper:lock` 防止多进程并发交易。
- `ai:decision:latest.trade_policy` 非 `normal` 时跳过交易。
- 数据过期时跳过或尝试补数。
- 风控失败时跳过。
- 同日同股同方向幂等保护。

---

## 10. 状态总线与数据产物

### 10.1 SQLite KV 状态总线

项目默认通过 `quant.data.cache.create_cache()` 使用 SQLite KV。

默认数据库：

```text
data/quant.db
```

表结构类似：

```text
kv(key TEXT PRIMARY KEY, value TEXT, exp REAL)
```

这相当于本项目的轻量 Redis，用于跨 Node/Python/Runner/Agent 共享状态。

### 10.2 关键状态 key

| 类别 | key 示例 | 说明 |
|---|---|---|
| 股票与行情 | `stock:universe`, `stock:name:<code>`, `kline:<code>:d`, `stock:realtime:<code>` | 股票池、名称、日 K、实时价。 |
| 自选股 | `watchlist:default` | 默认自选股列表。 |
| 执行状态 | `execution:state`, `execution:stops` | 模拟账户、订单、成交、持仓、止盈止损。 |
| 模拟盘 | `paper:config`, `paper:status`, `paper:progress`, `paper:log`, `paper:daily:<date>`, `paper:report:latest` | 模拟盘配置、状态、日志、日报。 |
| AI 调度 | `ai:scheduler:config`, `ai:scheduler:latest`, `ai:scheduler:log` | 自主调度器配置与状态。 |
| AI 闭环 | `ai:loop:latest`, `ai:loop:progress`, `ai:loop:log`, `ai:loop:lock` | 五层闭环状态、进度、互斥锁。 |
| AI 决策 | `ai:decision:latest` | 统一宏观交易决策。 |
| AI Agent | `ai:data:latest`, `ai:factor:*`, `ai:strategy:*`, `ai:execution:latest`, `ai:risk:latest`, `ai:operator:latest` | 各层 Agent 输出。 |
| 告警 | `alerts:records`, `alerts:rules` | 告警记录与规则。 |
| 全球上下文 | `global:context:latest` | 宏观/全球动态上下文。 |
| 看门狗 | `ai:watchdog:latest` | Watchdog 最近检查结果。 |

### 10.3 预计算与运行产物

| 文件 | 说明 |
|---|---|
| `data/factor_evaluation.json` | 全市场因子评估结果，供因子面板市场榜单读取。 |
| `data/factor_evaluation_neutral.json` | 中性化/增强版本因子评估结果。 |
| `data/factor_snapshot.pkl` | 全市场最新截面因子快照。 |
| `data/strategy_scan.json` | 全市场策略扫描结果。 |
| `data/strategy_scan_realistic.json` | 更现实约束下的策略扫描结果。 |
| `data/download_progress.json` | 批量下载断点与进度。 |
| `data/*.log` | 同步、扫描、快照、中性化等运行日志。 |
| `server.log`, `server.*.log`, `vite.verify.log` | 后端和前端验证日志。 |

---

## 11. API 与面板对应关系

### 11.1 `/api/data`

主要面板：`DbPanel.tsx`

常见 action：

```text
stocks
klines
stats
realtime_prices
indices
sector_flow
northbound
watchlist_get
watchlist_set
watchlist_add
watchlist_remove
watchlist_reset
```

### 11.2 `/api/factor`

主要面板：`FactorPanel.tsx`

常见 action：

```text
meta
factors
evaluate
evaluate_all
market_eval
market_evaluation
factor_stocks
```

### 11.3 `/api/strategy`

主要面板：`StrategyPanel.tsx`

常见 action：

```text
meta
run
backtest
batch_evaluate
factor_ic_detail
market_scan
```

### 11.4 `/api/execution`

主要面板：`ExecutionPanel.tsx`

常见 action：

```text
all
status
positions
orders
trades
place_order
fill_order
cancel_order
update_price
set_stop_loss
check_stops
stop_status
reset
```

### 11.5 `/api/risk`

主要面板：`RiskPanel.tsx`

常见 action：

```text
portfolio_risk
system_health
check
system_log
```

### 11.6 `/api/alerts`

主要面板：`AlertPanel.tsx`

常见 action：

```text
stats
list
rules
check
acknowledge
resolve
update_rule
silence
```

### 11.7 `/api/sync`

主要面板：`DbPanel.tsx`

常见 action：

```text
status
progress
update_progress
daemon_status
start_update
stop_update
start
stop
```

### 11.8 `/api/paper`

主要面板：`DashboardPanel.tsx`, `PaperPanel.tsx`

模拟盘 action：

```text
status
get_config
set_config
start
stop
run_now
progress
log
report
generate_report
benchmark
```

AI 控制台 action：

```text
ai_all_status
ai_all_run
ai_scheduler_status
ai_scheduler_start
ai_scheduler_stop
ai_scheduler_run_once
ai_loop_status
ai_loop_run
ai_operator_status
ai_operator_run
ai_screen_status
ai_screen_run
ai_verifier_status
ai_verifier_run
ai_tool_executor_status
ai_tool_executor_run
ai_self_improve_propose
global_context_status
global_context_run
watchdog_status
llm_usage
llm_usage_reset
test_llm
```

五层 Agent action：

```text
ai_data_run
ai_factor_run
ai_strategy_run
ai_execution_run
ai_execution_review
ai_risk_run
```

---

## 12. 常用运行命令

### 12.1 安装与启动

```bash
npm install
pip install -r requirements.txt
npm run dev:api
npm run dev
```

Windows 一键：

```bat
setup.bat
start_all.bat
```

### 12.2 构建与预览

```bash
npm run build
npm run preview
```

### 12.3 数据初始化与下载

```bash
# 少量测试数据
python scripts/seed.py --limit 50 --no-financial

# 指定股票
python scripts/seed.py --codes 600519,000001,300750

# 默认初始化
python scripts/seed.py

# 全市场下载，K线 + 财务
python scripts/download_all.py --phase both

# 仅 K 线
python scripts/download_all.py --phase kline
```

### 12.4 每日更新

```bash
# 每日增量更新
python scripts/daily_update.py

# 含财务刷新
python scripts/daily_update.py --financial
```

Windows 双击：

```bat
daily_update.bat
```

### 12.5 因子与策略预计算

```bash
# 全市场因子评估
python scripts/evaluate_factors.py

# 全市场策略扫描
python scripts/scan_strategies.py

# 因子快照预计算
python scripts/precompute_snapshot.py
```

### 12.6 同步服务

```bash
python quant/data/sync_service.py
```

### 12.7 模拟盘

```bash
# daemon 模式
python scripts/paper_trader.py

# 单次执行
python scripts/paper_trader.py --once

# 指定来源
python scripts/paper_trader.py --once --source manual
```

### 12.8 AI 调度器

```bash
# 常驻调度器
python scripts/ai_scheduler.py --daemon

# 当前时段跑一轮
python scripts/ai_scheduler.py --once

# 查看状态
python scripts/ai_scheduler.py --status
```

### 12.9 AI 闭环与总控

```bash
# 跑一轮 AI 闭环
python scripts/ai_loop.py --once

# 跑一轮 AI 闭环，并允许触发受控模拟盘
python scripts/ai_loop.py --once --trigger-paper

# 查看 AI 闭环状态
python scripts/ai_loop.py --status

# AI Operator
python scripts/ai_operator.py --run
python scripts/ai_operator.py --status
```

### 12.10 验证测试

```bash
# Python 全链路冒烟测试
python scripts/smoke_test.py

# API 端到端测试，需要后端已运行
python scripts/test_api.py --reset

# UI 验证，需要前后端已运行
node scripts/ui_verify.mjs
```

---

## 13. 配置项与环境变量

### 13.1 Node/前端配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `PORT` | Node 后端端口 | `3334` |
| `HOST` | Node 后端监听地址 | `127.0.0.1` |
| `ALPHACOUNCIL_API_TOKEN` | 控制面请求 token | 空，需要自行配置 |
| `ALLOWED_ORIGINS` | 允许跨域来源 | `http://localhost:3333,http://127.0.0.1:3333` |
| `VITE_API_BASE` | 前端 API base | 空字符串 |
| `VITE_ALPHACOUNCIL_API_TOKEN` | 前端发送的 API token | 空字符串 |

### 13.2 Python/数据配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `QUANT_CACHE` | 缓存后端，可选 `sqlite` / `redis` / `memory` | `sqlite` |
| `PYTHONPATH` | Python 模块查找路径 | 建议设为项目根目录，或在项目根目录运行脚本 |

默认 SQLite，无需 Redis。如需 Redis：

```bash
# Windows CMD
set QUANT_CACHE=redis

# PowerShell
$env:QUANT_CACHE = "redis"
```

### 13.3 LLM/API Key

`.env.example` 中包含示例：

```text
GEMINI_API_KEY=
DEEPSEEK_API_KEY=
JUHE_API_KEY=
QWEN_API_KEY=
```

实际 `.env` 不应提交到仓库。

### 13.4 AI 运行配置

| 文件 | 说明 |
|---|---|
| `ai_manifest.json` | AI 使命、硬约束、指标、审核策略。 |
| `ai_tools.json` | 白名单工具、风险等级、自动执行开关、每日次数、超时。 |
| `paper:config` | 存在 SQLite KV 中，控制模拟盘策略、股票池、仓位、LLM 等。 |
| `ai:scheduler:config` | 存在 SQLite KV 中，控制自主调度器启用状态。 |

---

## 14. 开发、验证与排错

### 14.1 推荐开发验证顺序

修改代码后建议依次运行：

```bash
python scripts/smoke_test.py
python scripts/test_api.py --reset
node scripts/ui_verify.mjs
```

说明：

- `smoke_test.py`：验证 Python 存储、数据、因子、策略、执行、风控、导入链路。
- `test_api.py`：验证后端 API action。
- `ui_verify.mjs`：验证前端渲染、API 响应和控制台错误。

### 14.2 常见问题

#### 前端显示“正在连接行情...”或数据为空

通常是数据库未初始化。运行：

```bash
python scripts/seed.py --limit 50 --no-financial
```

#### 改了 Python 代码但前端还是旧逻辑

后端使用 PersistentRunner 常驻 Python 子进程。修改 Python 后需要重启 Node 后端，并清理残留 Python 进程。

Windows 粗暴方式：

```bat
taskkill /f /im node.exe
taskkill /f /im python.exe
```

更精确方式可按项目路径过滤 Python 进程。

#### 端口 3333/3334 被占用

关闭已有 Node/Vite 进程，或修改 `vite.config.ts` / `server/config.mjs` 对应端口。

#### 报错 `ImportError: quant...`

确认在项目根目录运行，或设置：

```bash
export PYTHONPATH=.
```

Windows CMD：

```bat
set PYTHONPATH=.
```

#### 免费数据源超时

腾讯、AKShare、Baostock 等免费数据源可能出现超时或限流。可稍后重跑，或降低批量下载范围。

#### 控制面请求 403

检查：

1. 是否从本机访问。
2. 是否使用 `Content-Type: application/json`。
3. 是否配置 `ALPHACOUNCIL_API_TOKEN`。
4. 前端是否设置 `VITE_ALPHACOUNCIL_API_TOKEN`。
5. Origin 是否在 `ALLOWED_ORIGINS` 内。

---

## 15. 扩展指南

### 15.1 新增因子

推荐位置：

- 技术因子：`quant/factor/technical.py`
- 量价因子：`quant/factor/price_volume.py`
- 基本面因子：`quant/factor/fundamental.py`

一般步骤：

1. 添加计算逻辑，输出列名保持稳定。
2. 将因子名加入对应 `*_FACTORS` 列表。
3. 确认 `FactorEngine` 能自动拼接并计算。
4. 运行：

```bash
python scripts/smoke_test.py
python scripts/evaluate_factors.py
```

### 15.2 新增策略

推荐位置：`quant/strategy/engine.py`

一般步骤：

1. 在 `STRATEGY_META` 添加策略元信息。
2. 实现 `_run_xxx()` 策略函数，输出 signals。
3. 在 `run_strategy()` handler 字典中注册策略。
4. 用 `scripts/strategy_runner.py` 或前端策略面板验证。

### 15.3 新增 API action

一般步骤：

1. 在对应 `server/routes/*.mjs` 增加 action 分发。
2. 在对应 `scripts/*_runner.py` 增加 action 处理。
3. 如为只读 action，在 `server/router.mjs` 的 `READ_ONLY_ACTIONS` 中登记。
4. 前端组件调用 `/api/xxx`。
5. 运行 API 测试。

### 15.4 新增 AI 工具

一般步骤：

1. 在 `ai_tools.json` 增加工具定义：风险等级、是否允许自动执行、次数限制、超时、是否要求数据新鲜/风控通过。
2. 在 `scripts/ai_action_executor.py` 中实现实际执行逻辑。
3. 确保工具不执行任意 LLM 生成代码。
4. 高风险工具默认应要求风控通过或人工审核。

### 15.5 新增数据源

参考：

- `quant/data/tencent_source.py`
- `quant/data/akshare_source.py`
- `quant/data/baostock_source.py`

建议要求：

- 返回字段符合 `quant/data/schema.py`。
- 失败时可重试且不污染已有缓存。
- 写入 key 命名与现有 K 线/财务数据保持一致。

---

## 16. 风险提示

- 本项目仅用于量化研究、教学和模拟盘验证。
- 系统不连接真实券商，不应直接用于实盘交易。
- 免费数据源可能不稳定，数据可能延迟、缺失或被限流。
- 回测结果不代表未来收益，模拟盘结果不代表实盘表现。
- 基本面因子如未按财报实际发布日期处理，可能存在前视偏差。
- 如需实盘交易，必须接入合规券商接口，并重新设计认证、权限、风控、审计和灾备流程。
