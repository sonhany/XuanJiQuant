<p align="center">
  <img src="Logo/logo_horizontal.svg" width="360" alt="XUANJI" />
</p>

<h1 align="center">玄机量化 XuanJiQuant</h1>

<p align="center">
  <em>璇玑玉衡，以齐七政 ——《尚书·舜典》</em>
</p>

<p align="center">
  <strong>面向 A 股的数据 · 因子研究 · 策略评估 · Qlib 实验 · 确定性风控 · 模拟账本工作台</strong>
</p>

<p align="center">
  <a href="#当前架构">当前架构</a> ·
  <a href="#模块职责">模块职责</a> ·
  <a href="#agent-退役后的硬边界">硬边界</a> ·
  <a href="#确定性研究">确定性研究</a> ·
  <a href="#启动与验证">启动与验证</a> ·
  <a href="Logo/璇玑XUANJI品牌设计展示.html">品牌手册</a> ·
  <a href="docs/XUANJI_HANDOFF.md">交接文档</a>
</p>

---

## 项目定位

本项目是面向 A 股的数据、因子研究、策略评估、Qlib 实验、确定性风控和模拟账本工作台，全部运行在本机。
**当前不连接实盘，不承诺收益。**

| 维度 | 现状 |
|---|---|
| 运行形态 | 本机 Windows 单机；Web `127.0.0.1:8888` + Node API `127.0.0.1:8880` + Python 量化核心 |
| 数据与存储 | 默认 SQLite 状态总线 + 本地文件产物（`data/` 不入库） |
| 研究链路 | 日频确定性研究流水线、周频 Qlib 训练、周频 F4 多 Alpha 候选工厂 v2 |
| 模拟执行 | F5 确定性日频 + 盘中模拟执行，独立账本 `data/paper/f5_ledger.db`，十项对账 |
| AI 边界 | AI Agent 自治控制面已于 **2026-08-13 退役**；只保留**只读 AI 影子研究**（`DecisionProposal` 合同，零执行权限） |
| 权限事实 | `live_execution_authority=false`，任意 `place_order` 仍以 HTTP 409 拒绝 |

> 品牌释义与视觉规范见 [`Logo/璇玑 XUANJI.md`](Logo/璇玑%20XUANJI.md) 与[品牌设计手册](Logo/璇玑XUANJI品牌设计展示.html)。
> 完整交接边界见 [`docs/XUANJI_HANDOFF.md`](docs/XUANJI_HANDOFF.md)，系统流程图见 [`docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`](docs/XUANJI_SYSTEM_WORKFLOW_MAP.md)。

## 快速开始

```powershell
node scripts/start_services.mjs     # 幂等启动 Web + API
python -m pytest -q                 # Python 回归
npm run test:contracts              # Node 契约测试
npx tsc --noEmit && npm run build   # 类型检查与构建
```

- Web：<http://127.0.0.1:8888>；API：<http://127.0.0.1:8880>
- F5 活动账本：`data/paper/f5_ledger.db`；政策：`config/f5_paper_execution.json`
- 计划任务安装：日频 `scripts/install_f5_paper_task.ps1`，盘中 `scripts/install_f5_intraday_task.ps1`（安装前必须先完成全量回归）

---

# 玄机量化（XuanJiQuant）

2026-09-16 Web 可见性补齐：投资驾驶舱新增“AI影子研究”只读状态卡，数据来自 `/api/workbench` 的 `shadow_research` 字段。Node 端 `lib/shadow-research-status.mjs` 只检查 `data/nautilus-baseline/baseline_result.json → runtime_summary.json → ai_raw_output.json → shadow_cycle_report.json → shadow_decisions.sqlite3` 这条研究证据链是否存在和何时更新；缺失会明确显示为 `baseline_missing`、`runtime_summary_missing`、`shadow_ai_raw_output_missing` 或 `shadow_cycle_report_missing`。该 Web 卡片固定 `execution_authority=false`、`can_trigger_order=false`、`live_execution_authority=false`，不调用 `/api/paper`、`/api/paper-execution` 或 `/api/execution`，只能帮助判断后台只读影子研究推进到哪一步。

2026-09-15 只读 AI 影子研究接入日频流水线：`scripts/run_daily_research_pipeline.py` 在每日研究成功发布或恢复后，会检查 `data/nautilus-baseline/baseline_result.json`；存在已对账 paper baseline 时，生成 `shadow_research` 阶段和 `xuanji-shadow-runtime-summary-v1` 运行摘要。若同时存在 `data/nautilus-baseline/ai_raw_output.json`，才继续执行 `shadow-cycle` 并写入独立 `shadow_decisions.sqlite3` 与只读报表；若缺少 AI 原始输出，只记录 `shadow_ai_raw_output_missing` 并跳过 AI，不阻断每日研究。新增受控生产入口 `baseline-export` 和 `shadow-ai-output`：前者只发布已对账且 `live_execution_authority=false` 的 baseline，后者只发布通过 DecisionProposal 合同校验的 AI 原始输出。该阶段固定 `execution_authority=false`、`can_trigger_order=false`、`live_execution_authority=false`，不打开 F5 账本、不调用 `/api/paper` 或 `/api/execution`。

2026-09-14 继续验证：`hot_snapshot` 已补齐真实可得的交易所身份、交易所事件时间语义、股数单位、买卖一档、项目交易日历和带来源标记的日价格带/停牌估计；热行情过期阈值从 3000ms 调整为 5000ms，与隔离 Nautilus 准入一致。实测 `600000,000001` 两只盘中样本执行数据准入 2/2 通过；`600519` 因源报价 7.9 秒未更新仍被正确拒绝。新增 `build_observed_realtime_request()` 可把准入通过的实时快照转换为隔离 paper 回放请求；`data/nautilus-baseline/continuous-observed-final-20260914.sqlite3` 已用 600000 当前行情完成一笔 100 股买入回放，现金 `99054.99`、持仓 `600000:100`、六项对账与恢复通过，`live_execution_authority=false`。新增只读 `DecisionProposal` 影子合同与 `shadow-runtime-summary` 受控输入包，只允许 AI 消费已组装摘要并输出可验证研究建议；不接执行、不复活旧 Agent、不连接券商。

2026-09-13 后续验证：`trading_system/intake.py` 已通过既有数据 API 观察真实行情；`continuous.py` 增加单账户跨批次持久回放，未切换活动 F5。修复 `scripts/market_data.py` 丢弃新浪日期、把历史报价拼成今天的缺陷，API 重载后已实证返回正确 9 月 11 日日期。真实行情执行字段仍缺失，本轮没有启用 AI。最终相关 Python 124 项通过（124 条上游弃用警告），Node 58/58；首次账户读取超时单独留痕。详见[数据与连续账户报告](docs/superpowers/specs/2026-09-13-continuous-account-verification.md)和[运行方法](trading_system/README.md)。

2026-09-13 新架构阶段 B：新增隔离的 `trading_system/` 确定性离线基线，真实 Nautilus 内核加准入/预留规则、单写者持久日志与完整重放恢复。34 项测试通过，另有 62 条上游弃用警告；重复请求、竞争写入、两个提交断点的进程强退已验证。见[操作与模块边界](trading_system/README.md)和[恢复验收](docs/superpowers/specs/2026-09-13-nautilus-baseline-recovery-verification.md)。每个试验独立起算，不是连续盘中账户；未切换 F5、未部署 AI、未连接券商。

2026-09-11 新架构研发进度：已在隔离环境执行LEAN与NautilusTrader的真实内核实验，选择NautilusTrader作为AI自主模拟系统的开发主线。当前活动F5没有切换。实验代码与锁定依赖位于`experiments/kernel_evaluation/`；结论见[内核实测报告](docs/superpowers/specs/2026-09-11-kernel-evaluation-results.md)。Nautilus回归为7通过、4项A股准入预期失败；LEAN完整Engine完成10个合成场景，不能把退出码0解释为全部业务通过。T+1、证券状态、日价格带、交易单位、保守撮合和持久账户恢复仍是新内核接管前的必要工作。

本项目是面向 A 股的数据、因子研究、策略评估、Qlib 实验、确定性风控和模拟账本工作台。当前不连接实盘，不承诺收益。

> 2026-08-13 已彻底退役 AI Agent 自治控制面。2026-08-19 按人工批准的独立规格新增 F5 确定性日频模拟执行；2026-08-20 又按方案 A 增加受治理的实验模拟通道。它不含 Agent、不连接券商、不接受任意订单，也不复活旧自动执行链。历史数据库中的旧表、字段和审计记录不改写。

## 当前架构

