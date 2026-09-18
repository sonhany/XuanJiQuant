> **历史参考快照，不代表当前运行状态。** 本文保留旧设计、旧验证结果和迁移记录，仅用于审计追溯；其中日期、模型 provider、接口 action、命令输出和服务状态均可能过期。后续排查与模型交接必须以根目录 `README.md`、当前代码、当前进程会话和最新日志为准。

<p align="center">
  <img src="Logo/logo_horizontal.svg" width="360" alt="璇玑 XUANJI" />
</p>

> Qlib 本机训练的当前安装状态、数据链路、模型结果、操作命令和后续工作见
> [`docs/QLIB_LOCAL_TRAINING.md`](docs/QLIB_LOCAL_TRAINING.md)。

<h1 align="center">璇玑 XUANJI · AI 研究建议 + 硬规则门禁 A 股量化模拟盘系统</h1>

<p align="center">
  <em>璇玑玉衡，以齐七政 ——《尚书·舜典》</em>
</p>

<p align="center">
  <a href="#2-5-分钟快速开始">快速开始</a> ·
  <a href="#3-整体架构总览">架构总览</a> ·
  <a href="#9-ai-研究与门禁系统架构">AI 研究与门禁系统</a> ·
  <a href="Logo/璇玑XUANJI品牌设计展示.html">品牌手册</a> ·
  <a href="AI自主架构流程图/AI自主量化系统完整架构图.html">架构流程图</a>
</p>

> 术语边界：AI 调度/AI 闭环表示自动研究、筛选、生成组合建议和提交受控交易意图；最终执行必须通过数据新鲜度、verifier、risk gateway、白名单工具和熔断规则。系统不承诺 AI 绕过硬规则的全权交易。AI 的定位是提高 alpha 与执行效率，不承担爆仓防护、合规裁判、熔断开关等“保命”职责。

---

> 本项目是一个面向本地研究与模拟盘验证的 A 股量化系统，覆盖 **数据采集 → 因子计算 → 策略回测 → 模拟执行 → 风控监控 → AI 研究建议/复盘 + 硬规则门禁** 的完整闭环。
>
> 默认使用本地 SQLite 作为状态总线和缓存，前端、后端、Python 量化引擎均可在本机一键启动。

## 品牌释义

**璇玑（XUANJI）** 取自《尚书·舜典》「璇玑玉衡，以齐七政」。

