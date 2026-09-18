# Nautilus 确定性离线模拟基线

2026-09-14 继续交付：`hot_snapshot` 已能向本模块提供真实行情准入所需的交易所身份、事件时间语义、股数单位、买卖一档、当天交易日历和带来源标记的市场状态；`build_observed_realtime_request()` 可把准入通过的单票快照转换为 `observed_realtime` paper 回放请求。13:30 实测 `600000,000001` 通过数据准入；600519 因源报价超过 5 秒仍被拒。隔离日志 `data/nautilus-baseline/continuous-observed-final-20260914.sqlite3` 已用 600000 当前行情完成 100 股买入、恢复和对账。只读 AI 影子合同 `DecisionProposal` 已落地，但未接入执行入口。

2026-09-13 后续交付：增加真实数据 API 准入诊断和**单账户跨批次完整回放**。当时真实行情已读到，但执行字段不足、周末行情陈旧，未准入；AI 影子没有启用。见[本轮报告](../docs/superpowers/specs/2026-09-13-continuous-account-verification.md)。下文独立试验 `run` 与新的 `account-*` 命令是不同模式，不得混用同一日志。

本目录是新架构的隔离研发模块，不是现有 F5 的替代启动入口，不连接券商、不调用 AI、不启动计划任务。运行时使用真实 NautilusTrader BacktestEngine，只有该内核拥有试验中的订单、成交、现金和持仓；规则侧结算批次和日志结果用于核验，不是第二个活动账户。

## 模块边界

| 模块 | 职责 | 不负责 |
|---|---|---|
| contracts.py | 校验并复制输入，统一 Decimal、事件时间、显式日历与证券状态 | 获取外部数据、猜测交易日或价格带 |
| rules.py | T+1、资金/可卖量预留、单位、限价、行情新鲜度 | 撮合、记账、策略绩效 |
| native.py | 固定目标策略、Nautilus 适配、原生成交、费用及六项对账 | 访问 F5 或券商 |
| store.py | 单写者锁、SQLite 输入/结果提交、身份与哈希校验、完整重放 | 生成成交、连续账户迁移 |
| cli.py | run / recover / status 操作入口 | 后台调度、自动重试交易 |
| intake.py | 固定本地数据 API 观测、时间/字段/覆盖率准入报告；把准入通过的单票实时快照转换为隔离 paper 回放请求 | 获取下单权限、用最新价伪造盘口、多证券组合决策 |
| continuous.py | 单账户追加顺序、冻结初始配置、历史成交前缀核验 | 另算现金、原生增量热恢复 |
| shadow_context.py | 固定 AI 可见输入：baseline 哈希/账户摘要、行情、风险、因子、策略、历史摘要 | 暴露订单/成交明细、执行参数、旧 Agent 状态 |
| shadow_decision.py | 生成和校验只读 `DecisionProposal`，把 AI/影子模型建议与已对账基线结果哈希绑定 | 下单、改单、调度、恢复旧 Agent、修改风险或交易政策 |
| shadow_runner.py | 从已签名 `ShadowDecisionContext` 生成本地确定性影子提案，可选写入 shadow store | 调用外部大模型、查询数据库、访问 F5 写入口 |
| shadow_ai_adapter.py | 适配外部 AI 原始输出：清洗、生成 proposal、记录成功/失败审计 | 默认联网调用模型、放过校验失败输出、把 AI 输出当订单 |
| shadow_context_builder.py | 从受控 baseline/account/market/risk/factor/strategy/history 摘要组装 `ShadowDecisionContext` | 让 AI 自行查库、暴露订单成交明细、写执行账本 |
| shadow_runtime_summary.py | 把 baseline 与 runtime 摘要封装成可哈希校验的只读输入包，并由该包生成 `ShadowDecisionContext` | 下单、读取执行 journal、让 AI 临时拼上下文 |
| baseline_export.py | 只发布已对账且 `live_execution_authority=false` 的 `baseline_result.json`，并写元数据哈希 | 从 F5 写账本、伪造对账、发布实盘 baseline |
| shadow_ai_provider.py | 用 runtime summary 校验 AI 原始输出，校验通过后原子发布 `ai_raw_output.json` | 默认联网调用模型、放过非法输出、生成订单 |
| shadow_cycle.py | 串联 context-build → shadow-ai-run → shadow-report，生成单次只读研究闭环 | 调度日程、执行交易、绕过 proposal/context 校验 |