```text
外部数据源
  -> quant/data + scripts/daily_update.py
  -> DataSnapshot / SQLite / Qlib 数据集
  -> quant/factor + 确定性因子评估
  -> quant/strategy + F4 走样本外/组合级验证
  -> quant/risk + 硬风险规则
  -> quant/paper_execution + F5 盘中实时行情模拟 / 日频次日模拟与对账
  -> 独立 F5 账本 / 只读历史账本 / 审计页面

固定研究日程：
Windows 任务 XuanJiQuant-Research-Daily（交易日 16:20 / IgnoreNew）
  -> scripts/run_daily_research_pipeline.py
  -> daily_update.py（必要时补齐预期交易日）
  -> DataSnapshot 质量、新鲜度、版本门禁
  -> scripts/research_training_scheduler.py --once
  -> evaluate_factors.py
  -> research_selection_daily / generate_research_portfolio.py
  -> data/research/selections/<portfolio_id>/portfolio.json
  -> ResearchJobStore（幂等、互斥、审计）
  -> shadow_research（仅当已对账 baseline 存在；生成 runtime summary；有 AI 原始输出才运行 shadow-cycle；只读、不交易）

Windows 任务 XuanJiQuant-Qlib-Weekly（周六 18:30 / IgnoreNew）
  -> research_training_scheduler.py --once（ResearchJobStore 认领）
  -> qlib_schedule.py（六年 PIT -> 质量门禁 -> 行业/基准 -> Qlib 导出 -> 训练 -> 双引擎回测）

Windows 任务 XuanJiQuant-Strategy-Weekly（周日 10:00 / IgnoreNew）
  -> research_training_scheduler.py --once
  -> 当前完整同版本因子发布门禁
  -> validate_strategy_portfolios.py --once（PIT / 行业 / 基准 / 质量 + F4）
  -> Qlib 候选不可用只隔离 Q1-Q4，不控制整个 F4

Windows 任务 XuanJiQuant-Paper-Daily（交易日 17:10 / IgnoreNew）
  -> scripts/f5_paper_execution.py --once
  -> 结算上一目标交易日的准备计划
  -> 订单/成交/现金/持仓/权益十项对账
  -> 准入当天 F4 合格组合，或仅因绩效门禁失败但数据/身份/约束可信的实验组合
  -> validated_paper / experimental_paper 双通道准备下一交易日

Windows 任务 XuanJiQuant-Paper-Intraday（交易日 09:35-11:25、13:05-14:50，每 5 分钟 / IgnoreNew）
  -> scripts/f5_paper_intraday.py --once（只接受当前时间，不允许回填日期）
  -> 读取上一完整 research generation 及其受治理组合
  -> 主动刷新组合与持仓证券的实时行情（120 秒新鲜度门禁）
  -> 目标差额、硬风控、容量/涨跌停/T+1、费用和滑点模拟
  -> 立即写入独立 F5 订单/成交/现金/持仓/权益并完成十项对账
  -> 同一交易日 + 同一组合 + 同一政策幂等，不重复成交

`start_services.mjs` 只常驻 Web 与 API；`research_training_scheduler.py` 不再常驻轮询，只能由上述三项计划任务以 `--once` 启动，避免多个时钟争抢同一研究任务。

2026-09-01 计划任务后台化：`XuanJiQuant-Paper-Daily`、`XuanJiQuant-Paper-Intraday`、`XuanJiQuant-Research-Daily`、`XuanJiQuant-Qlib-Weekly`、`XuanJiQuant-Strategy-Weekly` 不再直接启动控制台版 `python.exe`，统一由 `scripts/run_hidden_scheduled_task.ps1` 的五个固定 `TaskKey` 映射到原解释器、脚本和参数。任务动作使用 Windows PowerShell 的 `-NonInteractive -WindowStyle Hidden`，启动器再以 `Start-Process -WindowStyle Hidden -Wait -PassThru` 运行 Python 并原样返回退出码；禁止任意命令文本和 `Invoke-Expression`。触发时间、`Interactive/Limited` 身份、`IgnoreNew`、重试次数、运行上限以及模拟/研究权限均未改变；这里的“后台”只表示登录桌面不弹控制台，不改变“用户登录后运行”的既有边界。五个任务已按当前脚本重装，16:46 对 `Paper-Intraday` 的盘外按需触发返回 0，任务恢复 `Ready`，无 Python 进程残留。

2026-08-31 后端连接恢复记录：前端 8888 持续正常，但 API 8880 的 Node 进程在 2026-08-30 23:02:11 最后一条正常 DataSync 日志后消失；日志中没有 SIGTERM、`uncaughtException`、listener error 或优雅关闭记录，`logs/backend.pid` 仍指向已失效 PID 30596，因此定性为外部终止/宿主进程丢失，而不是业务路由异常。使用 `node scripts/start_services.mjs` 幂等恢复后，后端 PID 19636 监听 `127.0.0.1:8880`，前端未重复启动；重复执行启动器能识别两个端口均已监听。验收：Web 19/19、浏览器 10/10、控制台错误 0。若再次出现“前端可开但后端连接被拒绝”，先检查 8880 与 `server-YYYYMMDD.log`，再执行同一幂等启动入口，禁止直接启动第二个 `server/index.mjs`。
```

确定性研究调度所有者为 `ResearchTrainingScheduler`，任务账本为 `ResearchJobStore`。二者只生成研究产物，不拥有交易权限。

Qlib 更新任务自身允许消费“完整但落后”的数据集和“带有效数据版本的不完整原子检查点”，因为它的职责正是补齐并重新通过质量门禁。F4 不读取 Qlib 周任务状态决定是否启动，而由 `validate_strategy_portfolios.py` 直接验证完整 PIT manifest、质量报告、历史行业、基准和每日因子发布。历史失败标的先走全窗口批量预取，批量仍无数据时保留原失败并快速越过，由最终覆盖率和质量门禁统一裁决，禁止单股 TDX/BaoStock/AkShare 回退链拖死全市场周期。外层已认领的到期任务用 `force=True` 调用内部 Qlib 周期；`--lane qlib` 在周六之后只允许恢复同周、同目标市场日、同调度版本的 `failed/blocked/interrupted` 原幂等任务，保证跨日安全重试不会被星期判断误记为跳过，也不会另建一条研究账本。

2026-08-30 全功能复巡进一步收紧 Qlib 增量失败语义：只有实际配置并尝试过批量预取、目标增量标的仍无可用双轨数据，且没有孤儿产物或退市终止历史可恢复时，才以 `source_batch_prefetch_unavailable` 快速失败并交给最终覆盖率/质量门禁；禁止再次进入可能长期占用线程的单股多源回退。job 16 的前三次尝试已因旧实现耗尽，账本保持 `interrupted/qlib_collector_stalled`，不得改 attempt 或另造并行幂等键；下一个合法恢复周期是 `XuanJiQuant-Qlib-Weekly` 的 2026-09-05 周任务。当前公共 PIT manifest 为 incomplete，F4 应按公共数据事实阻断，而不是按 Qlib 任务状态阻断。

市场浏览 Top100 与资金流补充链路：`DbPanel` → `server/routes/data.mjs` → `data_runner.py::action_stocks` → `fetch_stock_market_metrics`。字段包括 `main_net_inflow` 与 `turnover_rate`；东方财富不接管行情主源，腾讯只补换手率。

浏览器仅通过 `/api/*` 访问 Node 路由；Node 通过 `PersistentRunner` 调用 Python runner；核心规则位于 `quant/*`，不得复制到页面或路由。

## 模块职责

| 模块 | 负责 | 不负责 |
|---|---|---|
| `quant/data` | 数据接入、质量门禁、快照、缓存 | 因子判断、交易许可 |
| `quant/factor` | 技术/量价/基本面因子、受限 DSL、IC/IR | 自动生成或自动晋升因子 |
| `quant/strategy`、`quant/backtest` | F4 候选定义、走样本外、组合构建、成本/容量回测和研究门禁 | 下单、生产晋升与修改硬风控 |
| `quant/risk` | 确定性逐单规则和组合风险 | 接受模型放宽阈值 |
| `quant/health.py` | 从日线覆盖、完整研究代、F4 证据和 F5 账本投影四层健康/新鲜度 | 用缓存键数或历史账本猜测当前状态 |
| `quant/paper_execution` | F5 准入、目标差额、盘中实时/日线模拟撮合、独立账本、对账和幂等调度 | 实盘、Agent、任意订单、放宽硬风控 |
| `quant/data/audit.py` | 读取历史决策、风险、订单与成交审计事实 | F5 写入或当前自动下单 |
| `quant/qlib*` | 隔离研究、训练、产物和质量门禁 | 自动晋升生产或交易 |
| `components` / `server/routes` | 展示、协议、鉴权、只读投影 | 推导执行权限 |

## Agent 退役后的硬边界

