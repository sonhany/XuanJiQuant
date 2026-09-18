# XuanJiQuant 当前系统工作流图

> 架构规则更新：2026-08-20（Asia/Shanghai）。AI Agent 控制面已退役；历史数据库记录不代表当前能力。运行数据必须以各产物自己的时间字段为准，下方带日期的数值只表示历史快照。

## 确定性研究日程（2026-08-19 规则）

```mermaid
flowchart LR
  D["XuanJiQuant-Research-Daily<br/>交易日 16:20"] --> DATA["日线更新 + DataSnapshot 门禁"]
  DATA --> FACTOR["同版本 factor_daily"]
  FACTOR --> SELECT["research_selection_daily<br/>版本化研究组合"]
  SELECT --> RO["research_only<br/>execution_authority=false"]
  Q["XuanJiQuant-Qlib-Weekly<br/>周六 18:30"] --> PIT["六年 PIT + 质量 + 行业 + 基准证据"]
  FACTOR --> PRE{"周日双前置门禁"}
  PIT --> PRE
  S["XuanJiQuant-Strategy-Weekly<br/>周日 10:00"] --> PRE
  PRE -->|"通过"| F4["F4 走样本外与组合验证"]
  PRE -->|"缺失/错版"| CLOSED["失败关闭 + reason code"]
  F4 --> RO
  RO --> G5{"F5 独立准入门禁"}
  G5 -->|"F4通过"| P5["validated_paper"]
  G5 -->|"仅绩效失败且证据完整"| XP["experimental_paper / unqualified"]
  G5 -->|"F4 blocked / 身份错版 / 政策冲突"| B5["blocked + 零订单"]
  P5 --> PREP["17:10 准备下一交易日模拟计划"]
  XP --> PREP
  PREP --> E5["次日盘中 5 分钟周期模拟成交 + 十项对账"]
```

三项研究外部时钟均使用 `IgnoreNew` 和 4 小时上限。每日组合必须绑定当日快照 ID、数据哈希、因子版本、F4 validation ID 与组合政策版本；旧组合不能冒充当前结果。周日 F4 必须看到周五同版本因子和本周六 Qlib 成功账本，任何缺口均失败关闭。独立 F5 日频时钟在周一至周五 17:10 运行，`IgnoreNew`、15 分钟重试最多 3 次、最长 2 小时；盘中时钟在 09:35-11:25、13:05-14:50 每 5 分钟运行。两者只有本地模拟权限，不含 Agent、生产晋升或实盘权限。

页面投影保持双链分离：`market_scan` 显示“F4/PIT 数据截止日”和周频门禁；`research_selection` 显示“当前因子/选股日”和每日组合。两者只在 `StrategyPanel` 并列展示，任一失败不覆盖另一条证据；每日组合固定为 `research_only`、`execution_authority=false`，不构成交易信号。

2026-08-19 09:35 的运行快照：当时预期最新完整交易日为 2026-08-18；日线快照覆盖 5201/5203，58 个因子与数据哈希一致，`research_selection_daily` 生成 20 只股票的诊断研究组合。来源 F4 状态是 `f4_rejected`，所以该组合仅用于诊断研究，不表示 F4 门禁通过，更不表示可以交易。

```mermaid
flowchart TD
  S[外部行情/财务/资讯源] --> D[数据层 quant/data]
  D --> Q[质量门禁与 DataSnapshot]
  Q --> DB[(SQLite / Qlib PIT)]
  DB --> F[因子层 quant/factor]
  F --> E[IC/IR 与批量评估]
  E --> ST[策略层 quant/strategy]
  ST --> BT[F4 走样本外与组合回测]
  BT --> R[确定性风险分析 quant/risk]
  R --> G5{"F5 F4/身份/政策/硬风控门禁"}
  G5 -->|"通过"| PX["quant/paper_execution<br/>日线模拟撮合与对账"]
  G5 -->|"失败"| PB["blocked / 零活动订单"]
  PX --> F5DB[(data/paper/f5_ledger.db)]
  F5DB --> UI[驾驶舱与模拟页面]
  DB --> L[历史模拟账本只读]
  L --> UI

  RS[固定 ResearchTrainingScheduler] --> E
  RS --> F4[validate_strategy_portfolios.py]
  F4 --> BT
  RS --> QL[Qlib 周/月/季研究]

  X[旧 Agent / 任意订单 / 实盘]:::off
  X -. 永久禁止 .-> L
  classDef off fill:#3f1d24,stroke:#ef4444,color:#fecaca;
```

## 权限图