调用顺序：CLI → Journal 持久化输入 → Native 固定目标/显式订单 → Rules 准入与预留 → Nautilus 撮合和账户 → 对账 → Journal 提交结果。

AI 影子调用顺序是独立只读支路：已对账 baseline result → 可选 `shadow_runtime_summary.build_shadow_runtime_summary()` 固化受控输入包 → `shadow_context.build_shadow_decision_context()` → `shadow_runner.run_shadow_decision()` / `shadow_ai_adapter.run_shadow_ai()` → `shadow_decision.build_decision_proposal_from_baseline_binding()` → `validate_decision_proposal()` → 可选写入 shadow store → 仅用于研究对照。合同固定 `mode=shadow_only`、`execution_authority=false`、`can_trigger_order=false`、`can_change_trade_policy=false`、`live_execution_authority=false`；任何订单、成交明细、方向、数量、价格、券商、旧 `agent_*` 字段都会被剥离或拒绝。

只读影子记录使用独立 SQLite：默认 `data/nautilus-baseline/shadow_decisions.sqlite3`。它只保存已通过合同校验的 `DecisionProposal`，并生成“影子建议股票集合 vs baseline 当前持仓股票集合”的差异报表；不会打开 `--journal`，不会写 F5 活动账本。

## 本地操作

在 `C:\Users\HYSHEN\XuanJiQuant` 的 PowerShell 中运行：

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/demo.sqlite3 run --input trading_system/examples/two_session.json --id two-session-demo
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/demo.sqlite3 status
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/demo.sqlite3 recover
.venv-kernel-eval\Scripts\python.exe -m pytest tests/nautilus_baseline -q
```

记录和查看只读 AI 影子提案：

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli baseline-export --input data/nautilus-baseline/source_baseline_result.json --output data/nautilus-baseline/baseline_result.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli shadow-context-build --baseline-result data/nautilus-baseline/baseline_result.json --market-summary data/nautilus-baseline/market_summary.json --risk-summary data/nautilus-baseline/risk_summary.json --factor-summary data/nautilus-baseline/factor_summary.json --strategy-summary data/nautilus-baseline/strategy_summary.json --output data/nautilus-baseline/context.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-record --input data/nautilus-baseline/proposal.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-run --context data/nautilus-baseline/context.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-report
```

`baseline-export` 是 `baseline_result.json` 的受控生产入口：输入必须已经是完成对账的 paper baseline result，且 `live_execution_authority=false`。命令会先校验 baseline 合同，再原子写出 `baseline_result.json` 和 `baseline_result.meta.json`；失败时不覆盖旧文件，也不会打开 F5 或执行 journal。

`shadow-context-build` 的 baseline 必须是已对账且 `live_execution_authority=false` 的 paper baseline result。它会从 baseline 派生 account 摘要与历史计数，从 market/risk/factor/strategy 摘要中只提取白名单字段，并写出已签名 `xuanji-shadow-decision-context-v1`。即使输入摘要里带有订单、成交、价格、盘口或旧 Agent 字段，最终 context 也不得暴露给 AI；无法安全摘要的字段会被拒绝或忽略。

`shadow-record` 的输入必须已经是 `xuanji-decision-proposal-v1`，通常由 `trading_system.shadow_decision.build_decision_proposal()` 生成。`shadow-run` 的输入必须是 `xuanji-shadow-decision-context-v1`，通常由 `trading_system.shadow_context.build_shadow_decision_context()` 生成；当前只使用本地确定性影子模型，真实外部 AI 接入必须复用同一 context/proposal 合同。重复记录同一提案返回 `existing`；存量记录哈希不一致会失败关闭。`shadow-report` 返回 stance 分布、平均置信度、baseline 哈希集合，以及每条提案的 `shadow_only_codes / baseline_only_codes / overlap_codes`。