- 已删除 `quant/agent`、Agent runner/control/scheduler/verifier/memory/recovery、AI 因子/策略 Agent 和对应 Web 组件。
- `/api/execution` 仅允许 `all/status/positions/orders/trades`，这些读取动作全部是唯一 F5 活动账本的兼容投影；其他动作返回 `automatic_execution_disabled`。
- `/api/paper` 仅保留配置、历史状态、日志、报告和基准读取；不存在启动、运行一次、决策、恢复或下单入口。
- `/api/paper` 仍只读；`execution_runner.py` 已退出活动路由，仅保留历史审计兼容代码。数据库中的 `execution:state`、`agent_*`、旧 `ai:*` KV 和历史订单字段是审计事实，不参与当前权益、持仓、风险、告警或日报。
- 2026-08-20 已删除无活动路由、计划任务或运行时引用的旧 `quant/execution` 源码，以及旧 `smoke_test.py` / `verify_paper_rules.py`；历史数据库、日志和文档快照继续保留。
- `/api/paper-execution` 只读动作是 `status/account/runs/orders/fills/positions/equity/reconciliations/audit`；`account` 是驾驶舱、风险、告警、日报和兼容 `/api/execution` 的唯一活动账户投影。受控动作仅有启停后续模拟、F5 熔断、无参数 `run_due` 和无参数 `run_intraday`。
- 普通大模型可用于资讯或估值解释，但没有策略晋升、风险放宽或订单权限。
- 新 AI 影子入口仅限 `trading_system.shadow_decision` 的 `DecisionProposal` 合同：输入必须对照已完成对账的 paper baseline，输出固定 `shadow_only` 且四个执行/策略权限布尔值全为 `false`。它不能调用 `/api/paper`、`/api/execution`、F5 写入口或任何已退役 `agent_*` 控制面。
- AI 影子输入固定为 `trading_system.shadow_context` 的 `ShadowDecisionContext`：只暴露 baseline 哈希/账户摘要、行情、风险、因子、策略和历史摘要；不暴露订单/成交明细、执行参数或旧 Agent 状态。`trading_system.shadow_runner` 当前只使用本地确定性影子模型从 context 生成 proposal；真实外部 AI 后续接入也必须复用同一合同。
- AI 影子上下文自动组装使用 `trading_system.shadow_context_builder`：从受控 baseline/account/market/risk/factor/strategy/history 摘要中提取白名单字段，生成已签名 `ShadowDecisionContext`。它不允许 AI 自行查库，也不会把订单、成交明细、价格、盘口或旧 Agent 状态暴露给模型。
- AI 影子长期记录使用 `trading_system.shadow_decision_store` 与独立 `data/nautilus-baseline/shadow_decisions.sqlite3`。CLI 只提供 `baseline-export`、`shadow-context-build`、`shadow-runtime-summary`、`shadow-ai-output`、`shadow-record`、`shadow-run`、`shadow-ai-run`、`shadow-report` 和 `shadow-cycle` 九个只读研究动作：发布受控 baseline、组装固定上下文、封装受控运行摘要、发布受控 AI 原始输出、记录可验证提案、从固定上下文生成影子提案、适配外部 AI 原始输出、输出与 baseline 持仓集合的差异报表、串联单次只读研究闭环；不得把该库解释为订单簿、目标组合、风控许可或模拟账户。
- `shadow-cycle` 只是 `shadow-context-build -> shadow-ai-run -> shadow-report` 的一次性编排，仍要求调用方提供 `--raw-output`，不默认联网，不调度后台任务，不打开或写入执行 journal。
- 外部 AI 适配器为 `trading_system.shadow_ai_adapter`，只接收调用方提供的 `model_client(request)` 或 `--raw-output` 文件，不默认联网、不读取数据库、不调用 Web/API 执行入口。原始模型输出、清洗后 recommendation、校验失败原因和 proposal_id 都进入 shadow 审计表；校验失败不会生成 proposal。

## 确定性研究

- `quant/factor/dsl.py`：从旧 AI 因子工厂迁出的纯受限 DSL 解释器。
- `quant/factor/dynamic_factor_loader.py`：只读取 `research:factor:approved`，且默认关闭；不读取旧 `ai:factor:approved`。
- 因子日程调用 `scripts/evaluate_factors.py --no-cache`。
- 策略周日程调用 `scripts/validate_strategy_portfolios.py --once`，旧 `scan_strategies.py` 不再是策略页权威来源。
- 研究结果始终保留 `research_only` 且不能自动晋升生产。F5 把“策略质量”和“模拟许可”分离：`validated_paper` 只接收 F4 candidate；`experimental_paper` 只接收 `f4_rejected` 且拒绝原因完全属于五项绩效门槛、约束违规为 0、未来数据违规为 0、代际和候选锁一致的组合。两者生成的本地 `paper_execution_authority` 都不回写研究产物，也不能外溢为实盘。
- 策略页通过 `/api/strategy` 的只读 `research_selection` 动作展示 `data/research/selections/latest.json`。页面把周频“F4/PIT 数据截止日”和日频“当前因子/选股日”分开显示；诊断组合始终注明“不构成交易信号”，不连接执行链。

## 启动与验证

```powershell
node scripts/start_services.mjs
python -m pytest -q
npm run test:contracts
npx tsc --noEmit
npm run build
```

Web：`http://127.0.0.1:8888`；API：`http://127.0.0.1:8880`。

F5 活动账本：`data/paper/f5_ledger.db`。政策：`config/f5_paper_execution.json`。安装任务前必须先完成全量回归；日频任务使用 `scripts/install_f5_paper_task.ps1`，盘中任务使用 `scripts/install_f5_intraday_task.ps1`。当前真实 F4 即使为 `f4_rejected`，只要属于允许的纯绩效失败且完整实验组合已绑定当前 research generation，活动验收可显示 `experimental_paper / unqualified` 并自动生成本地模拟订单；`f4_blocked`、数据/身份/约束/未来数据异常仍必须关闭。不得为演示修改 F4 事实或门槛。

2026-08-19 16:18 F5 交付验收：Windows 任务 `XuanJiQuant-Paper-Daily` 已安装并实际启动验证，动作仅为当前项目 `scripts/f5_paper_execution.py --once`，工作目录为当前项目，工作日 16:40、`IgnoreNew`、15 分钟重试 3 次、2 小时上限；手动安全检查退出码为 0。活动 API 返回 `paper_execution_capability=true`、当前 `paper_execution_authority=false`、`live_execution_authority=false` 和 `blocked_by_f4`：模块可用不等于本轮获准模拟。目标交易日 `20260820`，订单/成交均为 0；已授权的任意 `place_order` 仍以 HTTP 409 / `arbitrary_order_action_forbidden` 拒绝。浏览器实际页面显示同一准入原因、独立 100 万模拟现金与空仓，控制台无 warning/error。16:20 日终研究并发更新期间，`factor_evaluation_version_mismatch` / `factor_projection_version_mismatch` 现以 HTTP 200 的失败关闭业务状态呈现，不再冒充基础设施 500，也不会沿用旧因子。最终全量回归为 Python `1025 passed / 1 skipped`、Node `48/48`、Web `15/15`、UI `23/23`，TypeScript 与 Vite 构建通过。旧 `quant.db` 的 `execution:state` 值 SHA-256 仍为 `a7cc9ad7dff2d8a9d4955d4a3370e883df2162a23f8b7c2dc96a649aa088cf00`；该哈希只证明本轮 F5 验收未改写该历史状态值，不代表整个数据库没有其他合法数据更新。

历史快照（2026-08-20 10:45，已被下述盘中闭环取代）：完整 research generation `2f1b4e16412487670e10eb46` 已派生实验组合 `93f6f13b6cd7286b8d99e4855eff957795c817a316c382dac86e09b402a08731`，当时系统只有次日准备链，因此未倒填虚假记录。该事实保留用于解释为何后来新增独立盘中路径，不代表当前仍需等到次日。

2026-08-20 11:13 盘中闭环验收：`XuanJiQuant-Paper-Intraday` 已安装 45 个工作日触发点，并在 11:15 由 Windows Task Scheduler 自动运行成功（`LastTaskResult=0`）。系统用 `tdx_quant` 的 `20260820111317` 实时行情消费上述 20260819 完整组合，生成 5 个模拟订单和 5 笔模拟成交，其中 1 单全成、4 单部分成交后余量取消；独立账户形成 5 个持仓、现金 `453183.88`、权益 `999775.88`、模拟当日损益 `-224.12`，十项对账全部通过。再次运行返回同一 run 且 `idempotent=true`，没有重复订单或成交。驾驶舱和模拟执行页均显示盘中模式、行情时间及实盘权限未启用；浏览器控制台 warning/error 为 0。最终回归证据：Python `1151 passed / 1 skipped`、Node `48/48`、Web `18/18`、UI `23/23`、TypeScript 与 Vite 构建通过。

2026-08-20 日终调度修正：日频模拟准备由 16:40 调整为 17:10。原因是 16:20 启动的全市场刷新、因子评估和研究组合生成在真实运行中可能持续到 16:40 以后；旧顺序会让 F5 先读到上一完整研究代并以 `selection_stale` 受阻。新顺序固定为“研究完整代提交 -> 实验/正式组合发布 -> F5 日频准备”，受阻运行在四层健康度中按警告显示，不再冒充执行层健康。历史 16:40 验收记录保留为审计事实，不代表当前活动时钟。

完整交接边界见 [docs/XUANJI_HANDOFF.md](docs/XUANJI_HANDOFF.md)，当前流程图见 [docs/XUANJI_SYSTEM_WORKFLOW_MAP.md](docs/XUANJI_SYSTEM_WORKFLOW_MAP.md)。冻结备份 `C:\Users\HYSHEN\AlphaCouncil2-AI` 禁止运行、测试或修改。

