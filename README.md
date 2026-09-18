# 玄机量化 XuanJiQuant

> 面向 A 股的本机量化研究与**确定性模拟盘**工作台。
> 全链路覆盖：数据接入 → 因子研究 → 策略验证 → Qlib 实验 → 硬风控 → F5 模拟账本。
> 单机运行，**不连接实盘，不承诺收益**。

**当前版本：`v1.0.0`　·　发布日期：2026-09-19**

---

## 当前状态

| 项目 | 状态 |
|---|---|
| 运行形态 | Windows 单机 · Web `127.0.0.1:8888` + API `127.0.0.1:8880` + Python 量化核心 |
| 实盘权限 | **关闭**，`live_execution_authority=false`，任意 `place_order` 返回 HTTP 409 |
| AI 自治 | 控制面已于 **2026-08-13 退役**；仅保留**只读** AI 影子研究（`DecisionProposal` 合同，零执行权限） |
| 研究链路 | 日频确定性研究流水线 · 周频 Qlib 训练 · 周频 F4 多 Alpha 候选工厂 v2 |
| 模拟执行 | F5 确定性日频 + 盘中自动模拟，独立账本、十项对账、幂等重放 |
| 数据与产物 | SQLite 状态总线 + `data/`（本地生成，不入库） |

## 核心能力

1. **数据接入与治理** —— 全市场日线 / 财务 / 资讯，快照版本化、质量门禁、覆盖率校验、未来数据防线。
2. **因子与策略研究** —— 58 个登记因子；F4 多 Alpha 候选工厂 v2（24 个预登记候选，504/126/126 交易日走样本外，purge 20、embargo 5，只有窗口胜者可读取 test）。
3. **Qlib 实验** —— 六年 PIT 数据集、窗口隔离训练、官方与 A 股双引擎回测，候选失败只隔离不阻断全链路。
4. **F5 确定性模拟执行** —— 日频准备 + 盘中自动模拟，独立账本 `data/paper/f5_ledger.db`，十项对账、T+1、涨跌停、费用滑点、跨批次幂等。
5. **硬风控与审计** —— 确定性逐单规则、四层健康度、全链路审计；风控失败即关闭，不允许放宽。
6. **只读 AI 影子研究** —— 受控上下文 + `DecisionProposal` 合同，输出固定 `shadow_only`，四个执行/策略权限布尔值全为 `false`。

## 快速开始

```powershell
npm install
pip install -r requirements.txt
node scripts/start_services.mjs     # 幂等启动 Web + API
```

- Web：<http://127.0.0.1:8888>　·　API：<http://127.0.0.1:8880>
- 全量回归：`python -m pytest -q`、`npm run test:contracts`、`npx tsc --noEmit`、`npm run build`
- 计划任务（安装前必须先完成全量回归）：日频 `scripts/install_f5_paper_task.ps1`、盘中 `scripts/install_f5_intraday_task.ps1`

### 下载安装包

从 Releases 获取便携包：<https://github.com/sonhany/xuanji/releases/latest>

1. 下载 `XuanJiQuant-vX.Y.Z-portable.zip` 并解压
2. 双击 `setup.bat`（检查 Node/Python 并安装依赖）
3. 双击 `start_all.bat`，或执行 `node scripts/start_services.mjs`

> 便携包为源码包，不含 `node_modules` 与本地数据（`data/`、`logs/`），首次启动需联网安装依赖。
> 每个 Release 由推送 `v*.*.*` 标签自动触发打包（`.github/workflows/release.yml`）。

## 架构

```text
数据源（TdxQuant / AkShare / BaoStock / 巨潮 / 资讯）
  -> quant/data             快照、质量门禁、覆盖率
  -> quant/factor           58 因子 + 受限 DSL + IC/IR
  -> quant/strategy         F4 走样本外 / 组合级验证（research_only）
  -> quant/risk             确定性硬风控
  -> quant/paper_execution  F5 日频 + 盘中模拟、独立账本、对账
  -> Web(8888) / API(8880)  只读投影与受控动作
```

研究与执行严格分离：研究产物固定 `promotion_state=research_only`、`execution_authority=false`；
F5 只消费已发布的研究结论，不回写研究产物，不外溢为实盘。

## 目录结构（仓库保留内容）