外部 AI 适配器当前只接受调用方提供的原始模型输出，不默认联网：

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-ai-run --context data/nautilus-baseline/context.json --raw-output data/nautilus-baseline/ai_raw_output.json
```

`shadow_ai_adapter.run_shadow_ai()` 也可在测试或上层编排中接收 `model_client(request)`。传给模型的 request 只包含已验证 `ShadowDecisionContext`；模型返回的原始文本会原样进入 `shadow_ai_runs.raw_output`，清洗后的 recommendation 进入 `sanitized_output`。成功时写入 proposal 并记录 `proposal_id`；JSON 解析、权重、权限、订单字段等任何校验失败都会记录 `validation_failed` 与 `validation_error`，不会生成 proposal，也不会进入执行层。

单次只读研究闭环可用：

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli shadow-runtime-summary --baseline-result data/nautilus-baseline/baseline_result.json --market-summary data/nautilus-baseline/market_summary.json --risk-summary data/nautilus-baseline/risk_summary.json --factor-summary data/nautilus-baseline/factor_summary.json --strategy-summary data/nautilus-baseline/strategy_summary.json --output data/nautilus-baseline/runtime_summary.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli shadow-ai-output --runtime-summary data/nautilus-baseline/runtime_summary.json --raw-output data/nautilus-baseline/raw_model_output.json --output data/nautilus-baseline/ai_raw_output.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-cycle --baseline-result data/nautilus-baseline/baseline_result.json --market-summary data/nautilus-baseline/market_summary.json --risk-summary data/nautilus-baseline/risk_summary.json --factor-summary data/nautilus-baseline/factor_summary.json --strategy-summary data/nautilus-baseline/strategy_summary.json --raw-output data/nautilus-baseline/ai_raw_output.json --context-output data/nautilus-baseline/context.json --report-output data/nautilus-baseline/shadow_cycle_report.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --shadow-store data/nautilus-baseline/shadow_decisions.sqlite3 shadow-cycle --runtime-summary data/nautilus-baseline/runtime_summary.json --raw-output data/nautilus-baseline/ai_raw_output.json --context-output data/nautilus-baseline/context_from_runtime.json --report-output data/nautilus-baseline/shadow_cycle_report.json
```

`shadow-runtime-summary` 生成 `xuanji-shadow-runtime-summary-v1`，把 baseline、market、risk、factor、strategy、history 摘要及其哈希绑定成受控输入包；它固定 `execution_authority=false`、`live_execution_authority=false`，不打开执行 journal，也不写 F5。`shadow-ai-output` 是 `ai_raw_output.json` 的受控生产入口：它用同一 runtime summary 构造只读 context，并用 `run_shadow_ai` 校验原始模型输出，只有输出可形成合法 `DecisionProposal` 时才原子发布。`shadow-cycle` 是 `shadow-context-build -> shadow-ai-run -> shadow-report` 的事务式编排：先构造 context，再适配 AI 原始输出，最后读取 proposal/audit 两类报表。它可以直接消费 `--runtime-summary`，仍要求调用方提供 `--raw-output`，不默认联网；输出 artifact 使用新建写入，不覆盖已有文件。即使传入 `--journal`，该命令也不会打开或写入执行 journal。

环境使用 `experiments/kernel_evaluation/requirements.lock` 的隔离依赖。没有 Nautilus 的普通 Python 环境会跳过这组测试，跳过不能算验证通过。示例是显式标记 synthetic 的两日合成场景，不是历史收益证明。

同一日志内，相同 ID 和相同内容返回已有结果；同 ID 改内容返回 `run_identity_conflict`。新的 ID 是从输入初始现金开始的**独立离线试验**，不承接上一试验的持仓，不能当成连续账户。`status` 核验哈希和实现身份，但不会重算；`recover` 才会重新运行内核比较完整输出。

不要把 `--journal` 指向 `data/paper/f5_ledger.db`。不匹配的已有数据库会被拒绝；默认日志位于 `data/nautilus-baseline/`。运行中的日志采用单写者拒绝模式，第二个进程得到 `writer_busy`，并不排队。正常退出或操作系统结束进程后锁自动释放，锁文件存在不代表仍被占用。

## 恢复契约与限制