## 2026-08-14 因子输入治理

因子层不再直接遍历可变的 `kline:*:d`。唯一入口是
`quant/factor/input_contract.py::load_factor_input_snapshot`，它绑定
`data:snapshot:a_share_daily:latest_passed`，并派生当前可评估股票池：

```text
daily_update.py
  -> DataSnapshot(latest_passed, coverage gate, content_hash)
  -> FactorInputSnapshot(snapshot_id + data_version + universe_version)
  -> data/research/daily/generations/<attempt>.staging
  -> factor_snapshot.pkl + factor_snapshot_latest.json + factor_evaluation.json + research_selection
  -> 三产物同身份/哈希/权限门禁
  -> data/research/daily/latest.json（单一原子完成指针）
  -> factor_runner.py（只接受完全相同的数据版本）
  -> validate_strategy_portfolios.py（F4 PIT/基准/样本外/组合门禁）
```

- 股票池规则为 `current_tradeable_v1`：排除 ST/退市状态、停留在快照日前的数据、历史不足及快照日零成交量。
- `governed_daily_bars` 会裁掉快照日之后的盘中/未来日线；`daily_update.py` 同时清理缓存中的此类条目，形成双重防线。
- 因子 pickle、轻量截面、IC 评估和研究组合先写入同一 attempt 暂存目录；三者身份、数量、日期、哈希和权限全部通过后才切换 `data/research/daily/latest.json`。刷新中继续读取上一完整 generation；坏指针或不完整 generation 失败关闭，固定文件仅是指针提交后的兼容镜像。
- 所有产物固定为 `promotion_state=research_only`、`execution_authority=false`；版本缺失或不一致时失败关闭。
- Windows 任务 `XuanJiQuant-Research-Daily` 在交易日 16:20 调用 `scripts/run_daily_research_pipeline.py --workers 8`，并以 `IgnoreNew` 禁止任务重叠；失败后按 15 分钟间隔最多重试 3 次。流水线先比较 `DataSnapshot.as_of` 与预期最新完整交易日；过期时运行全市场 `daily_update.py`，只有新快照通过质量、新鲜度和版本门禁后，才依次生成同版本因子和 `research_selection_daily` 研究组合。最终还要复核组合日期、快照 ID、数据哈希、非空持仓以及 `research_only` 权限；任一级不一致均失败关闭，不沿用旧结果。调度器每轮先回收“租约已过期且 owner PID 已消失”的孤儿任务，将其审计为 `interrupted/owner_lost`，经过 15 分钟安全退避后才允许用同一幂等键重试；活进程不会被回收。漏跑的因子任务在下一可用周期仍保持 due，由 `ResearchJobStore` 幂等键防止重复。
- `XuanJiQuant-Qlib-Weekly` 在周六 18:30 独立执行“六年 PIT 采集 → 质量门禁 → 同版本历史行业/沪深300参考 → Qlib 导出 → 训练 → 双引擎回测”，并独立记录模型、Recorder、回测和 Qlib 自身门禁。已完成但落后于最新日线的数据集是合法增量输入；内部周期以 `force=True` 支持安全跨日恢复。Qlib 股票池、行业参考和 F4 公共数据只接受 `manifest.completed_symbols`；目录残留只保留为审计事实。`XuanJiQuant-Strategy-Weekly` 在周日 10:00 独立运行 F4：调度器只要求哈希校验通过且与目标日/数据版本一致的每日完整因子 generation，F4 验证器再直接校验 PIT manifest、质量报告、历史行业和基准。策略任务不查询或要求本周 Qlib 周任务成功；Q1-Q4 依赖或训练失败只记为 `candidate_unavailable`，其他候选继续。每日研究和周六 Qlib 最长运行 4 小时；周日 v2 F4 上限为 12 小时。三类任务均为 `IgnoreNew`、`research_only`、`execution_authority=false`。

2026-08-31 调度新鲜度修正：PIT 采集截止日不再使用机器日历日 `date.today()`，只接受数据层已经通过质量与新鲜度门禁的最新完整交易日快照，避免周末生成伪市场日期。每日研究完整代提交后会附带轻量级 F4 readiness 检查；策略页分别展示“每日因子/选股日、PIT 数据可用日、最新完成 F4 证据日、当前重验准备状态”。当 PIT、质量、行业、基准和同日因子全部通过且最新 F4 证据落后时，Qlib 周期结束后使用与周日主任务相同的 ISO 周幂等键触发一次 F4 事件补跑；周日 10:00 主时钟继续保留，重复触发由 `ResearchJobStore` 拒绝。F4 仍是 `research_only`，不会因此获得交易或生产晋升权限。

2026-08-31 盘中全数据与全功能验收：日线/股票池入口核对 5203 只活动股票，5201 只已覆盖最新完整交易日 2026-08-28，2 只远端补取失败但整体覆盖率 99.9616% 通过；财务刷新真实执行 5203/5203、错误 0。修复 `daily_update.py --financial-only` 过去只设置跳过 K 线却未启用财务分支的问题，并用 CLI 行为测试锁定。日线刷新形成新快照 `a-share-daily-20260828-cc327bb7010a` 后，已立即运行同日确定性研究流水线并原子发布 generation `b8391e1c898878c661fdc29e`：58 因子、4996 只合格股票、10 只研究组合，四层数据版本一致。Jin10 上游 DNS 短暂不可达时，`status` 现返回 HTTP 200 的明确降级诊断（`healthy=false`），内容动作仍失败关闭；网络恢复后强制刷新得到快讯 20 条、新闻 14 条。验收为 Python `1442 passed / 2 skipped`、Node `51/51`、API `17/17`、全量 `42/42`、Web `19/19`、TypeScript/Vite 通过，10 个主页面和市场资讯 7 个子页浏览器交互无 warning/error。六年 PIT 仍是 2375/5435；盘中安全窗拒绝重任务是正确行为，已登记一次性 15:20 盘后续跑，不能把未完成清单写成成功。

2026-08-31 F5 模拟组合明细修复：账户数量、成本、现价、现金和权益继续只来自 `data/paper/f5_ledger.db`；`load_active_account_projection` 在只读投影阶段按“当前完整 research generation 的组合名称 → 因子截面名称 → 市场名称缓存”补充证券名称，不从旧 `execution:state` 或历史持仓快照回填。投影新增单票成本金额、市值、浮动盈亏、盈亏率、已实现盈亏、总盈亏、仓位占比和更新时间，并汇总账户持仓浮动盈亏/已实现盈亏。`f5_paper_runner.py` 的 account/all 动作已改为调用这一唯一入口，避免再次绕过名称补全。模拟组合页面同步展示当日/累计盈亏、累计收益率及完整持仓明细；实测 10/10 名称有效，浏览器 console warning/error 为 0，执行权限边界未改变。

同一 F5 账户投影已同步接入 `ExecutionPanel` 的“F5 确定性模拟执行”：运行状态、组合/验证身份、订单、成交和对账证据继续保留，账户摘要新增可用现金、持仓市值、当日/累计盈亏、累计收益率、持仓浮动盈亏和已实现盈亏；当前持仓表与模拟组合统一显示名称/代码、T+1 数量、成本/现价、成本金额、市值、浮动/已实现盈亏、盈亏率、仓位占比和更新时间。浏览器实测 10 行、10 个中文名称、订单/成交/对账区同时存在，console warning/error 为 0。

2026-08-31 盘后 PIT/Qlib 恢复：定位并修复两项导致周任务长期停滞的根因。`fetch_daily_history_tracks_batch` 在全市场大请求前新增 TdxQuant 短健康门禁，端口不可用时不再无心跳占用重任务锁；`qlib_job_worker._collect` 不再随运行日滚动六年起点，而从 symbol 级完整检查点取最晚稳定起点，使所有既有标的满足增量复用条件。相关 Qlib 数据源/采集/worker 回归 `69/69`。正式 weekly 周期随后完成 `daily-pit-2020-08-16-2026-08-31`：5435/5435 已处理、5414 完成、21 失败、manifest 覆盖 99.6136%，质量覆盖 99.3540%、最新日与预期日均为 2026-08-31，行业、沪深300基准、Qlib 导出、Recorder `855db93440564b5a8d75b881508ea96d`、官方回测和独立A股回测均完成。Qlib 自身门禁为 rejected，只隔离 Qlib 候选。F4 同周补偿任务随后正常完成，终态与 F5 重绑定证据见下文。

F5 执行证据名称补全：`active_account_projection` 现对 positions、orders 和 trades 使用同一只读证券名称解析器；`ExecutionPanel` 的本轮订单与成交表优先消费 `accountProjection.orders/trades`，不再使用缺少名称的原始列表。订单和成交均显示“股票名称 / 代码”，订单方向/委托/成交/取消/价格/状态/原因/时间以及成交ID/数量/手续费/入账结果和 reconciliation 保持不变。实测账户投影131条订单、76条成交名称缺失均为0；当前最新运行13条订单全部显示中文名称，因本轮尚无成交，成交表正确显示0笔而不伪造记录。