```mermaid
flowchart LR
  WEB[React 页面] --> API[Node API]
  API --> READ[只读 runner]
  READ --> FACTS[(当前数据/历史账本)]
  API --> F5["F5 固定动作白名单"]
  F5 --> PAPER[(F5 唯一活动模拟账本)]
  RESEARCH[确定性研究任务] --> ART[研究产物]
  ART -. 不自动晋升 .-> FACTS
  LLM[普通 LLM 解释] -. 无执行权限 .-> WEB
  ORDER[任意订单或实盘写入]:::blocked
  API -. 409 arbitrary_order_action_forbidden .-> ORDER
  classDef blocked fill:#3f1d24,stroke:#ef4444,color:#fecaca;
```

## 页面到源码

| 页面 | API | Python/领域 | 状态 |
|---|---|---|---|
| 投资驾驶舱 | `/api/workbench` | F5 account/risk/alert/global context 只读聚合 | 可用 |
| 因子研究 | `/api/factor` | `quant/factor`、`evaluate_factors.py` | 可用 |
| F4 组合验证 | `/api/strategy` | `validate_strategy_portfolios.py`、`quant/strategy/f4_*`、`portfolio*` | 等待真实窗口指标/只读研究 |
| F5 模拟执行/组合 | `/api/paper-execution` | `quant/paper_execution`、`f5_paper_runner.py` | 确定性模拟；无实盘权限 |
| 统一模拟账本 | `/api/paper-execution`、`/api/execution` | `f5_paper_runner.py`、`active_account_projection` | F5 唯一活动账户；实盘关闭 |
| 历史执行审计 | 审计回放、`/api/paper` | `quant/data/audit.py`、`paper_runner.py` | 历史只读，不参与当前账户 |
| 风险与审计 | `/api/risk` | `risk_runner.py`、`quant/data/audit.py` | 可用 |
| 市场数据 | `/api/data`、`/api/sync` | data runner/sync service | 可用 |
| 市场资讯 | `/api/jin10`、`/api/cninfo` | 对应 runner | 可用 |
| Agent 页面/API/运行时 | 无 | 已删除 | 退役 |

## F5 确定性模拟执行闭环（2026-08-19 规则）

```mermaid
flowchart TD
  SEL["每日研究组合<br/>research_only"] --> ID{"F4 candidate + 身份/新鲜度"}
  F4["F4 latest + validation ID"] --> ID
  FACTOR["因子快照 ID + 数据哈希"] --> ID
  POLICY["F5 版本政策 + hard_limits"] --> COMP{"组合政策兼容"}
  ID -->|"通过"| COMP
  ID -->|"失败"| BLOCK["paper_runs=blocked<br/>零订单/零成交"]
  COMP -->|"TopK/权重/敞口兼容"| PREP["prepared<br/>目标差额 + 卖出优先 + 买入整手"]
  COMP -->|"不兼容"| BLOCK
  PREP --> NEXT["目标交易日完整日线"]
  NEXT --> MATCH["开盘价 + 滑点 + 费用 + ADV容量"]
  MATCH --> TERM{"每张订单明确终态"}
  TERM --> LEDGER["订单/成交/现金/持仓/权益<br/>同一事务事实"]
  LEDGER --> REC["十项不变量对账"]
  REC -->|"通过"| DONE["completed / completed_with_rejections"]
  REC -->|"副作用无法证明"| HALT["halted_unknown + F5 熔断"]
```

权限分离：研究组合仍是 `research_only`、`execution_authority=false`；F5 只在独立模拟准入通过后为本地计划生成 `paper_execution_authority=true`，同时固定 `live_execution_authority=false`。UI/API 不能提交代码、方向、数量或价格。F4 为 `f4_rejected` 时策略质量仍是 `unqualified`；若且仅若拒绝原因属于五项纯绩效门槛、数据/身份完整且约束与未来数据违规均为 0，可进入 `experimental_paper`。`f4_blocked` 或任一安全证据异常继续失败关闭。

2026-08-19 16:18 运行证据：`XuanJiQuant-Paper-Daily` 已安装并实际启动返回 0；活动链路止于 `blocked_by_f4`，目标交易日 `20260820`，订单/成交均为 0。页面与 API 同时显示“模拟能力存在、当前模拟许可为否、实盘许可为否”；任意下单在控制面和 F5 白名单形成双层拒绝。固定合格测试覆盖“走样本组合 → 确定性差额订单 → 日线撮合 → T+1/费用/滑点 → 十项对账 → 终态”，只用于证明实现闭环，不改变活动 F4 审计事实。

## 历史与当前的分界