| 路径 | 职责 |
|---|---|
| `App.tsx` / `index.tsx` / `index.html` / `components/` | React + TypeScript 前端工作台 |
| `server/` | Node API：路由、鉴权、SSE 行情流、Python 进程管理、看门狗 |
| `quant/` | Python 量化核心：data / factor / strategy / backtest / risk / qlib / valuation / paper_execution |
| `scripts/` | Runner、研究流水线、F5 执行入口、Qlib 训练、契约测试套件 |
| `trading_system/` | 隔离确定性基线：Nautilus 内核准入、重放恢复、只读影子研究合同 |
| `tests/` | Python 与 Node 回归测试 |
| `config/` | 数据同步频率、F5 执行政策、LLM 模型配置 |
| `lib/` `hooks/` `public/` | 前端共享逻辑与静态资源 |
| `docs/` | 交接文档、系统流程图、Qlib 本地训练说明 |

**本地保留、不入库**（`.gitignore` 排除）：`data/`、`logs/`、`dist/`、`node_modules/`、`.venv*/`、
`Logo/`、`screenshots/`、`experiments/`、`docs/superpowers/`（历史研发计划）、`docs/plans/`、
`bigquant_comparison_analysis.md`、`archify/`、`graphify-out/`、二进制与缓存文件。

## 版本说明

### v1.0.0 — 2026-09-19

首个对外发布版本。系统定位由「AI 自主进化量化系统」收敛为「确定性优先的量化研究与模拟盘工作台」。

**Added**

- F5 确定性模拟执行：日频准备 + 盘中自动模拟，独立账本、十项对账、跨批次幂等与重放恢复。
- 确定性研究链路：`run_daily_research_pipeline`、`ResearchJobStore`、F4 多 Alpha 候选工厂 v2。
- Qlib 六年 PIT 数据集、窗口隔离训练与 A 股双引擎回测。
- 隔离基线 `trading_system/`：Nautilus 内核准入、单写者持久日志、只读 `DecisionProposal` 影子研究。
- 估值模块 `quant/valuation`、实时行情 SSE 推送与统一活动账户投影。

**Changed**

- 前端与后端端口调整为 Web `8888` / API `8880`，统一由 `scripts/start_services.mjs` 幂等启动。
- 数据同步频率收敛为单一权威 `config/data_sync_policy.json`，前后端与 Python 共同消费。
- 服务托管改为 Windows 计划任务（`XuanJiQuant-API-Service` / `-Web-Service` / `-Service-Supervisor`）。
- README 重写为发布版说明。

**Removed**

- AI Agent 自治控制面（`quant/ai`、`scripts/ai_*`、`scripts/paper/*`、`ai_manifest.json`、`ai_tools.json`）。
- 旧执行层 `quant/execution` 与旧冒烟测试脚本。
- 品牌资产、截图、历史研发计划等与运行无关的文件（本地保留，不入库）。

## 边界与权限（硬约束）

- 不连接券商、不触达真实资金；`live_execution_authority=false` 为固定事实。
- `/api/execution` 仅剩只读投影；`/api/paper` 只读；任意下单动作返回 HTTP 409。
- AI 不得晋升策略、放宽风控或下单；影子研究输出不得回写账本或触发执行。
- 研究结论与模拟许可分离：`validated_paper` 只接收 F4 合格候选，`experimental_paper` 只接收纯绩效失败的实验组合。
- 回测与模拟结果不代表未来收益。

## 文档

- 交接边界：[`docs/XUANJI_HANDOFF.md`](docs/XUANJI_HANDOFF.md)
- 系统流程图：[`docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`](docs/XUANJI_SYSTEM_WORKFLOW_MAP.md)
- Qlib 本地训练：[`docs/QLIB_LOCAL_TRAINING.md`](docs/QLIB_LOCAL_TRAINING.md)
- 隔离基线：[`trading_system/README.md`](trading_system/README.md)

## 环境要求

- Node.js 18+ · Python 3.10+ · Windows（PowerShell / 计划任务）
- 免费数据源可能限流或延迟，数据可能缺失；所有门禁失败一律按失败关闭处理。

## 风险提示

本项目仅用于量化研究、教学与模拟盘验证，不构成任何投资建议。系统不连接真实券商，不应直接用于实盘交易。
如需实盘，必须接入合规券商接口并重新设计认证、权限、风控、审计与灾备流程。