2026-09-01 02:58 全功能终态验收：F4 W36 job 17 已成功结束并发布验证 `c27ca9cd7109bf45a5e9701a64336d03e10c58bb65ba6137b83a758a7b860137`，市场日 2026-08-31、factory run `fafc4f7561d779be7853a7914721835b0f92cfebf474a929ed542f182f663f9f`，8 项不可变产物哈希与公共 PIT/质量/行业/基准/F3 输入全部通过完整性校验。结论是 `f4_rejected` 的真实绩效不达标：费后超额 -50.10%、双倍成本超额 -63.79%、Sharpe -0.0500、最大回撤 -32.04%、正超额窗口 20%，约束与未来数据违规均为 0；它不是数据或基础设施故障。修复了 F4 发布后实验组合仍绑定旧 validation 的断点：策略调度成功发布纯绩效拒绝结论后，确定性重建并绑定当前完整 generation 的实验选择，组合 `b60166954bc1225c11d65d5eceb0318ce20a7c8c8860f9f8b1215a977ead32c6` 已绑定上述新 validation，F5 当前准入为 `experimental_paper / unqualified`，休市时只显示 `outside_intraday_window`，不再误报 `validation_identity_mismatch`。最终回归为 Python `1447 passed / 2 skipped`、Node `51/51`、API `17/17`、功能验证 `42/42`、Web `19/19`、UI `23/23`，TypeScript、Vite 构建通过；浏览器策略页与 F5 页面身份一致、持仓/订单名称完整，console warning/error 为 0。

2026-09-01 20:00 准实时数据与驾驶舱改造：`config/data_sync_policy.json` 是20个数据域的唯一同步频率权威，Python `quant/data/sync_policy.py`、Node `server/sync-policy.mjs` 和前端 `lib/data-sync-policy.ts` 必须共同消费它；实时类、资讯类和日/周研究类按事实产生频率分层，页面不得私自提高上游抓取频率。`data_runner.py::hot_snapshot` 以快照哈希、逐证券行情时间、来源、age/stale 和市场阶段发布可信热行情；`MarketStreamService` 用独立 hot/full runner 合并所有客户端与F5持仓订阅，通过本机只读 SSE 推送 `hot_quotes/market_top100/cockpit_mark`，连接数增加不会复制上游请求。Top100只切换覆盖率通过的完整代，完成态不再永久显示 `refreshing=true`。浏览器使用共享 `useMarketStream`，市场浏览/实时行情/驾驶舱已移除15秒/5秒主轮询，仅保留首屏REST与断流30秒后的有界降级；价格行按变化更新，页面隐藏自动降频。

同轮 F5 在唯一 `data/paper/f5_ledger.db` 新增 `paper_live_marks` 与 `paper_live_account`，固定无业务参数 `mark_to_market` 只读取服务端可信热快照，以事务更新当前价格、权益、今日盈亏和估值时间；订单、成交、现金、数量、平均成本、策略证据和执行权限不可改变，同快照幂等，历史权益最多30秒追加一次。风险输出绑定同一 `market_snapshot_id`，驾驶舱慢系统健康/情绪/研究组合移出关键路径，并分别显示行情、权益估值、风险计算时间和实时/延迟/休市/降级状态。10客户端实测：16只持仓热行情p95 `1039ms`、驾驶舱估值p95 `1462ms`、暖态驾驶舱p95 `6ms`、上游调用倍数 `1.0`，每客户端12秒内收到12个热行情、12个权益和1个完整Top100代，执行事实哈希零变化。浏览器实测时间连续推进且console warning/error为0。最终验证：Python `1442 passed / 4 skipped`、Node `57/57`、API `17/17`、full `42/42`、Web `19/19`、UI `23/23`，TypeScript与Vite通过。系统Python缺少可选MLflow时对应集成测试跳过；同一测试在 `.venv-qlib` 中通过。Pandas日期序列固定转为 `datetime64[ns]`，避免新版本把微秒整数误解为1970年纳秒。

财务手动更新的生命周期不再隶属于 Web/API 进程。`server/update_manager.mjs` 对 financial 模式使用隐藏、detached 的 `daily_update.py --financial --financial-only`，stdout/stderr 固定写入 `logs/financial-update-out.log` 与 `logs/financial-update-err.log`，进度权威为原子文件 `data/financial_update_progress.json`。后端重启后按持久化 PID 加 checkpoint 重新投影 `running/completed/completed_with_errors/interrupted`，不能仅因 Node 内存中的 `updateProc` 消失就报 `orphaned update process`；重启后的“停止更新”也必须向已接管PID发送终止并把checkpoint落为 interrupted。2026-09-01 实测原任务在3/5203时被旧后端树终止，修复后复用3只断点并启动PID 37992；连续两次后端重启均未杀死任务，新后端先接管10/5203、后推进到90/5203，成功90、失败0、last_error为空。该任务仍在后台执行，不能把中间进度写成已完成。

2026-09-02 盘中自动模拟巡检：Windows `Paper-Intraday` 任务按5分钟时钟返回0不等于已经成交。现场发现09:35至11:25没有形成当日盘中run；第一根因是TdxQuant不可用时新浪只返回 `HH:MM:SS`，F5正确以 `intraday_quote_timestamp_invalid` 拒绝。统一行情入口现在只对刚同步取得的时分秒绑定当前交易日，生成14位 `timestamp`，完整供应商时间保持不改，F5的同日/120秒门禁未放宽。第二根因是16只旧持仓切换10只目标需要26张订单，超过每轮20张硬上限；planner不再整轮阻断，而是按“卖出优先、单轮最多20张、显式记录总计划/递延订单数”形成受控部分再平衡，硬上限保持20，执行策略身份升级为 `f5-paper-policy-v2-staged-rebalance`，旧v1 blocked记录继续保留审计。热行情在来源超时时采用2/5/10秒退避和15秒进程保护，行情stale阈值仍为3秒；午间接受当日11:30终点价做估值但页面必须显示休市。11:41证据为F5 enabled、kill switch false、paper ready true、窗口因午休关闭、下一计划13:05:05、估值绑定11:30行情、今日盈亏-4363；下午真实订单/成交/对账尚未发生，不得提前宣称闭环成功。修复后新鲜回归为 Python `1445 passed / 4 skipped`、Node `57/57`、API `17/17`、全功能 `42/42`、Web `19/19`、TypeScript 与 Vite 构建通过；UI 功能项 `23/23`，但因子元数据、IC 与批量 IC 仍出现约 6.1 秒、6.6 秒和 22.0 秒的计算型慢响应，性能验证因此返回告警而非全绿。

2026-09-02 下午多批次闭环：13:05 的 v2 batch 0 真实完成20张订单/20笔成交；现场继续监控发现原幂等键会让递延订单永远无法进入下一周期，因此 F5 账本升级为 schema v6，在同一 `portfolio + session + policy` 下增加不可变 `batch_index`，单批仍限制20单，已完成批次绝不重放，未完成差额可由下一合法时钟继续。14:25 batch 1 为9单/8成交/1涨停拒单，14:30 batch 2 为4单/3成交/1涨停拒单，逐批十项对账均10/10通过。后续又发现若每批按新价格重算目标股数会产生100股级来回微调；现以同一交易日每只股票第一次出现的 `target_qty` 冻结目标，后续价格只用于成交和估值，不重新定义目标。活动账户投影同时要求实时估值的 `run_id` 必须等于最新权益批次，否则忽略旧 live mark，避免驾驶舱/F5与风险页混用不同批次；跨页面权益和持仓重新恢复一致。涨跌停拒单保持终态审计，可在下一合法行情周期重试，但不得触发系统级熔断或绕过市场限制。

当日最终盘中事实：batch 0-5 共形成46张模拟订单、40笔成交，6个批次均为可验证终态且每批十项对账10/10通过；14:45最后实际执行批次只校正冻结目标差额并保留两张涨停拒单。14:50入口在收盘安全边界正常退出且未重复写单，下一触发点为下一交易日09:35。当前9只持仓，003039尚差800股、600830尚差9700股，原因均为`buy_limit_up`；这两个缺口不得冒充成交或系统失败。最终回归为 Python `1448 passed / 4 skipped`、Node `57/57`、API `17/17`、全功能 `42/42`、Web `19/19`、TypeScript与Vite构建通过；14:51跨页面权益统一为`1043428.34`、持仓统一为9只，14:56最新估值随行情更新为`1043042.34`。并发全量验证期间后端stderr保留8条risk runner退出告警；随后8次连续风险请求全部成功（约0.38-2.94秒），日志新增0字节、API未中断，因此不能写成“stderr为空”，也不能把历史告警冒充当前故障。