`quant.db` 可能仍含 `agent_runs`、`agent_events`、`agent_tool_calls`、authority/session、旧 `ai:*` KV 和带 `agent_run_id` 的订单字段。它们仅供历史审计与问题回放；当前代码不启动、不读取为控制状态，也不据此恢复交易。

## 因子层当前闭环（2026-08-14）

```mermaid
flowchart TD
  U["活动股票池 5203"] --> DU["daily_update.py"]
  K["完整日 K 缓存"] --> DU
  DU --> G{"覆盖率门禁 >= 95%"}
  G -->|通过| DS["DataSnapshot latest_passed"]
  G -->|未通过| STOP["失败关闭，不推进消费者指针"]
  DS --> FI["FactorInputSnapshot"]
  FI --> CUT["按 as_of 截断未来/盘中日线"]
  CUT --> ELIG["当前可评估股票池"]
  ELIG --> EF["58 因子 + IC/IR + 多周期衰减"]
  EF --> STAGE["同一 attempt 暂存代"]
  STAGE --> PKL["factor_snapshot.pkl"]
  STAGE --> JSON["factor_snapshot_latest.json"]
  STAGE --> IC["factor_evaluation.json"]
  STAGE --> SEL["research selection"]
  PKL --> VERSION{"三产物身份/结构/哈希/权限一致"}
  JSON --> VERSION
  IC --> VERSION
  SEL --> VERSION
  VERSION -->|一致| PTR["daily/latest.json 原子完成指针"]
  VERSION -->|不一致| STOP2["保留上一完整 generation"]
  PTR --> API["因子榜单/API"]
  VERSION --> STRAT["F4 策略与组合验证"]
  API --> RO["research_only / 无执行权限"]
  STRAT --> RO
```

职责边界：数据层只负责可验证的数据产品；因子层只负责计算和评估；策略层只消费同版本因子；页面只展示；执行写入保持关闭。`ResearchTrainingScheduler` 是确定性时间触发器，不是 AI Agent，也不能修改股票池规则、晋升研究产物或产生订单。

## F4 多 Alpha 候选工厂 v2（活动架构，真实六年结果待重跑）

```mermaid
flowchart TD
  F3["同版本 F3 因子证据"] --> DG{"PIT/质量/行业/基准门禁"}
  DG --> PANEL["504/126/126 窗口\npurge 20 / embargo 5"]
  PANEL --> REG["24 个预登记候选\n动量/反转/防御/流动性/组合/Qlib 各4"]
  REG --> FIT["train-only 拟合\n规则批量上下文 + Qlib 独立 Recorder"]
  FIT --> VAL["本窗口 validation 排名\n不可用候选单独记因"]
  VAL --> LOCK["持久原子 winner 锁\nregistry/alpha/fit/model/policy hash"]
  LOCK --> TEST["只有窗口锁定胜者可以读取 test\n1.0/1.5/2.0 倍成本"]
  TEST --> GATE{"f4-gate-v4\n八项门槛不变"}
  GATE --> TEN["十件套身份/哈希/有限值/权限门禁"]
  TEN --> PUB["factory-v2/<factory_run_id>\n原子 latest 指针"]
  PUB --> RO["promotion_state=research_only\nexecution_authority=false"]
  RO --> API["strategy_runner::market_scan\n只读六族诊断"]
  API --> UI["StrategyPanel\n无晋升或交易按钮"]
```

模块职责：`f4_alpha_contracts.py` 定义 v2 Alpha、候选与注册表身份；`f4_alpha_rules.py` 只负责规则特征、截面处理和训练段拟合；`f4_qlib_adapter.py` 只负责窗口隔离的 Qlib 训练/预测；`f4_candidate_factory.py` 与 `f4_real_pipeline.py` 负责候选隔离、榜单、锁和 winner-only test；`f4_v2_publication.py` 负责 exact-10 发布与读取完整性。v1/v2 下游读取必须显式分支，不能靠字段存在猜版本。

## F4 策略与组合验证闭环（2026-08-19 至 2026-08-20 的 v1 历史候选工厂）