- SQLite WAL + synchronous FULL；先提交不可变输入，再执行，再原子提交结果。pending 表示可以从输入重放，不表示应向外部系统重发订单。
- 完成结果重放必须逐内容哈希一致；输入/结果损坏、实现身份不一致、对账失败均拒绝继续。不要改哈希来强行解锁。
- 实现身份绑定 contracts/rules/native 文件及 Nautilus 版本，不是完整环境签名或防恶意篡改证明。升级后保留原日志和原实现，另建试验日志；没有自动迁移功能。
- 费用为输入配置：佣金、最低佣金、卖出税费和过户费；不宣称默认值覆盖所有市场制度。部分成交后剩余 IOC 数量取消，只按实际成交扣费。
- 范围限单证券、CNY 现金账户、100 股买入单位、0.01 元价格档位和连续竞价；交易日、日价格带与停牌信息由输入声明。没有集合竞价、全板块规则、公司行动、自动官方主数据或历史数据质量证明。
- 撮合仅使用有效一档报价及配置流动性份额，不外推深度；无效行情不能用于下单或刷新估值。固定目标数量用于检验执行，不是寻优策略。
- 已验证进程强制退出，不等同于断电、磁盘损坏或跨主机容灾。恢复是全量重放，成本随输入规模增加，尚未验证持续盘中、多证券、多日运营及增量热恢复。

2026-09-13 验收：34 passed，62 条上游 Pandas 弃用警告。详见[恢复验收报告](../docs/superpowers/specs/2026-09-13-nautilus-baseline-recovery-verification.md)。

## 真实数据观察

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli data-probe --codes 600000,000001,600519
```

默认读取 `http://127.0.0.1:8880/api/data` 的 `hot_snapshot`。可加 `--report data/nautilus-baseline/my-data-report.json` 新建报告，已有文件拒绝覆盖。报告保存原始响应、哈希、核验时间、每只股票源时间、覆盖率与阻断。

退出码 0 表示本次执行数据契约通过，2 表示接口观察成功但不具备执行准入，1 表示操作异常。即使返回 0 也没有下单权限，不会自动调用账户追加。请求限 20 只股票、超时默认 10 秒、响应不超过 2MB。可成交准入要求明确的事件时间语义、股数单位、交易所身份、日状态/价格带和日历；单有最新成交价不能替代。

当前 Sina 路径的一档盘口来自供应商原始 Level-1 字段，单位规范为 shares。日历来自项目交易日历；日价格带按前收盘价和 A 股板块规则派生并明确标记来源，适合 paper/研发准入，不等同于官方逐证券主数据。任何超过 5 秒、非当天、无盘口、无市场状态或状态日期不一致的快照继续拒绝。

## 单账户跨批次运行

以下两条命令分别在独立进程中运行，但必须使用同一 `--journal` 和 `--account`：

```powershell
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/continuous-demo.sqlite3 account-append --account demo --id day1 --expected-revision 0 --input trading_system/examples/continuous_day1.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/continuous-demo.sqlite3 account-append --account demo --id day2 --expected-revision 1 --input trading_system/examples/continuous_day2.json
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/continuous-demo.sqlite3 account-status --account demo
.venv-kernel-eval\Scripts\python.exe -m trading_system.cli --journal data/nautilus-baseline/continuous-demo.sqlite3 account-recover --account demo
```

两个示例均标记 synthetic。第一批买入 1000 股，第二批次日卖出。第二批的 initial_cash 只是校验首批冻结配置，**不是重新注资**。现金/持仓/T+1 由从首批开始的同一条原生事件历史恢复。每个新批次仅追加较晚的帧，禁止改写旧交易日/目标、费用、初始资金或证券。

`expected-revision` 是调用者看到的当前版本，错误版本拒绝；重复 batch ID 和相同内容返回原批次结果（可能是旧版本），要看最新状态请调用 account-status。`result.fills` 是累计成交，不能将各版本列表求和；`new_fill_count` 才是本批新增数量。一个日志只能归属一个账户，不能把旧独立试验日志直接转换为连续账户。

发生强退后若存在 `pending_revision`，禁止新批次追加；先 account-recover，再读取 committed_revision。状态继续展示最后已提交的账户，不把 pending 当成功。输入、结果、历史前缀或代码身份不一致会关闭恢复；不得直接编辑日志来解锁。

上限为 100 批次、累计 10000 帧，触顶明确拒绝。当前是有界的持久连续回放，不是长期驻留撮合服务，也不是增量热恢复；不能把完整重放耗时作为线上订单延迟。

模式有双向门禁：旧 trial 入口打开 continuous 日志即拒绝；连续模式禁止 Journal 通用 recover，必须经 ContinuousAccount 核验历史成交前缀。API 观察禁止 HTTP 重定向，避免把其他地址的响应归属到本地数据 API。