2026-09-03 盘中复核：09:35 batch 0 自动形成19单/19成交，09:40 batch 1 自动形成1单/1成交；20/20对账通过，10:40及10:45后续周期均未创建新batch，证明目标已收敛且幂等生效。10:45唯一账户为10只持仓、现金`59171.33`、权益`1047982.33`，四页面账本一致，实盘权限继续false。发现`market-stream-risk`在09:30和09:32退出：根因是1秒行情快照每次都同步触发风险重算，违反`cockpit_risk`的2秒权威频率，且5秒进程保护在负载波动时过紧。`MarketStreamService`现按同步政策节流风险计算到2秒，进程保护放宽到至少12秒；风险失败只保留上次可信风险并暴露`last_risk_error`，不得反向污染行情热流。重载后218次行情/估值仅触发73次风险计算，Web/API/构建并发压力下stderr保持0、hot failure为0。验证为Node契约`57/57`、Web`19/19`、API`17/17`、TypeScript和Vite通过。

2026-09-04 收盘巡检：`Paper-Intraday` 09:35完成policy v2盘中批次20单/20成交、10/10对账，后续周期保持幂等；17:10日频备用run仍为prepared，等待日频入口按同日盘中完成事实作废，不能计入盘中订单或失败。15:10发现8880/8888均未监听，PID文件仍指向已消失的44232/31248，后端最后业务日志停在14:41且没有uncaught/关闭栈，因此定性为宿主或外部进程终止，不是F5账本、计划任务或交易失败。使用唯一幂等入口`node scripts/start_services.mjs`恢复为backend 20484/frontend 39748；Web`19/19`、API`17/17`、Node`57/57`通过，四页面权益`1048503.71`、持仓10只一致。新增当前对话工作日盘中巡检，只在9/10/11/13/14时段每5分钟核对F5账本、任务、端口和日志；端口丢失且PID确认消失时允许用同一入口恢复，仍禁止实盘和任意订单。

2026-09-07 盘中恢复：计划任务09:35至13:55返回0但盘中账本没有policy v2 run，当前准入为`f4_evidence_missing`；根因是周五日频完整代`a54ef97fb43b659eb68a0113`和9月4日实验组合已发布，但周日F4尝试因`f3_pit_date_mismatch`写入新的`f4_blocked`兼容投影，运行时错误地让这个失败尝试覆盖了实验组合明确绑定的上一份已提交F4工厂。`runtime._f4_evidence`现先解析最新有效投影；失败时只允许当前完整generation内的实验组合按`validation_id + factory_run_id`解析不可变验证目录，逐文件校验artifact SHA-256、研究权限、候选工厂指针和14天F4新鲜度，篡改、过期或身份漂移继续失败关闭。14:10计划任务自动恢复batch 0；随后修复跨交易日T+1可卖量在规划后才重置的问题，首批规划前把上一交易日持仓恢复为可卖，避免短暂11只超出10只目标。14:15 batch 1为18单/17成交，603668因涨停拒单；14:20及以后只重试603668，不重复其他成交，逐批10/10对账通过。

同轮恢复实时估值：新浪降级源同一批证券时间天然相差2-8秒，原3秒热行情门槛使F5`mark_to_market`连续返回`market_snapshot_stale`。热行情展示继续保持3秒门槛；`cockpit_account`独立估值可信窗口调整为15秒，快照同时发布`stale`与`valuation_stale`，F5只消费后者，非当日、缺价、未来时间和超过15秒仍关闭。实机重载后`last_marked_snapshot`开始随行情推进，账户时间更新到14:30。最终验证为Python`1452 passed / 4 skipped`、Node`57/57`、API`17/17`、全功能`42/42`、Web`19/19`、TypeScript/Vite通过；Web跨不同1秒快照时要求同一F5权威和持仓一致、权益相对差异小于0.1%，同一snapshot仍要求分毫一致，禁止把正常市值变动误报成双账本。

2026-09-08 服务与数据巡检：09:35 F5 policy v2自动完成7单/7成交，后续一批2单/2成交，累计9单/9成交、20/20对账，10只持仓；实盘权限false。权威数据API的日线最新日期为`20260907`且5203/5203覆盖，页面曾显示`20260903`是Web/API进程死亡后的旧状态。连续三次发现脱离终端的Node服务在无崩溃栈时消失后，废弃“短任务生成脱离子进程”的假守护方案，改为`XuanJiQuant-API-Service`和`XuanJiQuant-Web-Service`两个任务直接长期托管隐藏服务宿主，`XuanJiQuant-Service-Supervisor`每5分钟只检查任务状态并重新启动停止的宿主。真实验收中API PID 39508被终止后，Supervisor恢复为40628；三任务均不引用F5入口、不具备交易权限。Node契约增至`58/58`，Web`19/19`、API`17/17`、TypeScript/Vite通过。

同日财务失败恢复：历史全量任务真实结果为4081成功/1122失败，原始checkpoint已归档到`data/audit/financial-updates/financial_update_progress-20260902-completed_with_errors.json`。重试池通过“当前5203股票池减去4081 completed_codes”重建为完整1122只，不能使用仅保留末尾100项的`failed_codes`字段。09:51启动PID 39988、4线程定向重试，已成功的4081只不重复抓取；10:39:17终态为completed，1122/1122成功、失败0、failed_codes=0。抽查000592、002693、688372财务API均返回数据，financial statements契约通过；因此原5203只已形成4081+1122的完整成功闭环，但两次运行记录继续分开保留审计。

上述财务任务随后于2026-09-02 09:56:42真实结束：5203/5203已处理，4081成功、1122失败，checkpoint=`completed_with_errors`、stderr为空。该结果证明独立进程跨后端重启完成，不是orphan；1122个失败代码继续保留在checkpoint，不能把“处理完成”写成“全部成功”。

2026-09-10 全功能闭环巡检：09:07 初始运行事实为 Web/API 在线但 `Research-Daily=0x40010004`、实验选股停在 `20260904`、F5 明日批次 `f4_evidence_missing`、`20260909` 日线仅覆盖 3933/5205。根因是 20260908 完整研究 generation 已原子提交，但 `generate_experimental_portfolio.py` 仍直接消费最新 `f4_blocked` 兼容投影；现在与每日研究生成器共用 `_load_reusable_f4_evidence`，只允许在 14 天策略证据 TTL 内复用实验组合已绑定的不可变 `validation_id + factory_run_id`。缺少旧实验组合或验证报告时返回当前阻断，不再抛出输入缺失异常。恢复产物为 selection `20260908`、generation `3221a53bdf326f1cddb338f9`、10 只股票、F4 validation `c27ca9cd...`，权限保持 `research_only / execution_authority=false`。

同轮 F5 于 09:35 自然触发 batch 0，形成20单/20成交，其中000929明确终态为7450已成交、2550已取消；09:40 batch 1只处理剩余2550股，累计21单/21成交、20/20对账，持仓收敛为10只，账本`quick_check=ok`，实盘权限始终false。数据控制面随后以单一任务补齐1258只日线、3944只跳过、1个非致命抓取错误，发布 `a-share-daily-20260909-1affbd5605fc`，覆盖5191/5203（99.7694%）。`strategy_runner.py` 现在把合法的 `f4_blocked` v2预检投影作为HTTP 200业务状态展示，仍拒绝越权和损坏证据；研究选股同时比较系统预期交易日，不能再把完成但落后的generation标为current。

驾驶舱一致性改为：同一snapshot继续严格一致；行情移动导致snapshot不同，只在同一F5账本、相同持仓数量、估值时间差不超过15秒且权益差不超过0.1%时接受风险，否则仍显示不一致。目标组合指针由24小时检查改为每30秒检查，但研究计算频率不变；因子页、策略页和驾驶舱均明确标注落后研究日期。`Research-Daily`保留16:20主触发并新增20:30幂等恢复触发，允许电池状态运行，仍为`IgnoreNew`和4小时上限。验收：Python`1458 passed / 4 skipped`、Node契约`58/58`、Web`19/19`、UI功能`23/23`且浏览器报错0、TypeScript和Vite通过；系统健康接口约3.6–7.1秒，属于已披露的只读聚合性能告警。Qlib隔离环境和六年质量门禁可用，但2026-09-05独立周任务因TdxQuant本地HTTP与BaoStock网络失败返回1，未在盘中擅自重跑重研究任务。

当前活动实现是 **F4 多 Alpha 候选工厂 v2**（`f4-multi-alpha-candidate-factory-v2`）。F0=原始数据接入，F1=质量门禁，F2=固定因子计算，F3=可复现股票池/IC/IR/成本与相关性评估，F4=走样本外和组合级策略验证。工厂只接受 24 个预登记候选，六个候选族各 4 个：动量、反转、防御、流动性、规则组合和 Qlib；规则候选使用不可变 Alpha 规格，Qlib 候选使用窗口独立 Dataset、Recorder、模型和预测产物，失败不得回退为同名规则。组合政策固定 Top10、总敞口不高于 95%、单票不高于 9.5%、行业不高于 25%、ADV 参与率不高于 10%。F4 仍执行 504/126/126 交易日、purge 20、embargo 5；每个窗口按 `train 拟合 -> validation 比较 24 候选 -> 原子锁定 winner -> test`，只有窗口锁定胜者可以读取 test，非胜者不得产生 test 证据。