```mermaid
flowchart TD
  F3["F3 版本化因子证据"] --> DG{"F4 数据门禁"}
  PIT["六年 PIT manifest + quality report"] --> DG
  IND["CNINFO 有效日期行业历史"] --> DG
  BENCH["版本化基准"] --> DG
  DG -->|"缺失/不一致"| BLOCK["f4_blocked + reason code"]
  DG -->|"全部通过"| PANEL["版本化 PIT 因子面板\n5426 标的 / 47 因子"]
  PANEL --> WF["走样本外 504/126/126\npurge 20 / embargo 5"]
  WF --> FIT["仅在训练段拟合因子"]
  FIT --> REG["预声明六候选\nTopK 5/10 × 周期 5/10/20"]
  REG --> VAL["仅本窗口 validation 排名"]
  VAL --> LOCK["原子稳定锁\nfactory/candidate/policy hash"]
  LOCK --> TEST["仅 winner 读取本窗口 test"]
  TEST --> PORT["总敞口 <=95% / 单票 <=20%\n行业/未知行业约束"]
  PORT --> SIM["停牌/涨跌停/T+1/整手\n费用/滑点/ADV 10%"]
  SIM --> METRIC["费后超额/夏普/回撤\n窗口稳定性/双倍成本"]
  METRIC --> GATE{"F4 硬门禁"}
  GATE -->|"未通过"| REJECT["f4_rejected"]
  GATE -->|"通过"| CAND["f4_research_candidate"]
  BLOCK --> AUTH["research_only\nexecution_authority=false"]
  REJECT --> AUTH
  CAND --> AUTH
  GATE -->|"六候选耗尽"| EXHAUST["f4_rejected_exhausted"]
  EXHAUST --> AUTH
  AUTH --> ID["身份绑定\nmanifest hash + quality report id\nindustry version + benchmark version"]
  ID --> ART["九份不可变证据 + 哈希校验"]
  ART --> LATEST["17KB latest 轻量只读投影"]
  LATEST --> API["strategy_runner::market_scan"]
  API --> PAGE["StrategyPanel F4 组合验证"]
```

`test` 切片不得用于窗口纳入、候选排名或重选；锁先于 test 持久化，崩溃重跑复用同一锁。研究组合到 F5 必须精确携带并核对 `factory_run_id + candidate_id + lock_hash + policy_hash`；新工厂身份缺失时失败关闭，不回退旧 Top20。以上仍为 `research_only`，不授予真实交易权限。

2026-08-18 11:18 真实快照为 `f4_rejected`，validation ID `65c264ce8f7c6af48e2b6410622c9491dffeb3f1a5509c4e90c23f6db373eeaa`。PIT 面板包含 7,095,568 行、5425 标的和 47 个严格日线因子，6 个完整窗口全部完成；正超额窗口占比 33.33%、聚合费后超额 -80.04%、中位 Sharpe -0.257、最差回撤 -55.61%、双倍成本超额 -90.95%。数据门禁、目标约束和未来数据检查均通过，但 5 项绩效门槛失败，所以不能成为研究候选。F4 无论通过与否都不拥有生产晋升或执行权限；页面不得回退到旧市场扫描、截面代理或历史策略榜单。

2026-08-20 01:54 历史 F4 快照：PIT `daily-pit-2020-08-05-2026-08-19` 的完成清单为 5426 只；目录中的退市残留 `SZ300028.json` 未删除，但不再进入行业、Qlib 或 F4 股票池。validation `5bd6ed52437f6042711ea55854b98cbf1ef83d8596fe35f5c85dcc46d132cc58` 使用 `f4-real-pipeline-v3-nested-candidates-gross-clamp` 和 5 个稳定外层窗口锁；六候选耗尽，费后超额 -74.37%、Sharpe 0.0136、最大回撤 -45.54%、双倍成本超额 -79.11%，状态为 `f4_rejected_exhausted`。v3 修正浮点总敞口尾差并以新身份完整重跑，没有复用 v2 证据。这是策略绩效拒绝，不是数据阻断；后续 F5 实验模拟设计允许该类纯绩效失败进入 `experimental_paper`，但不改变 F4 结论。

### 六年 PIT 数据产品关系

```mermaid
flowchart LR
  SRC["TdxQuant 近期 + AkShare/BaoStock 历史"] --> COL["collector.py\n可续跑 + 每标的哈希"]
  REF["交易所股票主数据\n上市/退市/名称变更"] --> COL
  COL --> MAN["manifest.json\n5426 completed symbols"]
  MAN --> QG["quality_gate.py\n生命周期口径"]
  QG --> QR["quality_report.json\npassed"]
  MAN --> EXP["exporter.py\n两遍流式导出"]
  QR --> EXP
  EXP --> BIN["Qlib bin\n1465 日 / 5426 标的"]
  CN["CNINFO 008002"] --> IND2["pit_industry.json\n有效日期 / 96.983%"]
  BM["沪深300日线"] --> BM2["000300.json\n1462/1465"]
  MAN --> F4ID["F4 四输入身份"]
  QR --> F4ID
  IND2 --> F4ID
  BM2 --> F4ID
  F4ID --> RO["research_only\nexecution_authority=false"]
```