- **璇玑** 为上古天文测算玉器，是人类最早的「计算装置」——以七政（日月五星）对应系统的七层架构，寓意以精准推演驾驭市场万象。
- **Logo** 为七角星轮 + 金环 + 金钻中心：
  - **七角星** = 七政 / 七层架构（数据 · 因子 · 策略 · 回测 · 执行 · 风控 · AI 研究建议）
  - **金环** = 璇玑玉衡，硬风控与审计的约束边界
  - **金钻中心** = AI 研究建议与硬规则门禁中枢
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
9. [AI 研究与门禁系统架构](#9-ai-研究与门禁系统架构)
10. [状态总线与数据产物](#10-状态总线与数据产物)
11. [API 与面板对应关系](#11-api-与面板对应关系)
12. [常用运行命令](#12-常用运行命令)
13. [配置项与环境变量](#13-配置项与环境变量)
14. [开发、验证与排错](#14-开发验证与排错)
15. [扩展指南](#15-扩展指南)
16. [风险提示](#16-风险提示)
17. [数据层重建基线](#17-数据层重建基线)
18. [Qlib 单独验证基线](#18-qlib-单独验证基线)
19. [项目健康巡检基线](#19-项目健康巡检基线)
20. [股票估值研究工作台](#20-股票估值研究工作台)

详细流程图与 Mermaid 架构图另见：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 1. 项目定位与核心原则

### 1.1 项目定位

XuanJiQuant 是一个本地运行的 A 股量化研究与模拟盘系统：

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
# 后端 API，默认 http://localhost:8880
npm run dev:api

# 前端 Vite，默认 http://localhost:8888
npm run dev
```

访问：

- 前端控制台：<http://localhost:8888>
- 后端服务：<http://localhost:8880>

### 2.4 启动性能与下次运行基线

当前推荐继续使用 `start_all.bat` 一键启动。该脚本会优先直接调用本地 `node_modules\vite\bin\vite.js`，避免 `npx vite` 带来的额外启动开销。

最近一次干净启动基线（2026-07-12，多次冷启动观测范围）：

| 指标 | 结果 |
|---|---:|
| 后端 API / 首个功能接口可用 | 约 4.8-5.9 秒 |
| 前端 Vite ready / HTTP 可访问 | 约 0.7-2.2 秒 |
| 前后端基础可用总耗时 | 通常小于 7 秒 |
| watchdog 恢复 paper/AI daemon | 后端启动约 30-40 秒后完成 |

启动后应固定监听：

```text
http://127.0.0.1:8888  前端
http://127.0.0.1:8880  后端 API
```

如果端口被占用，先关闭旧的本项目 Node/Vite/Python 进程，再启动。不要让 Vite 自动漂移到 `3335`，否则前端代理和验证脚本可能连到旧服务。

快速确认端口：

```powershell
$lines = cmd /c netstat -ano
$lines | Select-String -Pattern ':8888\s+.*LISTENING|:8880\s+.*LISTENING'
```

### 2.5 如果启动后无数据

先初始化少量测试数据：

```bash
python scripts/seed.py --limit 50 --no-financial
```

然后刷新前端页面。

---

## 3. 整体架构总览

系统采用四段式本地架构：

```text
React/Vite 前端 8888
  ↓ HTTP /api 代理
Node HTTP API 8880
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
│ 默认端口: 8888                                                │
└─────────────────────────────┬────────────────────────────────┘
                              │ /api/*
┌─────────────────────────────▼────────────────────────────────┐
│ Node HTTP API                                                  │
│ server/index.mjs + server/router.mjs + server/routes/*.mjs     │
│ 鉴权 / CORS / 静态文件 / 路由分发 / Python 进程管理 / Watchdog     │
│ 默认端口: 8880                                                │
└─────────────────────────────┬────────────────────────────────┘
                              │ stdin/stdout JSON 或 spawn
┌─────────────────────────────▼────────────────────────────────┐
│ Python Runner / AI Agent / 量化核心                            │
│ scripts/*_runner.py + scripts/ai_*.py + quant/*                │
│ 数据 / 因子 / 策略 / 回测 / 执行 / 风控 / AI 研究建议              │
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
| AI 系统 | `scripts/ai_*.py`, `ai_manifest.json`, `ai_tools.json` | 五层 AI Agent、研究建议、工具白名单、硬规则门禁与验证。 |
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
  → /api/data action=stocks/klines/realtime_prices/watchlist_get/watchlist_add/ticks
  → server/routes/data.mjs
  → scripts/data_runner.py
  → quant.data.cache / quant.data.loader / scripts.market_data
  → data/quant.db
```

补充交互：

- `数据浏览 > 市场浏览` 默认展示按成交额排序的 Top100 股票，并支持 5 秒轮询刷新。
- Top100 行支持鼠标右键菜单，采用与金十数据快讯相同的实用交互模式：行触发上下文事件，公共菜单层统一渲染。
- 右键菜单提供 `AI 委员会分析（华尔街13位）`、`股票估值`、`K线走势`、`加入自选股` 四个操作。
- `股票估值` 会跳转到独立研究工作台，并自动运行绝对估值、相对估值和市场估值；GLM 模型估值只允许人工点击触发。
- `K线走势` 会跳转到当前股票 K 线页面；`加入自选股` 会调用 `watchlist_add` 持久化到后端；AI 委员会分析只读展示，不构成自动下单指令。

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
  → LLM 个股置信度复核，可选；只能重排既有候选，不能新增/删除/替代候选池
  → quant.risk.gateway.check_order 同步阻塞式事前风控
  → scripts/execution_runner.py action_place_order
  → 写 execution:state / paper:status / paper:daily
```

### 4.5 AI 研究建议与硬规则门禁链路

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
  → 风控、验证与硬规则门禁全部通过时，触发受控模拟盘交易
```

---

## 5. 目录结构说明

```text
XuanJiQuant/
├── App.tsx                         # 前端主应用，Tab 导航与 LiveIndexBar
├── index.tsx                       # React 入口
├── index.html                      # Vite HTML 入口
├── package.json                    # Node/Vite 依赖与脚本
├── requirements.txt                # Python 依赖
├── vite.config.ts                  # Vite 配置，/api 代理到 8880
├── setup.bat                       # 首次安装脚本
├── start_all.bat                   # 一键启动前后端
├── daily_update.bat                # 每日增量更新入口
├── ai_manifest.json                # AI 系统使命、硬约束、指标与审核策略
├── ai_tools.json                   # AI 可执行工具白名单与风控要求
│
├── components/                     # React 面板组件
│   ├── DashboardPanel.tsx          # AI 驾驶舱
│   ├── DbPanel.tsx                 # 数据浏览、自选股、数据同步
│   ├── ValuationPanel.tsx          # 四轨股票估值研究工作台
│   ├── FactorPanel.tsx             # 因子引擎、因子评估、因子榜单
│   ├── StrategyPanel.tsx           # 策略运行、回测、市场扫描
│   ├── ExecutionPanel.tsx          # 模拟账户、订单、成交、持仓
│   ├── PaperPanel.tsx              # 模拟盘、AI 控制台、日报、LLM 使用量
│   ├── RiskPanel.tsx               # 组合风险、系统健康
│   ├── AlertPanel.tsx              # 告警规则、告警列表、确认/处理
│   ├── Jin10DataPanel.tsx          # 金十 MCP 数据页
│   └── QlibResearchPanel.tsx       # Qlib 独立研究页
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
│   ├── sync_service_manager.mjs    # 实时数据同步 daemon 管理
│   ├── update_manager.mjs          # 持久化后台数据更新任务管理
│   ├── watchdog.mjs                # 进程保活与自愈
│   ├── watchdog_worker.mjs         # 独立 Worker 运行 watchdog，隔离 HTTP 主线程
│   └── routes/
│       ├── data.mjs                # /api/data
│       ├── factor.mjs              # /api/factor
│       ├── strategy.mjs            # /api/strategy
│       ├── execution.mjs           # /api/execution
│       ├── risk.mjs                # /api/risk
│       ├── alerts.mjs              # /api/alerts
│       ├── market.mjs              # /api/market 与指数行情
│       ├── sync.mjs                # /api/sync 数据更新/同步
│       ├── paper.mjs               # /api/paper 模拟盘与 AI 聚合 API
│       ├── jin10.mjs               # /api/jin10 金十 MCP 聚合 API
│       ├── qlib.mjs                # /api/qlib Qlib 独立研究 API
│       └── valuation.mjs           # /api/valuation 股票估值 API
│
├── scripts/                        # Python 运行脚本、Runner、AI Agent、验证工具
│   ├── data_runner.py              # 数据 API Runner
│   ├── sync_runner.py              # 数据管理轻量状态/健康/持久化 Runner
│   ├── factor_runner.py            # 因子 API Runner
│   ├── strategy_runner.py          # 策略 API Runner
│   ├── execution_runner.py         # 执行 API Runner
│   ├── risk_runner.py              # 风控 API Runner
│   ├── alert_runner.py             # 告警 API Runner
│   ├── paper_runner.py             # /api/paper 高频只读状态 Runner
│   ├── qlib_runner.py              # /api/qlib 只读状态、目录、样例因子 Runner
│   ├── valuation_runner.py         # /api/valuation 常驻估值 Runner
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
│   ├── ui_verify.mjs               # UI 验证脚本
│   ├── rebuild_financials_full.py  # 全市场历史多期财报采集 (平铺格式)
│   ├── supplement_current_ratio.py # current_ratio 数据源补充采集
│   ├── full_validation.py          # 全量功能验证脚本
│
├── quant/                          # Python 量化核心
│   ├── data/                       # 数据源、缓存、schema、loader、同步服务
│   ├── factor/                     # 因子引擎、技术因子、量价因子、基本面因子、IC
│   ├── strategy/                   # 策略引擎与内置策略
│   ├── backtest/                   # 事件驱动回测
│   ├── execution/                  # 执行层核心
│   ├── qlib_adapter/               # Qlib-compatible 数据适配层
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
- `vite.config.ts`：开发服务器端口 `8888`，将 `/api` 代理到 `http://localhost:8880`。

### 6.2 面板列表

| Tab | 组件 | 主要用途 |
|---|---|---|
| 驾驶舱 | `DashboardPanel.tsx` | AI 自主调度器、五层状态、看门狗、LLM 用量总览。 |
| 数据浏览 | `DbPanel.tsx` | 股票池、K 线、自选股、实时行情、数据同步。 |
| 股票估值 | `ValuationPanel.tsx` | 绝对、相对、市场和手动 GLM 四轨估值，展示敏感性、同行样本、市场调整和审计信息。 |
| 因子引擎 | `FactorPanel.tsx` | 因子元信息、单因子评估、全市场评估、因子选股。 |
| 策略运行 | `StrategyPanel.tsx` | 策略元信息、运行回测、全市场策略扫描、**多因子组合回测**。 |
| 交易执行 | `ExecutionPanel.tsx` | 模拟账户、订单、成交、持仓、止盈止损。 |
| 模拟盘 | `PaperPanel.tsx` | 模拟盘配置、启动/停止、手动执行、日志、日报、AI 控制台。 |
| 风控监控 | `RiskPanel.tsx` | 组合风险、系统健康、风控检查。 |
| 监控告警 | `AlertPanel.tsx` | 告警统计、规则、列表、确认、静默、处理。 |
| 金十数据 | `Jin10DataPanel.tsx` | 金十 MCP 市场快讯、新闻资讯、全品种宏观行情、财经日历。 |
| Qlib研究 | `QlibResearchPanel.tsx` | Qlib 独立研究入口，展示数据桥接、因子库、模型训练、回测、实验管理和强化学习规划。 |

### 6.3 API 调用风格

前端通常使用相对路径调用 API：

```ts
fetch(`${API_BASE}/api/paper`, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
  },
  body: JSON.stringify({ action: 'status' }),
});
```

其中：

- `VITE_API_BASE`：可覆盖 API base，默认空字符串。
- `VITE_XUANJI_API_TOKEN`：前端发送到后端的控制面 token。
- 开发模式下，`/api/*` 由 Vite 代理到 Node 后端 `8880`。

---

## 7. Node 后端架构

### 7.1 后端入口

`server/index.mjs` 负责：

- 创建 HTTP server。
- 加载 `createRouter()`。
- 默认监听 `127.0.0.1:8880`。
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
| `POST /api/jin10` | `routes/jin10.mjs` | 金十 MCP 数据聚合 API。 |
| `POST /api/qlib` | `routes/qlib.mjs` | Qlib 独立研究页只读 API，当前支持 `status`、`catalog`、`factors`。 |
| `POST /api/valuation` | `routes/valuation.mjs` | 股票估值 API；`analyze/latest` 只读，`glm_analyze` 需要控制面 token。 |

### 7.3 控制面鉴权

后端区分只读 action 与控制 action：

- 只读 action 允许直接访问。
- 控制 action 需要满足：
  1. 请求来自本机。
  2. `Content-Type` 包含 `application/json`。
  3. Origin 在允许列表内。
  4. 请求头 `X-XuanJi-Token` 或 body.token 匹配 `XUANJI_API_TOKEN`。

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
| `sync_service_manager.mjs` | 启停 `quant.data.sync_service`，以 PID + SQLite 心跳确认真实存活。 |
| `update_manager.mjs` | 后台触发 `scripts/daily_update.py`，持久化范围、进度、结果和 stderr。 |
| `watchdog.mjs` | 定期检查 paper trader、AI scheduler、数据同步 daemon 和 PersistentRunner，必要时自愈。 |
| `watchdog_worker.mjs` | 在独立 Node Worker 中运行 watchdog，避免同步跨进程检查阻塞 HTTP 主线程。 |

---

## 8. Python 量化核心架构

### 8.1 Runner 层

Runner 是 Node API 和 Python 核心之间的 action 适配层。

| Runner | 主要 action | 主要依赖 |
|---|---|---|
| `scripts/data_runner.py` | `stocks`, `klines`, `stats`, `realtime_prices`, `indices`, `watchlist_*` | `quant.data.cache`, `quant.data.loader`, `scripts.market_data` |
| `scripts/sync_runner.py` | `sync_status`, `sync_health`, `write_update_status` | 轻量 SQLite 控制面；不加载行情和 NumPy，避免队头阻塞。 |
| `scripts/factor_runner.py` | `meta`, `factors`, `evaluate`, `evaluate_all`, `market_eval`, `factor_stocks` | `quant.factor.FactorEngine`, `data/factor_evaluation.json` |
| `scripts/strategy_runner.py` | `meta`, `run`, `backtest`, `batch_evaluate`, `factor_ic_detail`, `market_scan` | `quant.strategy.StrategyEngine`, `quant.backtest.BacktestSimulator` |
| `scripts/execution_runner.py` | `all`, `status`, `positions`, `orders`, `trades`, `place_order`, `fill_order`, `cancel_order`, `check_stops`, `reset` | `execution:state`, `execution:stops` |
| `scripts/risk_runner.py` | `portfolio_risk`, `system_health`, `check`, `system_log` | `quant.risk.RiskEngine` |
| `scripts/alert_runner.py` | `list`, `rules`, `stats`, `check`, `acknowledge`, `resolve`, `silence`, `update_rule` | 告警状态与规则 |
| `scripts/paper_runner.py` | `status`, `progress`, `log`, `report`, `ai_all_status`, `ai_scheduler_status`, `llm_usage` 等 | SQLite KV 高频只读状态 |

### 8.2 数据层：`quant/data`

当前数据层不是单一免费源架构，而是“TdxQuant 优先、tdxrs 真逐笔、腾讯/新浪兜底、财务多源补全”的分层采集链路。

| 文件 | 当前角色 |
|---|---|
| `cache.py` | 默认 SQLite KV 缓存，也支持 Redis/Memory；实时状态、审计、前端查询仍落在 `data/quant.db`。 |
| `schema.py` | K 线、行情、财务和标准字段规范。 |
| `loader.py` | 从缓存加载股票池、K 线和因子输入为 DataFrame。 |
| `tdx_quant_source.py` | TdxQuant 主数据源；优先提供股票/指数实时行情、日 K、分钟 K、快照、盘口、证券基础信息和 Tick 可用性探测。 |
| `tdxrs_tick_source.py` | tdxrs 真逐笔入口；用于持仓、自选池、AI 候选股、待下单股的微观结构校验。 |
| `tick_store.py` | `market_ticks` 逐笔表；只保存新增 Tick 和采样盘口，避免 SQLite 过大。 |
| `tencent_source.py` | 腾讯兜底和交叉校验源；用于 TdxQuant 异常或口径校验。 |
| `sina_source.py` | 新浪兜底源；用于实时行情和行情链路降级。 |
| `akshare_source.py` | AKShare 财务/特色数据补全源。 |
| `baostock_source.py` | 历史兼容备用源；默认不作为批量主链路。 |
| `sync_service.py` | 实时同步 daemon；由 `server/sync_service_manager.mjs` 统一启停，并持续写入 PID、心跳、数据源分布和错误状态。 |
| `sync_status.py` | 同步 daemon 的跨 Node/Python 状态协议、代码过滤和心跳新鲜度规则。 |
| `source_health.py` | TdxQuant、新浪、腾讯、AkShare、Baostock、金十 MCP、Tushare 的真实探测与状态归一化。 |
| `health.py` | 全市场 K 线覆盖、字段、Schema、跳变和新鲜度检查。 |

数据源优先级：

| 数据类型 | 主源 | 兜底/校验 | 说明 |
|---|---|---|---|
| 实时行情 | TdxQuant | 新浪、腾讯 | 前端市场浏览、实时行情、交易前价格检查优先走 TdxQuant；显式保留 `sh/sz/bj` 前缀，避免指数/股票同码冲突。 |
| 日 K / 分钟 K | TdxQuant | 腾讯双写校验、腾讯/新浪兜底 | 重建近一年数据时以 TdxQuant 为主，异常价格跳变进入审计。 |
| 逐笔 Tick / 盘口 | tdxrs 真逐笔 | TdxQuant snapshot 明确标记兜底 | 高频 Tick 不做全市场常驻落 SQLite，只服务微观结构、风控和候选股分析。 |
| 证券基础信息 | TdxQuant | AkShare / Tushare 补全 | `get_stock_info` 用于名称、上市日期、股本、EPS 等基础信息。 |
| 财务数据 | AkShare / Tushare | TdxQuant 基础信息补充 | 完整财报仍以 AkShare/Tushare 交叉补全为主；如后续接入 TdxQuant 专业财务接口，必须保留披露日和前视偏差校验。 |
| 宏观/新闻/日历 | 金十 MCP | 本地缓存 | 作为 shadow-only 宏观情绪与风险解释信号，不直接触发订单。 |

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
>
> 财务数据来源：AkShare 东方财富财务摘要（80 项指标），按报告期 +45 天做 PIT 对齐。支持两种存储格式：
> - 平铺格式（多期历史，`fetch_core_financials` / `seed_financials`）：`[{report_date, code, roe, roa, ...}]`
> - 嵌套格式（仅最新 1 期，`rebuild_financials_bulk`）：`[{code, period, tables:{performance, income, balance, cashflow}}]`
>
> `compute_fundamental` 自动兼容两种格式，嵌套格式通过 `_flatten_bulk_tables` 换算为 11 个英文因子。
>
> 因子说明文档详见 `因子层解释说明.md`，Qlib Alpha158 因子对照详见 `Qlib因子说明.md`。

### 8.4 策略层：`quant/strategy`

当前内置 5 类策略：

| 策略名 | 中文名 | 说明 |
|---|---|---|
| `factor_rank` | 单因子排名 | 多股截面按因子 Z-Score 排序；单股模式按阈值交易。 |
| `multi_factor` | 多因子加权 | 多个因子 Z-Score 加权求和，生成交易信号。支持自定义因子组合与权重。 |
| `ma_cross` | 均线交叉 | 短期均线上穿长期均线买入，下穿卖出。 |
| `bb_reversion` | 布林带回归 | 价格触及下轨买入，触及上轨卖出。 |
| `topk_dropout` | Top-K Dropout | 动态淘汰排名靠后的持仓，补充新信号。 |

策略输出 signals 后进入 `quant.backtest.BacktestSimulator` 做事件驱动回测。

> **多因子组合回测**：在策略引擎面板 → "多因子组合" Tab 中，可选择多个有效因子并设定权重，
> 组合成综合打分对全市场股票排名后回测。默认组合：net_margin(0.3) + volatility_20(0.25) + turnover_5(0.2) + roa(0.15) + ret_60(0.1)。

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
- 实时行情代码归一化：`sh600519`、`sz000001` 等响应统一映射回六位股票代码，避免实时价存在但执行层错误回退到日 K 收盘价。
- 成交量参与约束：默认单笔最多使用当日已观察成交量的 1%；超过上限时部分成交，缺少成交量时不虚构流动性。
- 数量驱动的市场冲击：在基础滑点之外，按成交量参与率平方根增加冲击成本，达到参与上限时默认增加 15 bps。
- 进程间写锁：Web Runner、模拟盘和止损扫描对 `execution:state` 的修改由 `quant/execution/state_lock.py` 串行化。
- 决策级幂等：订单携带稳定 `client_order_id`；已受理或已成交的相同意图直接返回原订单，临时失败允许后续重试。
- 启动迁移：自动合并历史上由执行订单和 paper 摘要形成的重复订单记录，不重置现金、持仓或成交。
- 原子审计：SQLite 模式下，关键账户状态与订单/成交审计行在同一事务提交；任一写入失败则整体回滚。

核心状态 key：

```text
execution:state
execution:stops
```

### 8.7 风控层：`quant/risk`

风控层负责：

- `quant/risk/gateway.py` 是订单路径上的同步阻塞式事前风控网关；`paper_trader.py` 必须通过 `scripts/paper/pretrade_risk.py -> check_order()` 才能进入 `order_router.py`。
- `quant/risk/hard_limits.json` 是硬风控上限来源；`paper:config.risk`、`ai:autonomous:config.risk` 和显式参数只能收紧，不能放宽硬限制。
- 风险增加订单受全部硬门槛约束；合法的风险降低卖单可越过 kill switch、日亏、最大回撤、日换手、资金上限和单轮订单数等“阻止退出”的账户级门槛，但仍必须遵守数量合法性、停牌、跌停、持仓数量和 T+1 可卖量。
- 日亏熔断以 `day_start_equity` 为基准，最大回撤以 `peak_equity` 为基准；状态接口同步返回 `daily_pnl` 与 `drawdown_pct`。
- 组合风险计算、持仓集中度、波动率与 VaR 类指标。
- 系统健康检查、系统日志/异常状态。
- 订单级审计：每个拒单/放行结果写入 `risk_events`，用于回放当时的意图、组合、市场和规则原因。

---

## 9. AI 研究与门禁系统架构

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

### 9.2 AI 模型工作职责、设权与硬边界

本系统采用成熟量化机构常见的“分权制衡”原则：AI 模型负责提高 alpha、研究效率和执行效率；资金安全、熔断、合规与最终风险约束由确定性规则、人类 PM/风控委员会和审计系统承担。AI 可以在风控边界内自由生成信号和建议，但不能成为自己的裁判，也不能覆盖硬规则。

#### AI 可以承担的职责

| 层级 | AI 职责 | 项目内对应模块 |
|---|---|---|
| 信号生成层 Alpha | 特征工程、非线性关系挖掘、多因子组合优化、市场状态识别、新闻/情绪/订单流等另类数据辅助分析。 | `ai_factor_agent.py`, `ai_strategy_agent.py`, `ai_stock_screener.py`, `global_context.py`, `jin10_runner.py` |
| 执行优化层 | 给出 TWAP/VWAP/IS 等执行参数建议、滑点预测、订单拆分建议、模拟盘报价/成交质量复盘。 | `ai_execution_agent.py`, `ai_portfolio_planner.py`, `paper_trader.py` |
| 风险监测辅助 | 异常检测、尾部风险和流动性枯竭预警、组合相关性变化提示、压力测试场景生成。 | `ai_risk_agent.py`, `risk_runner.py`, `quant/risk/gateway.py` |
| 研究与复盘 | 盘后/非交易日因子稳定性评估、策略回测、候选池维护、日志审计、失败原因归因和自我改进提案。 | `ai_loop.py`, `ai_self_improver.py`, `ai_memory.py`, `daily_report.py` |

#### 必须设置的硬边界

| 边界 | 不可交给 AI 的最终权限 | 项目要求 |
|---|---|---|
| 资金分配最终决策 | 仓位规模、杠杆倍数、单笔最大风险敞口、组合总风险预算。 | 由 `quant/risk/gateway.py`、`quant/risk/hard_limits.json`、人类 PM/风控委员会规则最终裁决；AI 只能提交意图和建议。 |
| Kill Switch | 熔断、暂停交易、异常交易拦截、日内亏损停止。 | 必须由确定性 if-then 规则触发；AI 不允许自行决定是否关闭或绕过熔断。`paper:config.risk` 只能收紧，不能放宽文件级硬限制。 |
| 模型风险管理 | 判断模型是否可信、是否降级、是否晋升生产候选。 | 使用 shadow model、硬指标晋升状态机、置信度阈值和简单规则降级；模型不能批准自己上线。`ai_verifier.py` 为规则化验证器，不调用 LLM。 |
| 合规与审计 | 最优执行证明、内幕交易审查、监管解释、审计留痕完整性。 | AI 可生成解释草稿，但最终依据必须来自结构化日志、订单链路、风控事件和人工可解释规则。 |
| 代码和配置变更 | 自动修改生产代码、启用新策略、修改实盘配置。 | `self_improve_propose` 只生成提案；任何生产变更必须经过测试、审核和人工确认。 |
| 实盘交易接入 | 自动连接券商并实盘下单。 | 默认禁止；实盘前只允许 read-only sync、shadow live signal、manual approve order。 |

#### 分层授权示意

```text
人类 PM / 风控委员会
  └─ 设定风险预算、资金上限、策略上限、模型晋升标准
规则化风控系统
  └─ 强制熔断、仓位硬约束、单日亏损限制、订单网关
AI 模型层
  └─ 信号生成、市场识别、组合建议、执行优化、复盘解释
执行系统
  └─ 只执行通过 verifier + risk gateway + 白名单工具的受控订单
```

#### 代码中已经强制的硬边界

| 边界 | 强制位置 | 说明 |
|---|---|---|
| 订单唯一硬门禁 | `scripts/paper/pretrade_risk.py -> quant/risk/gateway.py` | 模拟盘订单在进入 `order_router.py` 前同步调用 `check_order()`；拒绝结果写入 `risk_events`。 |
| 硬风控上限 | `quant/risk/hard_limits.json`, `quant/risk/config.py` | `paper:config.risk`、`ai:autonomous:config.risk`、显式参数只能收紧，不能放宽单票仓位、总暴露、日换手、亏损熔断、涨跌停/ST 等限制。 |
| verifier 独立性 | `scripts/ai_verifier.py` | 规则化检查器，不调用 LLM；校验决策协议、数据新鲜度、目标组合权重、工具白名单和风控状态。 |
| LLM 个股复核权限 | `scripts/paper_trader.py` | LLM 只作为 `confidence_only` 软信号重排既有量化候选；不能新增、删除、替代候选池，不能绕过风控。 |
| 高风险工具执行 | `scripts/ai_action_executor.py` | `paper_trade_once/paper_rebalance_once` 必须同时满足交易日、交易时段、决策正常、verifier 通过、risk 通过和白名单限制。 |

#### 因子/策略晋升硬指标

晋升状态由 `quant/ai/promotion.py` 的确定性状态机维护：

```text
candidate -> shadow -> paper_active -> production_candidate -> approved -> retired
```

| 对象 | shadow / paper_active | production_candidate | approved |
|---|---|---|---|
| 因子 | 单次通过进入 shadow；连续 3 次 level>=1 进入 paper_active。level>=1 要求 `passed=true` 且 `best_abs_ic>=0.03`、`best_ir>=0.3`。 | 连续 5 次 level>=3；level>=3 要求 `best_abs_ic>=0.06`、`best_ir>=0.6`、`n_records>=200`。 | 不由 LLM 自动批准；需要人工或独立审核流程。 |
| 策略 | 连续 3 次 level>=1 进入 paper_active。level>=1 要求样本外 `val_sharpe>0` 且优于基线。 | 连续 5 次 level>=3；level>=3 要求 `val_sharpe>=0.8`、总收益为正、最大回撤<=12%、paper trading 至少 20 个交易日、paper 超额收益>=0、paper 回撤<=12%。 | 不由 LLM 自动批准；必须基于 paper trading 结果和人工确认。 |

连续 3 次失败会把 `paper_active` / `production_candidate` 降为 `retired`。这套阈值是模拟盘研究默认值，未来接实盘前应由独立风控/PM 审核后固化。

#### 当前项目与机构级生产系统的差距

- 当前人工审核默认依赖单一操作者，不等同于机构级 four-eyes principle。
- 当前硬限制文件在同一项目目录内，已经避免 AI 通过 KV 放宽限制；若进入团队/实盘环境，应迁移到权限隔离的配置仓库或只读配置服务。
- SQLite 适合实时状态、审计和小窗 Tick；大规模 Tick 历史、全市场分钟矩阵、训练样本应迁到 ClickHouse / Parquet / 离线 GPU worker。
- 金十 MCP、新闻情绪、宏观日历均为 shadow-only 或解释信号，不应直接触发订单。

#### 交易日与非交易日职责边界

| 时段 | AI 应参与的工作 | AI 禁止动作 |
|---|---|---|
| 交易日盘中 | 数据新鲜度检查、L2/L3 因子和策略扫描、全市场 AI 筛选、组合建议、风控验证、受控模拟盘意图。 | 绕过风控、越过 verifier、直接修改资金上限、关闭 kill switch。 |
| 交易日盘后 | 数据更新、因子评估、策略复盘、执行复盘、明日候选池和组合计划。 | 盘后自动实盘下单、用盘后复盘结果覆盖硬风控。 |
| 非交易日 | 研究型工作：数据巡检、因子稳定性评估、策略回测、候选池维护、日志审计、自我改进提案。 | 触发交易执行、提交真实订单、绕过非交易日交易日历。 |

关键判断原则：犯错成本可逆的任务，例如错过一点收益、候选池排序偏差、执行参数建议，可以交给 AI；犯错成本不可逆的任务，例如爆仓、监管处罚、系统性风险、资金权限和熔断控制，必须交给确定性规则和人工治理。

### 9.3 工具白名单

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

### 9.4 L0 + L1-L5 架构

| 层 | 模块 | 职责 |
|---|---|---|
| L0 总控 | `ai_loop.py`, `ai_operator.py` | 编排五层、汇总决策、写 `ai:decision:latest`。 |
| L1 数据层 | `ai_data_agent.py` | 数据完整性、新鲜度、自动补数。 |
| L2 因子工厂 | `ai_factor_agent.py` | 生成候选因子、验证 IC/IR、Shadow → Approved。 |
| L3 策略工厂 | `ai_strategy_agent.py` | 生成策略配置、自动回测、与基线对比。 |
| L4 执行层 | `ai_execution_agent.py` | 执行建议、订单质量分析、执行复盘。 |
| L5 风控层 | `ai_risk_agent.py` | 风险监测辅助、自我验证和风险解释；最终硬风控仍由规则化 risk gateway 裁决。 |

### 9.5 受控调度器

`scripts/ai_scheduler.py` 是 AI 系统的主心跳。

运行模式：

| 模式 | 时间 | 行为 |
|---|---|---|
| `intraday` | 交易日 09:30-15:00 | 盘中自适应研究与交易循环：数据检查、L2/L3 因子和策略扫描、全市场 AI 筛选、组合建议、风控验证；只有通过 verifier/risk gateway 时才允许受控模拟盘意图。 |
| `postclose` | 交易日 15:00-23:59 | 重巡检：数据更新、因子评估、策略/执行复盘、AI 闭环、明日候选池和组合计划；必要时仅触发受控模拟盘复盘或计划生成。 |
| `idle` / `research_idle` | 夜间/非交易日 | 研究维护：全球动态、数据新鲜度、因子稳定性、策略回测、日志审计、自我改进提案；禁止触发交易执行。 |

常用入口：

```bash
python scripts/ai_scheduler.py --daemon
python scripts/ai_scheduler.py --once
python scripts/ai_scheduler.py --status
```

### 9.6 AI 闭环

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
12. 在交易时段、交易日历、verifier、risk gateway 和白名单工具全部允许时，才可触发 `paper_trade_once`；非交易日只允许研究和复盘，不触发交易执行。

### 9.7 模拟盘执行器

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
- 交易日 + 决策 ID + 股票 + 方向 + 数量组成稳定幂等键；只有订单成功受理后才标记完成，行情超时等临时失败不会永久阻止重试。

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
| 数据同步控制 | `data:sync:config`, `data:sync:daemon_status` | 实时同步开关、代码范围、PID、心跳、监控数量、来源分布和最近错误。 |
| 手动数据更新 | `data:update:status` | K线/财务更新的持久化进度、PID、范围、结果和 stderr 尾部。 |
| 数据健康 | `data:health:last`, `data:source_health` | 全市场覆盖检查和各数据源探测结果；默认缓存 5 分钟。 |

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
health
progress
update_progress
daemon_status
start_update
stop_update
start
stop
```

`start` / `stop` 直接控制由 `server/sync_service_manager.mjs` 管理的
`python -m quant.data.sync_service` 进程，不再写入无人消费的触发 key。
`daemon_status` 只依据真实 PID 和 `data:sync:daemon_status` 心跳判断状态，
不会再把共享的 `stock:realtime:*` 缓存误判为 daemon 在线。

`start_update` 支持可选 `codes` 数组：

```json
{
  "action": "start_update",
  "mode": "kline",
  "codes": ["600519", "000001"],
  "workers": 8
}
```

留空 `codes` 时才执行全市场增量更新。任务状态持久化在
`data:update:status`，后端重启后可识别失联任务，不再依赖 Node 内存。

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

`start_all.bat` 通过 `scripts/start_services.mjs` 启动前后端。服务进程与启动窗口解耦，
关闭启动窗口不会结束后端；重复执行时会检测 `8888/8880` 端口，避免重复启动。
启动 PID 和输出分别记录到：

- `logs/backend.pid`
- `logs/frontend.pid`（仅由启动器新拉起前端时生成）
- `logs/backend-launcher-out.log`
- `logs/backend-launcher-err.log`
- `logs/frontend-launcher-out.log`
- `logs/frontend-launcher-err.log`

仅在性能排查或前台调试时直接启动：

```powershell
# 后端 API
node server\index.mjs

# 前端 Vite，固定 8888，不允许自动换端口
node node_modules\vite\bin\vite.js --host 127.0.0.1 --port 8888 --strictPort
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
# 推荐：在“数据浏览 → 数据管理”中启动，由后端 manager 和 watchdog 管理

# 仅用于调试的直接启动方式
python -m quant.data.sync_service
python -m quant.data.sync_service --codes 600519,000001
```

数据管理页面显示真实 PID、心跳年龄、监控股票数、数据源分布、SQLite
容量、全市场 K 线覆盖、源健康和结构化更新进度。`data:sync:config.enabled`
开启时，Watchdog 会在 daemon 意外退出或心跳失效后尝试恢复；人工停止会
将其设为 `false`，不会被自动拉起。

页面每 3 秒读取一次统一控制面状态。`/api/sync` 的状态与健康查询使用
轻量 `PersistentRunner('sync_runner.py')`，不会在每次轮询时重新启动 Python，
也不会被 `data_runner.py` 中较慢的实时行情请求排队阻塞。健康检查默认缓存
5 分钟，只有人工点击“刷新健康状态”时才强制重新扫描全市场并探测数据源。

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

# Web/API 全功能验证，需要前后端已运行
node scripts\web_verify.mjs

# 数据浏览合同测试
node scripts\data_browse_contract_tests.mjs

# 启动性能相关合同测试
node scripts\performance_priority_contract_tests.mjs
node scripts\persistent_runner_idle_contract_tests.mjs
```

---

## 13. 配置项与环境变量

### 13.1 Node/前端配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `PORT` | Node 后端端口 | `8880` |
| `HOST` | Node 后端监听地址 | `127.0.0.1` |
| `XUANJI_API_TOKEN` | 控制面请求 token | 空，需要自行配置 |
| `ALLOWED_ORIGINS` | 允许跨域来源 | `http://localhost:8888,http://127.0.0.1:8888` |
| `VITE_API_BASE` | 前端 API base | 空字符串 |
| `VITE_XUANJI_API_TOKEN` | 前端发送的 API token | 空字符串 |

### 13.2 Python/数据配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `QUANT_CACHE` | 缓存后端，可选 `sqlite` / `redis` / `memory` | `sqlite` |
| `PYTHONPATH` | Python 模块查找路径 | 建议设为项目根目录，或在项目根目录运行脚本 |
| `PYTHONIOENCODING` | Python 输出编码，避免 Windows 控制台乱码影响 JSON 通讯 | `utf-8` |
| `PYTHONUNBUFFERED` | Python runner 非缓冲输出，降低长驻进程通讯延迟 | `1` |
| `OMP_NUM_THREADS` | OpenMP/NumPy 线程上限，防止多个 runner 叠加占用内存和线程 | `1` |
| `OPENBLAS_NUM_THREADS` | OpenBLAS 线程上限 | `1` |
| `MKL_NUM_THREADS` | MKL 线程上限 | `1` |
| `NUMEXPR_NUM_THREADS` | NumExpr 线程上限 | `1` |

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
GLM_API_KEY=
GLM_BASE_URL=http://192.168.8.49:3003/v1
GLM_MODEL=glm-5.2
XUANJI_TDX_QUANT_FIRST=1
JIN10_MCP_SERVER_URL=https://mcp.jin10.com/mcp
JIN10_MCP_PROTOCOL_VERSION=2025-11-25
JIN10_MCP_BEARER_TOKEN=
XUANJI_API_TOKEN=
VITE_XUANJI_API_TOKEN=
```

实际 `.env` 不应提交到仓库；新环境请从 `.env.example` 复制并填入本机密钥。

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

#### 端口 8888/8880 被占用

关闭已有 Node/Vite 进程，或修改 `vite.config.ts` / `server/config.mjs` 对应端口。
正常重复启动请直接再次执行 `start_all.bat`，启动器会复用已经监听的服务。

#### 前端可以打开，但全部 API 功能异常

先检查 `8880` 是否监听，再查看 `logs/backend-launcher-err.log` 和当日
`logs/server-YYYYMMDD.log`。后端现在会记录监听错误、未捕获异常、未处理 Promise
拒绝及正常关闭信号，便于区分代码崩溃和外部终止。

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
3. 是否配置 `XUANJI_API_TOKEN`。
4. 前端是否设置 `VITE_XUANJI_API_TOKEN`。
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

- `quant/data/tdx_quant_source.py`
- `quant/data/tdxrs_tick_source.py`
- `quant/data/tencent_source.py`
- `quant/data/sina_source.py`
- `quant/data/akshare_source.py`
- `quant/data/baostock_source.py`

建议要求：

- 返回字段符合 `quant/data/schema.py`。
- 明确主源、兜底源、交叉校验规则和异常裁决规则。
- 失败时可重试且不污染已有缓存。
- 写入 key 命名与现有 K 线/财务数据保持一致。

---

## 16. 风险提示

- 本项目仅用于量化研究、教学和模拟盘验证。
- 系统不连接真实券商，不应直接用于实盘交易。
- TdxQuant、tdxrs、腾讯、新浪、AkShare/Tushare 等多源口径可能不一致，数据可能延迟、缺失或被限流；交易前必须以数据健康检查和风控网关为准。
- 回测结果不代表未来收益，模拟盘结果不代表实盘表现。
- 基本面因子如未按财报实际发布日期处理，可能存在前视偏差。
- 如需实盘交易，必须接入合规券商接口，并重新设计认证、权限、风控、审计和灾备流程。

---

## 17. 数据层重建基线

更新时间：2026-07-09。

本节记录当前数据层的稳定基线、重建命令和验证口径。该基线只用于研究、回测、模拟盘和 AI 辅助决策，不改变实盘安全边界。

### 17.1 当前覆盖率

| 数据项 | 当前口径 | 覆盖结果 |
|---|---|---|
| 股票池 | `stock:universe` | 5203 只，已过滤 `920xxx` |
| 股票名称 | `stock:name:<code>` | 5203/5203，只保留纯 6 位代码键 |
| 日 K | `kline:<code>:d` | 5203/5203，每只约 300 根，样本最新交易日 `20260708` |
| 全市场摘要 | `stock_daily_summary` | 由最新日 K 写入，供市场浏览 Top N 排名使用 |
| 财务快照 | `fin:abstract:<code>` / `fin:crosscheck:<code>` | 5201/5203，基于 `20260331` 批量财报表 |
| 财务缺口 | - | `002731`、`688121` 暂未出现在该报告期批量财报表中 |

### 17.2 数据源策略

| 数据类型 | 主链路 | 兜底/说明 |
|---|---|---|
| 实时行情 | TdxQuant 优先 | A股股票和 A股指数均优先走 TdxQuant；新浪、腾讯兜底；名称缓存统一写入 `stock:name:<6位代码>` |
| 日 K | TdxQuant 主取 | 腾讯交叉校验，新浪兜底；Baostock 默认关闭，避免批量重建卡死 |
| 分钟 K | TdxQuant 优先 | 腾讯兜底 |
| 财务数据 | AkShare 东方财富批量财报表 | 单股 AkShare 接口只适合作为慢速增强；Tushare 为可选交叉源，需 Token 权限 |
| 宏观/新闻/日历 | 金十 MCP | 只作为宏观行情、资讯、财经日历输入，不替代 A 股行情主链路 |
| 顶栏/全球动态 A股指数 | TdxQuant 优先 | `sh000001`、`sz399001`、`sz399006`、`sh000300`、`sh000905`、`sh000688` 优先走 TdxQuant；海外指数、商品、汇率继续由 Sina/Jin10 按品种兜底。 |

#### 17.2.1 金十数据页面容量与刷新策略

- 市场快讯和新闻资讯首次加载、手动全量刷新时最多按 `cursor` 连续读取 10 页，前端去重后保留最近 200 条。
- 后台自动刷新每 90 秒只读取最新一页，与现有列表去重合并，不重复执行 10 页深度扫描。
- 财经日历每 90 秒刷新一次，前端保留最近 200 条；若上游返回超过 200 条，不继续扩大浏览器常驻数据。
- 宏观行情通过 `quote://codes` 动态发现全部支持品种，不再写死 4 个代码；报价按每批 20 个代码读取。
- `XAUUSD`、`USOIL`、`USDCNH`、`USDJPY` 四个核心品种每 10 分钟刷新；全部支持品种每 4 小时刷新；手动“全量刷新”可立即更新全部品种。
- 失败刷新不会清空旧数据；部分品种报价失败时保留品种卡片，并在页面显示失败代码。
- 2026-07-13 实测：`quote://codes` 返回 97 个品种，页面显示 97/97；市场快讯显示 200 条；财经日历从上游 224 条中显示最近 200 条；新闻资讯上游当时仅返回 29 条，页面按实际可用数量完整显示，不填充虚假记录。
- 金十数据仍只用于宏观、资讯、日历和解释型 shadow signal，不替代 TdxQuant A 股主行情，也不能直接触发交易。

### 17.3 存储规划

当前默认仍使用 `data/quant.db`：

- SQLite KV：保留实时状态、审计、AI 决策、调度状态、模拟盘状态和轻量缓存。
- `stock_daily_summary`：保留最新全市场摘要，支撑市场浏览成交额/成交量 Top N。
- 历史大表：后续迁移到 ClickHouse，适合承载多年日 K、分钟 K、tick、全市场回测和大规模因子截面。

### 17.4 全市场重建命令

```bash
# 重建股票池、清理无效键，并全量刷新近一年日 K
python scripts/rebuild_market_data.py --phase kline --fresh --workers 16 --count 300

# 只补缺失日 K，不覆盖已有数据
python scripts/rebuild_market_data.py --phase kline --workers 8 --count 300

# 批量补全财务快照，报告期可按最新披露期调整
python scripts/rebuild_market_data.py --phase financial --fresh --financial-period 20260331 --workers 8

# K 线和财务都执行；大批量运行前建议确认 TdxQuant 可用
python scripts/rebuild_market_data.py --phase both --fresh --workers 12 --count 300
```

说明：

- 脚本会自动恢复 `stock:universe`，重建 `stock:name:<code>`，并清理 `920xxx`、空 K 线、旧格式名称键。
- 对复权/除权导致的价格跳变，严格校验仍会记录警告；重建脚本会以 `tdx_quant_jump_review` 来源保存逐 bar 合法的数据，便于后续审计。
- 如确需启用 Baostock 兜底，可临时设置 `XUANJI_BAOSTOCK_FALLBACK=1`；批量重建默认不建议启用。

### 17.5 市场浏览 TopN / Top100 规则

数据浏览 > 市场浏览 的成交额/成交量榜单使用以下口径：

1. 正常链路优先走实时行情：`scripts/data_runner.py?action=stocks&sort_by=amount` 会全市场调用 `scripts.market_data.fetch_realtime()`。
2. `fetch_realtime()` 的主源是 TdxQuant；价格、涨跌幅、成交量、快照状态优先来自 TdxQuant。
3. TdxQuant 的成交量单位为“手”，后端统一换算为“股”后返回给前端；同时保留 `raw_volume` 和 `raw_volume_unit` 便于审计。
4. 如果 TdxQuant 的成交额为空或不可用，后端会用腾讯成交额补齐，此时单行会显示 `source=tdx_quant`、`amount_source=tencent`。这表示行情主源仍是 TdxQuant，成交额字段来自腾讯兜底。
5. 实时源短时不可用时，才回退到 `stock_daily_summary` 按最新交易日全市场排序，并合并可用的实时价格、涨跌幅和名称。
6. 不再从当前少量 K 线代码、自选股或实时接口的 0 成交额结果驱动 TopN。
7. 前端当前默认请求 `limit=100`，因此页面显示为 Top100；接口仍支持 `limit=30/50/100` 等不同榜单规模。
8. Top100 行支持右键操作菜单：`AI 委员会分析（华尔街13位）`、`K线走势`、`加入自选股`。菜单渲染在 `DbPanel` 公共层，不放在 `DataManagePanel` 或 `RealtimePanel` 子组件中，避免跨组件状态引用导致白屏。

接口示例：

```bash
curl -X POST http://127.0.0.1:8880/api/data \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"stocks\",\"limit\":100,\"sort_by\":\"amount\"}"
```

期望返回：

- `data.source = "realtime"`；实时源不可用时才回退到 `daily_summary+realtime`
- `data.latest_date` 为最新交易日
- 非交易日不得使用本机日期冒充交易日；例如 2026-07-11 周六应显示 `20260710`
- `data.stocks[0].amount > 0`
- `data.stocks` 按 `amount` 降序

### 17.6 验证命令

```bash
# Python 单元测试
python -m pytest tests -q

# 数据重建契约
node scripts/data_rebuild_contract_tests.mjs

# 成交额 Top N 新鲜度和排序契约
node scripts/top_amount_freshness_tests.mjs

# 前端构建
npm run build

# Web 全功能验证，需要 8888/8880 已启动
node scripts/web_verify.mjs
```

最近一次验证结果：

- `python -m pytest tests -q`：53 passed。
- `node scripts/data_rebuild_contract_tests.mjs`：passed。
- `node scripts/top_amount_freshness_tests.mjs`：passed。
- `npm run build`：passed。
- `node scripts/web_verify.mjs`：24 passed / 0 failed。

### 17.7 运维注意事项

- 修改 `scripts/data_runner.py`、`scripts/market_data.py` 等 Python runner 后，需要重启 Node 后端和常驻 Python 子进程。
- 数据重建不触发交易；模拟盘交易仍必须经过 verifier、risk gateway 和当前交易策略检查。
- 财务数据用于因子和研究时，必须注意财报发布日期，避免前视偏差。
- SQLite 适合实时状态和审计；多年历史、分钟级矩阵和全市场回测应迁移到 ClickHouse 或离线 worker。

---

## 18. Qlib 本机训练

更新时间：2026-07-12。

Qlib 已从只读能力展示升级为可实际运行的独立离线研究系统：

- 复用本机 Python 3.11.9，在仓库内建立 `.venv-qlib`，已安装 pyqlib 0.9.7 和 LightGBM 4.6.0。
- 项目内隔离的数据和模型仓库位于 `data/qlib`，由 Git 忽略，且不读取或写入交易库 `data/quant.db`。
- 已实现 TdxQuant 全 A 股票池、未复权日线采集、断点续跑、Qlib bin 导出、Alpha158、LightGBM、实验/模型注册和任务审计。
- 已实现六年研究数据双轨采集：TdxQuant 原始/前复权日线为主，AkShare 和 Baostock 负责补齐 TdxQuant 约 1200 根日线窗口之前的历史及退市股票；920xxx 不进入股票池。
- 已实现上市/退市/更名/ST 点时状态文件、原始/前复权分轨文件、复权因子裁决和固定质量门禁。六年导出与训练在 `quality_report.json` 未通过时会被同步阻止。
- 已实现固定 Walk-Forward：36 个月训练、6 个月验证、6 个月测试、每 3 个月滚动；聚合结果只能是 `candidate` 或 `rejected`。
- 已完成官方中国市场样例的真实训练、模型重载和评估，验证实验为 `qlib_official_demo_7ec16af1f1ec`。
- 近一年全 A 数据任务 `qlib_cec22f06ffbf40c2` 已完成：请求 5205 只、有效 5203 只、1298195 行、最新日期 2026-07-10、覆盖率 99.96%。
- Qlib bin 导出任务 `qlib_1db97b08a68d4ae1` 已完成：252 个交易日、5203 个标的、41624 个特征文件。
- 正式研究基线 `qlib_one_year_49dab0026126` 已完成训练；因样本外 Rank IC、ICIR、Sharpe 均为负，被硬门槛标记为 `rejected`，未进入交易链路。
- 左侧 `Qlib研究` 提供研究总览、数据准备、模型训练、实验记录、模型仓库、回测评估和任务日志七个中文页面。
- Windows 计划任务 `\XuanJiQuant-Qlib-Weekly` 每周六 18:30 执行增量采集、导出和重训。
- 调度器已支持自适应周期：普通周六运行一年基线，月初首个周六刷新六年点时数据，1/4/7/10 月首个周六在质量通过后运行 Walk-Forward。
- 模型最多只能由人工从 `candidate` 提升到 `shadow`，不能直接驱动模拟盘或实盘订单。

六年流水线当前状态（2026-07-12）：

- 代码、控制动作、中文页面和质量门禁已实现。
- 真实双轨样本验证通过：`600000`、`000001`、`300750` 的原始/前复权记录一致，复权校验异常为 0。
- AkShare 点时元数据实测返回当前股票 5203 只、更名记录 7439 条、退市记录 364 条。
- 窗口内退市股 `000005` 可由 AkShare 历史接口返回 892 条日线；该外部接口存在瞬时代理/连接失败，完整任务必须依赖断点续跑和后续补跑。
- 全量任务 `qlib_41c268e894ba4515` 于 2026-07-12 16:41 启动；因 AkShare/Eastmoney 远端断开且 Baostock 登录失败，首批数据未产生，已于 16:45 安全取消，避免无效长期占用。当前状态仍是“代码就绪、外部早期历史源待恢复后重跑”。
- 完整六年全 A 采集、质量通过、Qlib bin 导出和 Walk-Forward 正式训练均未完成，必须按实际任务状态记录，不能提前标记完成。

完整运行说明、命令、模型指标和后续工作见
[`docs/QLIB_LOCAL_TRAINING.md`](docs/QLIB_LOCAL_TRAINING.md)。

<details>
<summary>展开 2026-07-11 只读适配器历史记录（已废弃，不代表当前状态）</summary>

### 18.1 历史完成情况

| 项目 | 状态 | 说明 |
|---|---|---|
| 左侧入口 | 已完成 | `App.tsx` 在“金十数据”下方新增 `Qlib研究` 独立入口。 |
| 前端页面 | 已完成 | `components/QlibResearchPanel.tsx` 已展示 Qlib 数据层、因子库、模型训练、回测执行、实验管理、强化学习和本项目接入状态。 |
| 后端路由 | 已完成 | `server/routes/qlib.mjs` + `server/router.mjs` 暴露只读 `/api/qlib`。 |
| Runner | 已完成 | `scripts/qlib_runner.py` 支持 `status`、`catalog`、`factors`。 |
| 本地适配器 | 已完成 | `quant/qlib_adapter.to_qlib_panel` 可把本地 K 线转换为 Qlib-like 长表字段：`datetime`、`instrument`、`$open`、`$high`、`$low`、`$close`、`$volume`、`$amount`。 |
| 前端独立验证 | 已完成 | Web 插件访问 `http://127.0.0.1:8888/`，点击 `Qlib研究` 后右侧页面正常展示，控制台无 error/warn。 |
| API 验证 | 已完成 | `/api/qlib?action=status` 和 `/api/qlib?action=factors` 均返回成功。 |
| 构建验证 | 已完成 | `npm run build` 通过。 |

### 18.2 当前未完成 / 待处理

| 项目 | 当前状态 | 下一步 |
|---|---|---|
| pyqlib 安装 | 未安装 | 安装到项目 Python 虚拟环境 `.venv`，确保启动后端的同一 Python 能 `import qlib`。 |
| 依赖声明 | 待补充 | 在 `requirements.txt` 中增加可复现的 Qlib 依赖版本；Windows 下需验证 pyqlib、LightGBM、PyTorch 等依赖兼容性。 |
| Qlib 数据目录 | 待创建 | 推荐使用 `data/qlib/` 存放 Qlib bin、Parquet、calendar、instruments、features、labels。 |
| TdxQuant 导出器 | 待开发 | 新增 `scripts/qlib_exporter.py`，把 TdxQuant 日 K/分钟 K 导出为 Qlib 训练格式。 |
| Alpha158 / Alpha360 | 未真实执行 | 当前页面仅展示能力目录；真实 Alpha158/Alpha360 需在 pyqlib 安装和数据导出后启用。 |
| DatasetH / DataHandler | 待接入 | 需要定义 train/valid/test 切分、标签、缺失值、标准化和前视偏差检查。 |
| 模型训练 | 待接入 | LightGBM、LSTM、Transformer 等训练应放到离线 worker，不进入盘中主进程。 |
| 实验管理 | 待接入 | 需要接入 Qlib Recorder/Experiment 或本项目等价实验记录表。 |
| 回测融合 | 待接入 | Qlib TopKDropout/Portfolio Strategy 结果需统一进入本项目手续费、滑点、涨跌停、T+1 和 paper 晋升规则。 |
| GPU worker | 待规划 | 深度学习训练、超参搜索、大规模因子挖掘可进入离线 GPU worker；盘中交易进程不直接承载训练。 |

### 18.3 需要明确的事项

| 事项 | 需要确认 |
|---|---|
| Qlib 安装方式 | 使用 `.venv` 安装，还是单独创建 `qlib-env`。推荐 `.venv`，便于 `/api/qlib status` 直接识别。 |
| 训练数据范围 | 先使用近一年 A 股全市场日 K，还是扩展到 3-6 年历史、分钟线和财务因子。 |
| 存储方案 | 小规模验证可用 `data/qlib/` + Parquet；多年历史、分钟级矩阵和全市场回测建议迁移 ClickHouse/Parquet。 |
| Qlib 输出权限 | 推荐仅输出 `shadow_signal`、候选因子、候选模型和离线报告；不直接提交订单。 |
| 晋升门槛 | Qlib 模型进入模拟盘前，必须明确 IC/IR、分组收益、多空收益、回撤、样本外周期、paper trading 周期等硬指标。 |
| 资源预算 | LSTM/Transformer/RL/超参搜索是否启用 RTX 3090，需要根据数据规模和训练频率确认。 |

### 18.4 推荐目录规划

```text
XuanJiQuant/
├── .venv/                         # pyqlib 安装到项目 Python 环境
├── data/
│   └── qlib/                      # Qlib bin / Parquet / calendar / instruments / features / labels
├── quant/
│   └── qlib_adapter/              # 本项目数据到 Qlib 格式的适配层
└── scripts/
    ├── qlib_runner.py             # 当前已完成，只读状态/目录/样例输出
    ├── qlib_exporter.py           # 待新增，TdxQuant -> Qlib 数据导出
    ├── qlib_train.py              # 待新增，离线训练入口
    └── qlib_backtest.py           # 待新增，离线回测入口
```

### 18.5 验证命令

```bash
# Qlib 前端/路由/组件合约
node scripts/qlib_panel_contract_tests.mjs

# 前端构建
npm run build

# API 状态检查
curl -X POST http://127.0.0.1:8880/api/qlib \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"status\"}"

# Qlib-like 本地样例数据
curl -X POST http://127.0.0.1:8880/api/qlib \
  -H "Content-Type: application/json" \
  -d "{\"action\":\"factors\",\"code\":\"000001.SZ\"}"

# 全局接口冒烟
node scripts/hourly_loop_test.mjs
```

最近一次验证结果：

- `node scripts/qlib_panel_contract_tests.mjs`：passed。
- `/api/qlib` `status`：success，当前 `pyqlib_installed=false`、`integration_mode=local_adapter_only`。
- `/api/qlib` `factors`：success，可返回本地 Qlib-like 字段样例。
- `npm run build`：passed。
- Web 插件验证：左侧 `Qlib研究` 位于 `金十数据` 下方，右侧 Qlib 页面可见，核心模块和 TdxQuant 数据桥接信息可见，控制台无 error/warn。
- `node scripts/hourly_loop_test.mjs`：Qlib 两项通过；整体 `25/27`，失败项为既有控制面写操作 `exec.update_price`、`alerts.check` 鉴权 403，与 Qlib 独立验证无关。

### 18.6 当前边界

- 当前没有真实调用 pyqlib Alpha158/Alpha360，也没有执行 Qlib 模型训练。
- 当前 `Qlib研究` 页面展示的是独立研究能力、接入状态和本地适配器样例，不代表已完成生产级 Qlib 流水线。
- Qlib 研究产物后续只能进入 shadow signal、paper trading 和晋升状态机；未经硬指标和风控门禁，不得直接驱动交易。

</details>

---

## 19. 项目健康巡检基线

更新时间：2026-07-13 16:32 +08:00。

本节记录一次证据化巡检结果。结论不是“逐行绝对无缺陷”，而是：按当前测试、接口、浏览器验证、数据库状态和运行进程看，核心功能处于可运行状态；启动和常用缓存路径性能已恢复，仍存在离线研究模块和大规模历史计算待完善项。

### 19.1 本次修复

| 问题 | 处理结果 |
|---|---|
| `ui_verify.mjs` 会调用 `/api/execution reset`，污染真实模拟盘账户 | 已改为只读验证，并加契约防止 UI 验证重置账户。 |
| 模拟盘执行状态被测试重置为空仓 | 已从真实 `paper-*` 成交和结构化审计回放恢复：现金 631,345.88，4 个持仓，6 条规范订单，6 条成交。 |
| 结构化审计表出现 `O1/O2/O4/O-unit` 等测试订单 | 已清理测试订单、测试成交、测试风险事件和 unit 审计记录；`verify_paper_rules.py` 改为临时 SQLite，避免再污染真实库。 |
| 市场浏览实时 TOP 在周末显示本机日期 `20260711` | 已改为交易日历/最新 K 线日期，2026-07-11 周六显示最新交易日 `20260710`。 |
| PersistentRunner 旧进程清理可能匹配 PowerShell 自身 | 已排除 `$PID`，避免清理脚本自杀导致 `cleanup skipped`。 |
| `/api/execution action=all` 对字符串/浮点混合时间排序报错 | 已增加 `_sort_timestamp()`，支持运行时浮点时间和审计字符串时间混排。 |
| watchdog 后端重启后未恢复 `paper_trader.py` daemon | 已让 watchdog 读取 `paper:status.running`，未显式禁用时自动拉起 paper daemon。 |
| 日志持久化测试偶发失败 | `log_persistence_tests.mjs` 改为轮询等待异步落库。 |
| `ai_execution_agent` 单测曾写入真实 AI 记忆 | 已修复 cache 绑定；已清理测试经验记录。 |
| `数据管理` 页面白屏，报 `ctxMenu is not defined` | 已移除 `DataManagePanel` 内错误的右键菜单状态引用，菜单只由 `DbPanel` 公共层渲染。 |
| `市场浏览 Top100` 行右键菜单未显示 | 已将菜单从 `RealtimePanel` 分支提升到 `DbPanel` 主 return，Top100 行右键可打开操作菜单。 |
| 项目启动慢，后端首次功能接口约 11.78 秒才可用 | 已优化启动路径、市场指数冷启动缓存和 Vite 启动方式；2026-07-12 干净启动后端功能接口约 4.78 秒可用。 |
| `IC评估` 曾约 6-7 秒，被 UI 验证标记为慢响应 | 已为 `factor_runner.py` 的单因子评估增加参数签名缓存；缓存命中后 UI 验证中 IC 评估约 417 ms，批量 IC 约 432 ms。 |
| 多个 Python runner 常驻时私有内存偏高、线程偏多 | 已在 runner/daemon 启动环境中限制 `OMP/OPENBLAS/MKL/NUMEXPR` 线程为 1，并缩短 PersistentRunner 默认空闲保留时间。 |
| 周末数据新鲜度误回退两个交易日 | 已修正 `data_freshness.py` 的交易日计算，2026-07-12 正确指向最近交易日 `20260710`。 |
| TdxQuant 成交额和成交量单位存在混用风险 | 已统一成交额“万元转元”、成交量“手转股”，并保留原始单位字段供审计。 |
| 过期批量行情缓存可能继续参与 TopN | 已拒绝过期批量缓存，实时覆盖后重新按成交额排序。 |
| 财务数据可能取到旧报告期 | 已改为按报告日期选择最新记录。 |
| 周末测试 Tick 污染逐笔表 | 已删除 `20260711`、`20260712` 非交易日测试 Tick，仅保留最近交易日有效小窗。 |
| AI 因子候选可能绕过晋升状态进入运行时 | 运行时只加载 `approved` 因子；候选、shadow、retired 均不会进入交易因子集合。 |
| 限价/人工订单从提交到成交之间可能越过最新风险状态 | 成交前再次同步调用 risk gateway；不通过则拒绝成交并写入结构化审计。 |
| verifier 可能验证旧决策 | verifier 输出绑定 `decision_id` 和决策时间；模拟盘拒绝 ID 不匹配或早于当前决策的验证结果。 |
| 审计回放多条件查询可能串入其他链路 | `run_id`、`decision_id`、`order_id` 改为 AND 过滤，model call 同步按链路筛选。 |
| 回测存在同一根 K 线生成信号并按收盘成交的前视偏差 | 已改为 T 日收盘生成信号、T+1 开盘执行，并补齐 long-only 负信号平仓和初始资金收益率口径。 |
| 策略标准化使用全样本均值/方差 | 已改为 expanding z-score，只使用当时及以前的数据。 |
| HTTP 请求体无限制、无效 JSON 处理不明确 | 请求体限制为 1 MiB；无效 JSON 返回 400，超限返回 413；控制面写操作必须鉴权。 |
| 日志和 PersistentRunner 错误输出可能无限增长 | 日志默认保留 30 天；runner 只保留有界 stderr 尾部并在失败时返回。 |
| SQLite 文件膨胀至约 1.0 GB | 使用 `VACUUM INTO` 校验后原子替换，压缩至 373,829,632 bytes，完整性 `ok`、空闲页为 0。 |
| 成交前二次风控单测写入生产审计表 | 测试已改用 `tmp_path` 临时 SQLite；已清理 `run-1/decision-1/O1` 测试订单，复跑后生产库新增数为 0。 |
| 报价代码带 `sh/sz` 前缀时持仓标价可能失配 | 执行层统一把报价键归一为 6 位代码，启动时迁移并合并重复规范订单。 |
| 多进程同时修改 `execution:state` 存在覆盖风险 | 所有状态变更统一进入跨进程文件锁；只读查询不再回写账户状态。 |
| 模拟订单重试可能重复下单 | 订单路由使用 `交易日:decision_id:代码:方向:数量` 作为稳定 `client_order_id`，执行层再次去重。 |
| 账户状态与订单/成交审计可能部分成功 | SQLite 下使用单一 `BEGIN IMMEDIATE` 事务原子提交账户状态和结构化审计，失败整体回滚。 |
| 熔断后可能阻止合法减仓 | 合法且不超过可卖持仓的减仓卖单允许穿过账户级退出阻断，但仍受停牌、跌停、T+1、数量合法性约束。 |
| 固定滑点会高估大额订单成交能力 | 市价模拟成交默认限制为当期成交量的 1%，并按参与率平方根增加市场冲击。 |
| 订单历史显示市价单 `0.00` 和原始时间戳 | 前端改为优先显示实际成交价，并将秒级时间戳格式化为本地日期时间。 |

### 19.2 最近一次启动验证状态

| 模块 | 当前状态 |
|---|---|
| 验证时间 | 2026-07-13 16:32 +08:00，执行可靠性改造后重新启动并完成浏览器验证。 |
| 前端 | `http://127.0.0.1:8888` 正常监听。 |
| 后端 | `http://127.0.0.1:8880` 正常监听。 |
| 启动耗时 | 本轮受控重启至前后端监听约 5.62 秒；历史冷启动后端功能接口约 4.8-5.9 秒，基础可用通常小于 7 秒。 |
| paper daemon | watchdog 显示存活，进程已自动恢复。 |
| AI scheduler | watchdog 显示存活，provider=`glm`。 |
| AI verifier | `overall=pass`，数据新鲜度、Operator、决策一致性、组合计划、risk gate 全部通过。 |
| 最新 AI 决策 | `source=scheduler_research_idle`，本次为 `trade_policy=normal`；2026-07-12 为非交易日，研究循环可以运行，但 `trade_allowed=false` 属于硬门禁预期行为。 |
| 模拟盘账户 | 总权益 1,005,122.88，现金 631,345.88，持仓 4 只，规范订单 6 条，成交 6 条；本轮未提交测试订单。 |
| 数据层 | 股票池 5203，K 线 key 5204，最新交易日 `20260713`；健康股票 5096，问题 107，覆盖率 97.94%。当前问题均为价格跳变，需继续区分复权事件与异常数据。 |
| 因子层 | `factor_evaluation.json` 覆盖 5204 只、58 因子、1/5/10/20 日周期、数据最新至 `20260710`；`factor_evaluation_neutral.json` 已完成行业/市值中性化评估。 |
| 中性化因子结果 | 强有效 3 个、中等有效 23 个、弱/无效 32 个；结果仅作为研究证据，不能直接跳过晋升状态机。 |
| 策略层 | 已生成理想化和真实约束两套全市场扫描；API/前端优先读取 `strategy_scan_realistic.json`。真实约束下 11 个策略仅 3 个盈利，当前 AI 策略 `approved=0`。 |
| Tick | `market_ticks=7806`，仅保留最近交易日实时小窗；大规模 Tick 不进入 SQLite。 |
| 审计表 | `ai_decisions=263`，`orders=52`，`trades=31`，`positions_snapshots=197`，`risk_events=52`，`model_calls=1519`，`audit_events=91704`。 |
| SQLite | 当前 430,006,272 bytes（约 410 MB）；数据管理统一显示真实 key 数、数据库容量、股票池/K线覆盖和健康快照。 |
| 常驻资源 | 后端 Node 约 68-90 MB；Vite 开发服务约 149 MB 工作集；数据管理使用独立轻量 `sync_runner.py`，不再让控制面轮询排队等待行情 runner。 |

### 19.3 验证结果

| 验证 | 结果 |
|---|---|
| 核心 Python 测试 | 164 passed。新增覆盖减仓通道、最大回撤、报价归一、状态迁移、跨进程锁、幂等订单、成交量参与、市场冲击和原子审计。 |
| Python 脚本/合同测试 | 190 passed。 |
| Node 契约组合 | 43 个脚本全部 passed，覆盖数据源策略、成交额新鲜度、控制面鉴权、请求体限制、日志保留、runner 生命周期、Qlib/Jin10 页面和订单历史展示。 |
| `python scripts/smoke_test.py` | 7 层冒烟全部通过；日 K 按现行 TdxQuant 主源、腾讯校验/兜底链路验证，3 个样本均由 TdxQuant 返回。 |
| `python scripts/verify_paper_rules.py` | 模拟盘、LLM 配置、风险和审计规则验证通过，测试数据库与生产库隔离。 |
| `npm run build` | Vite 8.1.4 构建通过，1690 modules，本轮约 1.06 秒；主包约 490.96 kB，gzip 约 127.56 kB。 |
| `npm audit --json` | 0 vulnerabilities。 |
| `node scripts/web_verify.mjs` | 25 passed / 0 failed，包含 GLM 连接和三轨股票估值。 |
| `node scripts/ui_verify.mjs` | 22/22 功能检查通过、0 报错；本轮 IC 约 7.7 秒、批量 IC 约 13.9 秒，被标记为计算密集慢响应，未影响功能正确性。 |
| `node scripts/data_browse_contract_tests.mjs` | passed；覆盖 Top100 成交额、快速访问、自选股相关数据浏览合同。 |
| `node scripts/performance_priority_contract_tests.mjs` | passed；覆盖市场指数后台刷新、因子评估缓存等性能优先合同。 |
| `node scripts/persistent_runner_idle_contract_tests.mjs` | passed；覆盖 runner 空闲回收和进程管理合同。 |
| `node scripts/dbpanel_watchlist_quick_contract_tests.mjs` | passed；覆盖 Top100 右键菜单、watchlist 快速访问、数据管理不引用 `ctxMenu/aiAnalysis`。 |
| 数据管理控制面回归 | 15 个 Python 测试 passed；`sync_control_plane_contract_tests.mjs`、`update_manager_fast_contract_tests.mjs`、`security_regression_tests.mjs` passed。 |
| 数据管理性能 | 状态冷启动约 2.19 秒，暖查询约 121-214 ms；单股已最新增量任务约 1.74 秒，任务期间状态查询最大约 155 ms。 |
| Watchdog 隔离测试 | watchdog 首次巡检和 daemon 自愈在 Worker 中运行；并发 30 次控制面查询 0 错误，平均约 129.5 ms，未再出现连接重置。 |
| Playwright 浏览器交互抽检 | `交易执行` 刷新后显示总权益 1,005,122.88、现金 631,345.88、4 个持仓、6 笔订单；`模拟盘` 显示调度运行和 GLM 调用统计；`风控监控` 显示各层正常并可展开决策回放。 |
| 浏览器插件抽检 | 执行、模拟盘、风控页面完成真实浏览器切换和异步加载验证；项目控制台 0 warning/error。 |
| 浏览器页面抽检 | 风控页显示数据层 5204 只、执行层 4 持仓/6 订单、总权益 1,005,122.88；最新历史运行可回放决策、风控、订单和成交。 |
| 安全探针 | 未鉴权控制动作返回 403；合法 token 可进入处理器；无效 JSON 返回 400；超过 1 MiB 请求返回 413。 |

### 19.4 数据与交易口径

- 实时行情优先 TdxQuant；成交额缺失时使用腾讯补齐，单行可能出现 `source=tdx_quant`、`amount_source=tencent`。
- `data.latest_date` 表示交易日，不表示本机请求日期；非交易日以交易日历和最新 K 线修正。
- 日 K/分钟 K 以 TdxQuant 为主，腾讯做交叉校验和兜底；财务以 AkShare/Tushare 补全并按最新报告期选择；tdxrs 提供真逐笔，TdxQuant snapshot 仅作为明确标记的兜底。
- 金十 MCP 仅承担宏观行情、市场快讯、新闻资讯和财经日历，不作为 A 股个股成交或财务主源。
- 模拟盘状态以 `execution:state` 为当前账户，以 `orders/trades/positions_snapshots/risk_events/audit_events` 做结构化回放。
- 所有订单必须经过同步 risk gateway；限价和人工订单在真正成交前还会二次检查。AI 只能提交意图，不能修改硬限制、kill switch 或绕过 verifier。
- 执行状态修改使用跨进程文件锁；状态、订单和成交审计在 SQLite 中原子提交。状态/持仓/总览等只读查询只做内存标价，不再反向改写共享状态。
- 自动止损只卖出 `available_qty`，不会因持仓中含当日买入数量而整单触发 T+1 拒绝；停牌和跌停封板仍然拒绝成交。
- 市价模拟成交默认受 1% 成交量参与上限和数量驱动市场冲击约束，相关参数位于 `ai:autonomous:config.execution`，AI 不能借此绕过硬风险网关。
- 策略回测使用 T 日收盘信号、T+1 开盘成交，并统一纳入手续费、滑点、涨跌停和 T+1 约束。
- 全市场市场扫描同时保留理想化与真实约束结果；对外 API 和前端必须优先展示真实约束结果，理想化结果只用于研究对照。
- UI/自动验证脚本不得再执行账户 reset；需要重置必须人工明确执行。

### 19.5 已知风险与后续优化

- `IC评估` 暖缓存约 0.4 秒；首次未缓存的大规模因子评估实测可到约 10.8 秒，仍需继续推进离线预计算、异步任务化和历史矩阵存储。
- 完整 5204 股票策略扫描实测：理想化约 8.1 分钟，真实约束约 8.7 分钟；必须作为离线任务运行，前端只读取预计算文件，后续应拆为异步 worker 并增加参数签名缓存。
- 策略对成本高度敏感：理想化结果 9/11 盈利，加入单边 0.15% 成本和涨跌停拒绝后仅 3/11 盈利；`range_pct` 从理想化年化 `+62.4%` 变为真实约束 `-65.7%`。禁止用理想化结果做晋升依据。
- 当前真实约束扫描最佳为 `pvbeta_20`：年化约 `39.0%`、Sharpe `1.371`、最大回撤约 `-16.0%`。该结果仍是历史回测，不代表样本外和 paper trading 已通过。
- 当前 AI 策略晋升列表为 0，表示没有 AI 生成策略满足 approved 门槛；内置策略和扫描功能可用，但不能据此宣称策略已具备生产资格。
- 历史 `model_calls` 记录均没有 `run_id/decision_id`；表结构和回放过滤已经支持链路 ID，但所有 LLM 调用点的上下文传播尚未完全补齐。新调用应逐步强制携带链路 ID，旧记录无法无损反推。
- Qlib 当前为 `local_adapter_only`，`pyqlib_installed=false`；还没有真实 Alpha158/Alpha360、模型训练和 Qlib 回测流水线。
- ClickHouse 目前只是规划，尚未部署；SQLite 只适合实时状态、审计和小窗 Tick，多年历史、分钟级矩阵、全市场 Tick 和大规模训练应迁移 ClickHouse/Parquet + 离线 worker。
- 当前 Tick 只覆盖持仓、自选、AI 候选和待下单标的的小窗采集，不代表全市场、全日、全历史 Tick 已完整归档。
- TdxQuant、tdxrs、金十 MCP 和 GLM 均为外部依赖；本地健康不等于上游永久可用，盘中必须继续执行数据新鲜度和降级检查。
- 当前项目主运行环境是 Python 3.14。全局环境中的可选 `transformers/torch` 存在版本兼容提示，但不在当前 GLM API 主链路中；后续本地深度学习/GPU worker 应使用隔离的 Python 3.11 环境。
- 系统仍是模拟盘和研究系统；实盘券商接入、机构级双人复核、权限隔离配置服务和自动对账尚未完成。
- “一年达到一亿元”只能作为研究目标和压力测试参数，不能作为收益承诺或风险预算放宽依据。

### 19.6 自动巡检任务基线

更新日期：2026-07-12 +08:00。

Codex Desktop Agent 中已固化 5 类自动任务，全部默认只读，不允许直接修改代码、交易配置、风控阈值、真实交易接口或绕过 verifier/risk gateway。

| 任务 | 频率 | 当前职责 |
|---|---|---|
| XuanJi 盘中健康监控 | 交易日盘中约每 15 分钟 | 仅在 09:35-11:30、13:00-15:05 深检；检查前后端、paper status/progress、risk trace、TdxQuant/tdxrs 数据新鲜度、market_ticks、TOP30、AI scheduler、watchdog、GLM/model_calls、金十 MCP、Qlib 页面和日志异常。 |
| XuanJi 盘后系统复盘 | 交易日 17:30 | 生成日报，回放 ai_decisions/model_calls/orders/trades/risk_events/audit_events，检查数据新鲜度、模拟盘调度、AI 降级、金十/Qlib 页面和 Web 冒烟结果。 |
| XuanJi 每周工程健康巡检 | 每周日 | 只读运行关键测试、构建/冒烟、数据库体积、慢功能、常驻 runner、敏感配置、数据健康、调度健康和性能风险检查。 |
| XuanJi 每周 AI 量化技术雷达 | 每周六 | 联网跟踪 AI 量化、因子发现、Qlib、深度学习选股、强化学习、risk gateway、audit replay、market microstructure 等方向，并对照本项目给出待确认迭代清单。 |
| XuanJi 每月架构与性能体检 | 每月 | 深度检查 L0-L6 架构、AI 决策协议、promotion、risk gateway、audit replay、TdxQuant/tdxrs/金十/Qlib 数据链路、性能、安全和 AI 运行质量。 |

任务执行原则：

- 盘中任务必须先做交易时段门禁；非交易日或非盘中只记录轻量状态。
- 盘后任务延后到 17:30，避免收盘后数据、成交回放和日志尚未完整时过早判定。
- 周度/月度任务只提出改造建议和验证计划，不自动落地代码变更。
- 所有报告必须区分“已验证证据”和“无法检查/待人工确认”，不得把工具失败包装为系统健康。

---

## 20. 股票估值研究工作台

更新日期：2026-07-13 +08:00。

`数据浏览 > 股票估值` 已形成独立研究链路，Top100 股票行右键也可直接跳转并自动带入代码和名称。页面采用四轨并列设计：

| 估值轨 | 方法 | 触发方式 | 边界 |
|---|---|---|---|
| 绝对估值 | 标准化 FCFF/FCFE 的五年三阶段 DCF，保守、中性、乐观三情景 | 自动 | FCFE 只使用股权资本成本 `Ke`；FCFF 使用含债务税盾的 `WACC`。优先取最近三个年度自由现金流中位数，缺失时才降级为披露单期、TTM、经营现金流减资本开支或维护性资本开支代理；不使用净利润冒充自由现金流。 |
| 相对估值 | PE、PEG、PB、PS，同业 IQR 异常值过滤、相似度加权分位数 | 自动 | PEG 优先使用净利润增长，不再把营业收入增长当作首选盈利增长；同行按市值、盈利增长、ROE 和净利率相似度加权，方法权重同时考虑样本量和离散度。 |
| 市场估值 | 个股历史位置、行业位置、指数状态、市场宽度和流动性 | 自动 | 绝对估值与相对估值先形成加权基础价值，市场状态只调整一次，调整范围固定限制在 `-20%` 到 `+20%`；历史不足三年必须显示降级。 |
| GLM 模型估值 | 读取同一数据快照和三类规则估值，输出独立目标区间、假设、驱动、风险、失效条件 | 人工点击 | 严格 Schema；格式或数值越界直接废弃；不覆盖规则估值、不生成订单。 |

### 20.1 数据与缓存

- 估值输入由 `quant/valuation/data.py` 统一构建，TdxQuant 行情和财务字段优先，现有腾讯、缓存财务和 Baostock 行业链路负责明确降级或补全。
- 财务记录统一按 `valuation_as_of` 做 point-in-time 过滤：有公告日时排除估值时点尚未公开的数据；缺少公告日时保留报告期口径并标记 `report_period_only`，不会伪造公告日期。
- 财务层生成 `financial_as_of`、`point_in_time_quality`、`point_in_time_quality_score`、年度记录和 TTM 指标。非年报 TTM 使用“上一完整年度 + 当前累计期 - 上年同期累计期”，字段不足时明确返回不完整口径。
- TdxQuant 万元/万股字段在适配层显式换算；每个字段保留来源，`NaN/inf` 转为缺失值，不生成伪数据。
- AKShare 财务摘要刷新会保留营业收入、归母净利润、经营现金流、每股企业自由现金流和每股股东自由现金流；首次选择字段不完整的股票时允许执行一次有界联网补全，结果持久化到 `fin:abstract:<code>`。
- 当用户切换到尚未完成新版财务补全的股票时，估值服务会自动调用 AKShare 财务交叉补全并持久化结果，不再要求人工先运行数据更新。失败结果短期缓存并明确降级，成功后后续估值直接读取本地缓存。
- 个股估值日线默认目标为 900 根；缓存不足时由 TdxQuant 增量补齐，遇除权价格跳变时保留 `factor` 并生成 `adjusted_close`，避免历史分位被未复权价格扭曲。
- 无时间戳但具有有效成交量/成交额的 TdxQuant 盘中快照，按本地交易时段标记为 `live` 并记录采集时间；盘外仍保持陈旧或前收盘降级，不伪造交易所时间。
- 沪深300日线会派生指数历史分位和 `bull/neutral/bear` 市场状态，供市场估值使用；同行同时派生营业收入增长、净利润增长、ROE、净利率和市值，支持质量匹配后的 PE/PB/PS/PEG。
- 基本面按状态使用 24 小时、15 分钟或 60 秒分级 TTL；实时行情 5 秒；同业成员 30 分钟；同业实时倍数 5 秒。
- 同业最多返回 24 只，排除目标自身、ST、920/BJ、缺少有效报价或估值基础字段的股票；无效头部样本会继续向后回补。

### 20.2 存储与审计

- `stock_valuations` 按 `valuation_id + valuation_type` 唯一保存输入快照、输出、公式版本、模型版本、prompt 版本、数据日期和报告期。
- `valuation_forecasts` 保存绝对估值、相对估值和最终共识的预测中枢、当时价格、到期日及后验误差；到期后使用历史日线结算。
- `valuation_model_calibration` 保存各规则模型的样本数、MAPE、方向命中率和可靠性系数。结算样本少于 20 个时强制使用中性先验 `1.0`，避免小样本把模型权重放大。
- 每条估值写入 `audit_events.event_type=stock_valuation`，GLM 调用继续由 `llm_client.py` 写入 `model_calls`。
- `analyze` 运行绝对、相对、市场三轨，并返回独立 `consensus`：基础权重由模型置信度、数据质量和历史校准共同决定，市场调整只应用一次。30 分钟数据签名缓存命中时直接复用。
- `glm_analyze` 是独立受保护动作，缓存签名额外包含 GLM 模型和 prompt 版本。

### 20.3 API 与验证

```text
POST /api/valuation
  action=analyze      # 只读，自动运行三类规则估值
  action=latest       # 只读，查询最近一次结构化估值
  action=glm_analyze  # 控制面动作，需要 XUANJI_API_TOKEN
```

当前专项验证命令：

```powershell
python -m pytest scripts\valuation_engine_tests.py -q
node scripts\valuation_api_contract_tests.mjs
node scripts\valuation_frontend_contract_tests.mjs
npm run build
```

估值结果只用于研究和人工判断，不构成收益承诺，不改变 risk gateway、kill switch、仓位上限或订单路径。

### 20.4 GLM 估值运行约束与最新验证

- GLM 输入使用有界证据包，不发送完整历史大对象：财务记录最多 8 期、个股日线最多 24 根、指数日线最多 12 根，并保留三类规则估值、关键基本面、市场摘要和数据警告。
- GLM prompt 已升级为 `valuation-v2`，证据包显式包含最终共识和估值语义：基础价值只由绝对估值与相对估值加权形成，市场状态仅调整一次，GLM 只能给出独立研究意见。
- GLM-5.2 单次调用预算为 `max_tokens=3600`、上游超时 105 秒、自动重试 0 次；API 总超时 150 秒，避免慢推理触发重复扣费或重复审计。
- 只有 Schema 完整且数值边界通过的 GLM 结果才缓存 30 分钟；错误结果仍写入结构化估值与审计记录，但不会缓存，人工可立即重试。
- 2026-07-13 浏览器插件实测：Top100 右键选择 `603986 兆易创新` 后成功跳转并带入代码和名称；绝对、相对、市场三轨自动返回；手动 GLM 轨返回完整区间、置信度、假设、驱动、风险和失效条件。
- 2026-07-13 `300442 润泽科技` 专项修复实测：财务历史 52 期；日线 900 根，覆盖 `20221018-20260713`；绝对估值使用 `20251231` 披露的每股股东自由现金流；PE/PB/PS/PEG 全部可用；市场历史覆盖 46 个月；沪深300指数分位和状态可用；绝对、相对、市场三轨均为 `success`。
- 同一数据快照强制重跑 GLM 后返回 `success`，置信度 `1.0`，不再出现资本开支代理、6%基准增长、PEG 不可用、16个月历史覆盖或指数维度缺失等旧缓存结论。
- 浏览器插件复验：三条规则估值均显示“完整”，PEG 正常展示，输入层“未发现数据警告”；手动 GLM 重试后返回“完整”，核心假设明确使用 FCFE，旧的资本开支代理、6%基准增长、PEG 不可用、16个月覆盖和指数维度缺失提示均未再出现。
- 换股自动补全实测：`600519 贵州茅台` 初始只有 102 期财务比率字段、无自由现金流且日线仅 300 根；首次估值自动补齐 FCFF/FCFE 字段和 900 根日线，绝对、相对、市场三轨均为 `success`，PEG 可用且无输入警告。首次联网补全约 17 秒，后续缓存命中约 0.7 秒。
- 2026-07-13 机构化估值升级专项回归：`108 passed`；估值 API 合同、前端合同、Python 编译检查和 Vite 生产构建均通过。页面规则估值中枢读取最终共识，不再把绝对、相对和已经调整后的市场估值再次平均。
- 浏览器插件复验：`300442` 页面显示 FCFE/Ke、标准化每股现金流、模型权重、PIT 财报口径和 TTM 公式；手动 GLM 返回完整结果，并准确说明“两阶段共识 + 市场仅调整一次”，未改写规则中枢。
- Vite 开发服务器已忽略 `.venv-qlib`、`data`、`logs`、`dist` 和 Python 缓存目录；干净重启后 15 秒采样约 119 MB、639 句柄，修复前约 613 MB、48,887 句柄。