v2 模块分工为：`f4_alpha_contracts.py` 管不可变 Alpha/候选身份；`f4_alpha_rules.py` 管规则派生、截面预处理与训练段拟合；`f4_qlib_adapter.py` 管窗口隔离的 Qlib 训练/预测；`f4_candidate_factory.py` 与 `f4_real_pipeline.py` 管候选不可用隔离、validation 榜单、持久锁和 winner-only test；`f4_v2_publication.py` 在十件产物全部通过身份、哈希、有限值与权限校验后，原子发布到 `data/research/f4/factory-v2/<factory_run_id>/` 并切换权威指针。F4 v4 的八项门槛和数值均未改变；候选耗尽仍是合法的 `f4_rejected_exhausted` 研究结论，不得事后改公式或放宽门槛。

F4 winner 通过 `factory_version + factory_run_id + candidate_id + alpha_spec_hash + alpha_fit_hash + 可选 model_artifact_hash + lock_hash + policy_hash` 贯穿研究组合和 F5 门禁。v1/v2 读取必须显式分支；三处版本、策略或锁任一缺失/漂移都失败关闭。所有 v2 产物固定 `promotion_state=research_only`、`execution_authority=false`，不自动授予模拟或实盘权限。

自适应市场状态模型是独立研究输入，不参与放宽 F4 门禁。`scripts/adaptive_regime.py` 从可配置活动 Qlib 数据根读取六年数据，但模型固定发布到项目内 `data/qlib/models/regime/`；`quant/qlib/regime_model.py` 采用 `staging -> generations/<generation_id> -> 兼容镜像 -> regime-latest.json 指针` 的顺序。读取端只认指针指向的不可变代际，并在反序列化前校验元数据自哈希与模型文件哈希。

2026-08-22 22:06 的真实 v2 六年重跑已完成。权威 factory run 为 `f8bd58748ff64ec442cf6a29446acf64fec1ae29d4ebe42110b3bd311f62c3be`，代码身份 manifest 为 `c90da61ce68066c1e3021e9d82df71791fa096b647182dd250f18f8bd802ec96`；输入绑定 `daily-pit-2020-08-07-2026-08-21`、行业 `cninfo-008002-b092a1797ca95fba`、基准 `000300-3456c358743fd3c3`。运行耗时 29,605.57 秒，exact-10 产物、5 把唯一窗口锁和 20 个独立 Qlib Recorder 均验证完整，20 个 Recorder 全部为 `FINISHED`。六族 24 个候选全部可用；Qlib 胜出 4 个窗口（Q3、Q4、Q3、Q2），防御 D4 胜出 1 个窗口。最终是 `f4_rejected_exhausted` 而非数据阻断：正超额窗口比例 40%，1.0 倍成本费后超额 -7.9381%，Sharpe -0.6218，最大回撤 -32.0092%，2.0 倍成本超额 -19.8710%，约束违规与未来数据违规均为 0。五项绩效门槛未通过，禁止晋升为 F4 合格策略；门槛没有放宽。

同轮修复了兼容证据恢复缺陷：旧 `f4_blocked/candidate_score_contract_invalid` 不可变目录仍作为审计事实保留；成功重算结果写入 `data/research/f4/recoveries/<validation_id>/<recovery_id>/`，再由 `data/research/f4/latest.json` 原子指向恢复证据。兼容投影的 `factory_version` 和六族 `family_diagnostics` 必须从已完成哈希校验的 v2 权威代际补入，`strategy_runner.py` 继续严格校验，禁止通过放宽接口门禁掩盖镜像缺字段。页面当前应显示 `f4_rejected_exhausted`，不能再把旧阻断冒充当前状态。巨潮 PDF 正文解析依赖 `pypdf==6.14.2`，普通环境和隔离 Qlib 环境的依赖清单均已登记。下方 2026-08-18 至 2026-08-20 的六候选结果均为 v1 历史审计事实。

2026-08-26 全功能巡检修复了 v2 周期的三个交付断点。`research_training_scheduler.py` 现在用 `--lane daily|qlib|strategy` 隔离日频、周六 Qlib 和周日 F4 任务；Qlib 的 `market_date` 读取质量报告中的实际最后交易日，不再把周六采集日期冒充交易日。日频研究选股通过严格 `factory-v2/latest.json` 解析胜者、锁和模型证据，并从哈希一致的规则 `alpha-fit.json` 恢复信号；带正负号的信号复用 F4 的 5-MAD、行业去均值和行业内排名语义。实验模拟组合只消费完整 research generation 已发布的 `selection.json`，不再从旧 v1 目录重算。当前完整日频代为 `817ab83fe8c3740789093130`，日期 `20260825`，58 个因子、4969 只可评估股票、10 只 v2 研究组合；F5 对 v2 使用候选锁内的 canonical policy hash，不再把外层 v1 封装名当成胜者政策。F5 `status` 同时返回当前只读准入和历史账本尾部，午间/休市时不得把旧阻断冒充当前原因；候选热路径只校验 pointer、factory report/pipeline hash 和模型清单哈希，完整 exact-10 继续留在发布/离线审计门禁。驾驶舱通过只读 `research_selection` 投影展示“研究目标组合”的代码、中文名称、目标权重和研究理由，并明确不构成订单。

同日 13:05 的盘中计划任务实际完成当前研究代的实验模拟：运行 `paper_run_record_39ac0f59342024d01da8952c2b2cb44d72ebaed707361a7825d3409c56f4bcb4` 生成 12 张模拟订单和 12 笔成交，账本当前累计 40/40 项对账通过，实盘权限仍为 false。四层健康投影不得在同一交易时段已有当前完成运行时误报 `paper_execution_cycle_pending`；休市后的 `outside_intraday_window` 只描述下一轮调度窗口，不否定当天已完成的模拟运行。系统诊断的 readiness、历史原因和休市原因必须通过 `lib/workbench-state.mjs` 中文结构化展示，不得输出 `[object Object]` 或裸英文 reason code。

2026-08-26 统一活动账本验收：驾驶舱、兼容 `/api/execution`、组合风险和 `/api/paper-execution account` 同时返回权益 `1023672.01`、10 个持仓和 `ledger_authority=f5`；驾驶舱与模拟组合同时显示当日盈亏 `17469.87`。告警、tick 订阅、同步服务和日报均调用 `load_active_account_projection`，不再从 `execution:state` 推导当前账户。旧缓存与历史快照未迁移或改写。验收为 Python `1424 passed / 2 skipped`、Node `51/51`、API `17/17`、全量功能 `42/42`、Web `19/19`、UI `23/23`，TypeScript、Vite 和浏览器控制台检查通过。

同日晚间复巡修复了模拟组合状态覆盖缺陷：`PaperPanel` 同时读取 F5 runtime status 与 account projection 时，必须先展开账户投影、最后写入 runtime `status`，防止账户兼容字段覆盖当前准入状态。页面现与模拟执行一致显示“实验模拟自动交易 / 策略质量未通过F4 / 模拟许可已授权 / 盘中窗口外”；权益仍来自同一 F5 账本。`paper_ledger_ui_contract_tests.mjs` 固化了对象合并顺序。

2026-08-27 盘中自动模拟闭环修复：TdxQuant 实时快照的 `volume` 单位为“手”，而 F5 参与率与容量模型使用“股”。旧实现直接传入导致容量少算 100 倍，表现为准备单存在但买单容量为 0 或仅极小部分成交。`normalize_intraday_quotes` 现在依据 `volume_unit=hand/lot` 转为股并记录 `source_volume_unit`，其他已为股的数据源保持原值。09:35 计划任务自动消费 20260826 同代组合，行情事实 `20260827093505`，运行 `paper_run_record_63ace902e8138d8cc5b0c7b890867234802e795bb4e7663c0b88e1c6b02a5d53` 完成 13 张订单、13 笔成交，11 单全成、2 单部分成交后余量取消，十项对账 10/10 通过；实盘权限仍为 false。

同日成交/持仓可见性修复：F5 API 原有 13 笔成交和 12 个持仓，但 `ExecutionPanel` 曾把 58 条累计订单按最旧优先展示，今天记录被压在长表底部，持仓又仅在模拟组合页。执行页现在以 latest run 为默认上下文，首屏显示本轮状态、13 单、13 成交、12 持仓和当前权益；当前持仓管理（只读）位于订单/成交表之前，本轮订单、成交和十项对账只过滤当前 `run_id`，历史总数仅作摘要，不再遮蔽当前事实。

2026-08-28 订单顺序修复：策略规划器一直产生“卖出优先、买入随后”的订单列表，但 `paper_orders` 没有序号，账本按同秒 `created_at + 哈希 order_id` 读取，可能把买单排到卖单前。当天运行因此出现一笔 `cash_insufficient`，即使同轮存在足以释放现金的卖单。F5 schema v4 为订单增加 `sequence_no`，写入时保存规划顺序，结算时按 `created_at + sequence_no + order_id` 读取。当天拒单保留为审计事实；后续运行严格保持卖出优先。

2026-08-30 Qlib/F4/F5 责任解耦验收：`strategy_weekly` 调度层已删除 `qlib_sync_complete`、Qlib 市场日、同周 Qlib 成功 job 和 Qlib 输出版本前置，只保留每日完整因子 generation 的哈希、权限、日期与版本校验；`validate_strategy_portfolios.py` 继续直接验证 PIT manifest、质量报告、历史行业和基准。Q1-Q4 的依赖、训练或预测失败仍只形成 `candidate_unavailable`，其他候选继续；F5 继续只读取已发布 F4/selection 与 F5 政策、风险、行情和唯一活动账本。活动 Qlib 恢复进程在 2375/5435 后 owner PID 消失，Qlib job 与研究 job 已如实恢复为 `interrupted/owner_lost`，未写成成功，也不再作为 F4 总开关。当前 F4 历史发布仍为 `f4_rejected / positive_excess_window_ratio_below_0_60`，未因代码改动伪造新结论。验收：Python `1434 passed / 2 skipped`、Node `51/51`、API `17/17`、全量功能 `42/42`、Web `19/19`、UI `23/23`、浏览器 `10/10` 且 console/page error 为 0，TypeScript 与 Vite 通过。

六年 PIT 与 F4 参考数据的权威链路为：

```text
TdxQuant 近期行情 + AkShare/BaoStock 历史补段 + 交易所股票主数据
  -> quant/qlib/collector.py（可续跑、逐标的哈希）
  -> data/qlib/datasets/a_share_6y_daily/manifest.json
  -> quant/qlib/quality_gate.py + quality_report.json
  -> scripts/build_f4_market_references.py
  -> data/research/industry/pit_industry.json + data/research/benchmarks/000300.json
  -> quant/qlib/exporter.py（completed_symbols 进入 market；沪深300只注册到 provider/all 作基准）
  -> data/qlib/qlib_bin/a_share_6y_daily
  -> validate_strategy_portfolios.py（四输入版本/哈希绑定）
```

2026-08-20 四层健康与 Qlib 修复：`/api/risk system_health` 不再读取旧 `factor:*` 键或 `execution:state`，而是分别读取全市场日线覆盖、经哈希/身份校验的完整 research generation、F4 latest/每日 selection 和独立 F5 账本。`f4_rejected*` 表示研究候选未通过绩效门禁，健康状态为警告而不是基础设施故障；缺失、跨代、权限越界、数据过期或对账失败才是错误。沪深 300 在 Qlib 中同时写入 `instruments/all.txt` 供 benchmark provider 解析，并从 `instruments/market.txt` 的训练/交易股票池排除。基准参考使用 AkShare 历史与本机 TdxQuant 增量合并，当前 1465/1465、截至 2026-08-19、缺失 0；来源和回退状态写入产物，不冒充单一新抓取。

2026-08-17 21:42 真实快照：PIT 版本 `daily-pit-2020-08-01-2026-08-14`，5425/5425 标的采集闭合、1464 个交易日，质量报告 `quality_89583d26ec22b5b25bed` 已通过；生命周期样本覆盖率 98.428%，最近应交易标的覆盖率 99.942%，重复行、非法 OHLC、非正复权因子均为 0。Qlib 二进制包含 5425 个标的和 86800 个特征文件。行业版本 `cninfo-008002-97085abce2eeb77f` 的有效日期样本覆盖率为 96.967%；基准版本 `000300-eadcbd32c1c07c91` 覆盖 1464/1464。基准远端重建失败时使用同日已抓取 bars 做当前交易日历重校验，产物明确保留 `source_fetch_status=cache_revalidated`、原抓取时间和错误，不冒充新抓取。

2026-08-18 11:18 真实 F4 闭环已完成：`f4-gate-v4` 在 7,095,568 行、5425 标的、47 个严格日线因子的 PIT 面板上生成 6 个完整 walk-forward 窗口；全部窗口的历史行业覆盖率为 97.64%–99.68%，目标组合约束违规和未来数据违规均为 0。最终状态为 `f4_rejected`，不是数据阻断：2/6 窗口费后超额为正，聚合费后超额 -80.04%，中位 Sharpe -0.257，最差窗口回撤 -55.61%，双倍成本超额 -90.95%，未通过 5 项绩效门槛。validation ID 为 `65c264ce8f7c6af48e2b6410622c9491dffeb3f1a5509c4e90c23f6db373eeaa`；结论只表示预声明候选在该历史方案下不可晋级，不能解释为数据或系统失败。

2026-08-20 01:11 修复前历史快照（已被上方 Qlib provider 修复取代）：六年 PIT 版本为 `daily-pit-2020-08-05-2026-08-19`，完成清单 5426 只；原始目录多出的退市历史文件 `SZ300028.json` 保留但已从行业参考、Qlib 股票池和 F4 面板全部排除。当时 Qlib 日历 1465 日、股票池 5426 只，`SH000300` 有基准特征但尚未进入 `all.txt`，这正是后续 benchmark 失败的根因；行业 `cninfo-008002-b092a1797ca95fba` 覆盖率 96.983%，5426/5426 验证至 2026-08-19；基准当时覆盖 1462/1465（99.795%）。该段只保留故障演进证据，不代表当前 provider 规则。

同一数据版本的当前 F4 validation ID 为 `5bd6ed52437f6042711ea55854b98cbf1ef83d8596fe35f5c85dcc46d132cc58`，pipeline `f4-real-pipeline-v3-nested-candidates-gross-clamp`，factory run `84d991755b20cdb1b18d1ef28d3a56433058590e596d2350d0589e8566c1d676`。5 个外层窗口均在 test 前形成稳定 winner 锁；正超额窗口比例 20%、费后超额 -74.37%、Sharpe 0.0136、最大回撤 -45.54%、双倍成本超额 -79.11%，约束违规与未来数据违规均为 0。v3 将二进制浮点累加产生的超敞口尾差确定性吸收到最后一只持仓，并以新 pipeline 身份重跑，未复用 v2 证据。六候选耗尽后状态为 `f4_rejected_exhausted`，未放宽阈值；该纯绩效失败可进入 `experimental_paper / unqualified` 本地模拟，不能晋升为 F4 合格策略或实盘权限。

2026-08-20 修复前历史回归：主 Python `1109 passed / 1 skipped`；Qlib/F4/F5 聚焦回归通过；Node 契约 `48/48`、Web `15/15`、UI `23/23`、TypeScript 与 Vite 构建通过。当时 F5 仍为 `blocked_by_f4`；该记录已被当前实验模拟闭环取代。

2026-08-20 17:24 当前四层验收：数据层 5201/5205（99.9232%）且截止 20260820；因子层完整代 `cba7d15f62bb96d3a3a3f2b1`、58 个已登记因子、4990 只可评估股票、覆盖率 99.9616%；策略层当日 5 只组合身份和新鲜度有效，但真实 F4 为 `f4_rejected`，因此健康度为业务警告且策略质量保持 `unqualified`；执行层已通过 `experimental_paper` 为 20260821 准备 4 笔模拟订单，状态 `prepared`、实盘权限 false。日频任务 17:10 自动运行结果 0。健康接口对全市场日线只读取每条序列的有界尾部，热请求由约 5.1 秒降至约 1.5 秒。最终回归：Python `1158 passed / 1 skipped`、Node 契约 `50/50`、Web `18/18`、UI `23/23`、TypeScript 与 Vite 构建通过，浏览器控制台/page error 为 0。

权威链路为 `ResearchTrainingScheduler -> validate_strategy_portfolios.py -> f4_real_pipeline.py -> data/research/f4/cache/<panel_id> -> data/research/f4/<validation_id>/九份不可变证据 -> data/research/f4/latest.json -> strategy_runner.py::market_scan -> StrategyPanel`。完整报告保留逐窗权益曲线和压力明细；`latest.json` 是 17KB 轻量只读投影，不复制重型曲线。2026-08-18 实测 API 冷请求 155ms、热请求 21ms/11ms。页面和 API 均不会产生订单、目标持仓或执行授权。

2026-08-21 09:35 盘中自动模拟验收：驾驶舱不再把“最近一次仍是日频准备态”误判为盘中模拟未启用；只要 F5 已启用、未熔断、最新运行属于 `experimental_paper/validated_paper` 且模拟许可有效，就显示“盘中自动模拟交易已启用”。Windows 任务 `XuanJiQuant-Paper-Intraday` 自动返回 0，使用 `tdx_quant / 20260821093504` 行情完成 run `paper_run_record_dd8eacf7543511c00ed29807393a44c9a7521fa6a1cf0079e3c9294e944b38c1`：4 张订单、4 笔部分成交、剩余数量全部取消、十项对账 10/10；09:40 再次由计划任务触发仍返回 0，同一幂等身份只有 1 个 run，订单/成交继续保持 4/4。为防止 17:10 日频备用单重复成交，`PaperExecutionService.run_due()` 会在同组合、同交易日已有盘中完成终态时把旧准备单安全落为 `blocked/superseded_by_intraday`；不会再次撮合。F4 仍为 `f4_rejected_exhausted / unqualified`，`live_execution_authority=false`。本轮回归为 Python `1160 passed / 1 skipped`、Node `50/50`、Web `18/18`、UI `23/23`，TypeScript、Vite 和浏览器控制台均通过。
