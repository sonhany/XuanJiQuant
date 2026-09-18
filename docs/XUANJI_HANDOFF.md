# XuanJiQuant 交接说明

## 2026-09-16 驾驶舱展示只读 AI 影子研究状态

投资驾驶舱现在展示 `/api/workbench` 聚合出的 `shadow_research` 字段。其实现只读读取 `lib/shadow-research-status.mjs`，检查 `data/nautilus-baseline` 下 `baseline_result.json`、`runtime_summary.json`、`ai_raw_output.json`、最新 `shadow_cycle_report.json` 和 `shadow_decisions.sqlite3` 的存在性、更新时间、cycle 成功状态与 proposal 数量。首屏若慢缓存未完成，会同步补一次只读状态，避免页面显示空白。

边界：这是 Web 可见性与交接诊断，不是新的执行面。该字段固定 `execution_authority=false`、`can_trigger_order=false`、`live_execution_authority=false`，不写 F5 `data/paper/f5_ledger.db`，不调用 `/api/paper`、`/api/paper-execution` 或 `/api/execution`。如果当前显示 `baseline_missing`，含义是尚未发布 `data/nautilus-baseline/baseline_result.json`，不能把后台研究代码优化误解为已经产生 AI 影子建议。

## 2026-09-15 日频流水线接入只读 AI 影子研究

`scripts/run_daily_research_pipeline.py` 现在在每日研究成功发布或兼容镜像恢复后追加 `shadow_research` 只读阶段。默认输入位于同一数据根下的 `data/nautilus-baseline/baseline_result.json`、`data/nautilus-baseline/ai_raw_output.json`，输出位于 `data/nautilus-baseline/shadow-daily/<expected_date>/<generation>-<timestamp>/`，审计库仍为独立 `data/nautilus-baseline/shadow_decisions.sqlite3`。若 baseline 文件不存在，该阶段不触发；若 baseline 存在但 AI 原始输出不存在，会生成 `runtime_summary.json` 并返回 `status=skipped / reason_code=shadow_ai_raw_output_missing`，不把“没有 AI 输出”伪装成已决策。

新增两个受控生产端：`trading_system.baseline_export` / CLI `baseline-export` 负责把已完成对账、paper-only、`live_execution_authority=false` 的 baseline result 原子发布为 `baseline_result.json`，并写 `baseline_result.meta.json` 哈希元数据；`trading_system.shadow_ai_provider` / CLI `shadow-ai-output` 负责用 `runtime_summary.json` 构造只读 context 并校验原始模型输出，只有可形成合法 `DecisionProposal` 时才原子发布为 `ai_raw_output.json`，并写 `ai_raw_output.meta.json`。二者失败时不覆盖旧文件，不写执行账本。

边界：`shadow_research` 只调用 `trading_system.shadow_runtime_summary` 和 `trading_system.shadow_cycle` 的只读合同，固定 `execution_authority=false`、`can_trigger_order=false`、`live_execution_authority=false`。它不打开活动 F5 `data/paper/f5_ledger.db`，不调用 `/api/paper`、`/api/execution`，不恢复旧 `agent_*` 控制面，不连接券商。baseline 文件存在但内容越权、未对账或 shadow-cycle 校验失败时，日频结果会以 `shadow_research_failed` 暴露异常，避免静默吞掉错误。

## 2026-09-14 真实行情准入字段与隔离单账户实跑

`scripts/market_data.py` 现从新浪 A 股原始字段提取买一/卖一价格与数量，并标记 `venue`、`timestamp_kind=exchange`、`size_unit=shares`。`scripts/data_runner.py::normalize_hot_snapshot` 在热快照中补充项目交易日历与 `market` 状态；价格带来自前收盘价和板块规则，字段明确标记 `price_band_source=prev_close_board_rule`，停牌状态来自报价活跃度，字段标记 `status_source=quote_activity`。这些字段用于 paper/研发准入，不是官方主数据或实盘授权。

`config/data_sync_policy.json` 的 `hot_quotes.stale_after_ms` 从 3000 调整为 5000，与 `trading_system` 的 5 秒执行准入一致；不改变刷新频率、风控阈值或交易权限。API data_runner 长驻进程已按本项目 PID 精确重载。实测 `data-probe --codes 600000,000001` 在 2026-09-14 13:30:37 取得 `2/2` 执行准入；`600519` 在同轮因 7.9 秒旧报价继续被拒，说明陈旧行情没有被放行。

新增 `trading_system.intake.build_observed_realtime_request()`：只接受整批和单票都 execution_ready 的报告，将准入通过的实时快照转成 `data_kind=observed_realtime` 的单证券 Nautilus paper 请求；输出价格固定到 0.01 精度，避免三位小数触发原生内核精度错误。最终隔离研发日志 `data/nautilus-baseline/continuous-observed-final-20260914.sqlite3`，账户 `observed-realtime-smoke`，revision 1 使用 600000 当前行情买入 100 股，现金 `99054.99`、持仓 `600000:100`、当日可卖 0、权益 `99993.99`，六项对账与 `account-recover` 均通过，`live_execution_authority=false`。

边界：这不是活动 F5 `data/paper/f5_ledger.db`，没有切换 Web/API 执行路径，没有恢复旧 Agent，也没有连接券商接口。只读 AI 影子合同已经新增为 `trading_system.shadow_decision`：它只接受已完成对账且 `live_execution_authority=false` 的 paper baseline，对 AI/影子模型建议生成 `xuanji-decision-proposal-v1` 的 `DecisionProposal`，并绑定 `baseline_result_hash`。合同固定 `shadow_only`、`execution_authority=false`、`can_trigger_order=false`、`can_change_trade_policy=false`、`live_execution_authority=false`；订单、方向、数量、价格、券商和旧 `agent_*` 字段会被剥离或校验拒绝。当前它仅供研究对照，不接 F5 写入口、不接 Web/API 执行入口。

同日新增只读影子持久化：`trading_system.shadow_decision_store.ShadowDecisionJournal` 使用独立 `data/nautilus-baseline/shadow_decisions.sqlite3`，只保存通过合同校验的提案。`trading_system.cli` 增加 `shadow-record --input <proposal.json>` 与 `shadow-report`，二者只读研究语义固定为 `mode=shadow_decision`，不会打开或写入 `--journal`，不会触碰 F5 活动账本。报表只做 AI 影子建议与 baseline 持仓集合的差异：`shadow_only_codes`、`baseline_only_codes`、`overlap_codes`、stance 分布、平均置信度和 baseline 哈希集合；它不是订单簿、目标组合、风控许可或模拟账户。

同日继续新增只读影子上下文与运行器：`trading_system.shadow_context` 定义 `xuanji-shadow-decision-context-v1`，AI 可见输入只包括 baseline 哈希/账户摘要、行情、风险、因子、策略和历史摘要；订单/成交明细、方向、数量、价格、券商和旧 `agent_*` 字段均被拒绝。`trading_system.shadow_runner.run_shadow_decision()` 从已签名 context 生成本地确定性 shadow proposal，并可选写入 shadow store；CLI 新增 `shadow-run --context <context.json>`。当前没有接外部大模型，后续真实 AI 接入必须只读消费同一 context，并只输出同一 `DecisionProposal`，不得直接查询库、调用 `/api/paper`、调用 `/api/execution` 或写入 F5。

外部 AI 适配器已新增为 `trading_system.shadow_ai_adapter`。它的边界是“适配原始模型输出”，不是 Agent 控制面：上层可以传入 `model_client(request)`，CLI 也支持 `shadow-ai-run --context <context.json> --raw-output <ai_raw_output.json>` 做离线验收；适配器自身不默认联网、不读数据库、不调用 Web/API、不写 F5。`shadow_ai_runs` 审计表记录原始输出、清洗输出、`validation_error` 和可选 `proposal_id`。模型输出如果包含订单、成交、方向、数量、价格、券商或旧 Agent 字段，最终 proposal 必须被剥离或拒绝；校验失败仅记录 `validation_failed`，不得生成提案或进入执行层。

同日新增 `trading_system.shadow_context_builder`：从受控 runtime 摘要自动组装 `ShadowDecisionContext`，CLI 为 `shadow-context-build --baseline-result <baseline.json> --market-summary <market.json> --risk-summary <risk.json> --factor-summary <factor.json> --strategy-summary <strategy.json> --output <context.json>`。baseline 必须已对账且 paper-only；account 与 history 摘要由 baseline 派生，market/risk/factor/strategy 只抽取白名单字段并附 `source_hash`。该 builder 的职责是替 AI 固定输入边界，不是给 AI 查询数据库或账本的权限；输入文件中即使存在订单、成交、价格、盘口或旧 Agent 字段，最终 context 也不得暴露。

同日新增 `trading_system.shadow_cycle` 与 CLI `shadow-cycle`：将 `shadow-context-build -> shadow-ai-run -> shadow-report` 串成单次只读研究流水线。它要求显式传入 baseline、摘要文件和 `--raw-output`，不会默认联网调用模型；可选 `--context-output` 与 `--report-output` 均为新建写入，不覆盖已有 artifact。该命令即使收到 `--journal` 也不会打开或写入执行 journal，只写独立 shadow store；用途是每天或每次 baseline 完成后留下 AI 影子对照证据，不是交易调度器。

新增 `trading_system.shadow_runtime_summary` 与 CLI `shadow-runtime-summary`：把已对账 baseline result 以及 market/risk/factor/strategy/history 摘要封装为 `xuanji-shadow-runtime-summary-v1`，逐项保存 `source_hashes` 并固定 `execution_authority=false`、`live_execution_authority=false`。`shadow-cycle` 现在可直接消费 `--runtime-summary` 生成只读 context，再执行 `shadow-ai-run` 与报表输出；该路径用于把真实运行摘要交给 AI 影子对照，但仍不允许 AI 自己查库、读取执行 journal、写 F5、调用 `/api/paper` 或 `/api/execution`。

## 2026-09-13 数据准入与单账户跨批次回放

新增 `trading_system/intake.py`：只消费现有 `/api/data` hot_snapshot，不反向控制数据层，保存来源、源时间、核验时间、原始响应哈希、覆盖与缺项。3 只实取均有报价但执行准入 0/3，不代表全市场或真实盘中已通过。新增 `continuous.py`：在 Journal 上绑定唯一 account_id、顺序 revision、batch ID、原始输入块与上一结果哈希；冻结配置与旧输入，native 仍唯一负责账户。store.execute 增加提交前结果校验回调，历史成交改变则保留 pending，不发布成功。

命令分离：data-probe 不触碰账户；account-append/status/recover 必须显式研发日志路径；旧 run 是独立试验，不能混用。连续模式最新结果含累计成交，禁止跨 revision 相加；真实数据报告不能直接转成订单。仍是 100 批/10000 帧以内的完整重放，不是长期驻留或增量热恢复。

实际修复数据来源缺陷：新浪字段 30 的交易日期此前被忽略，字段 31 时分秒被拼上本机日期。现保留完整源日期，缺日期不补今天；股票和指数均有回归测试。仅重载 API 6416 下 3 个明确属于本项目的 data_runner 子进程，11:51:57 再调用 API 已从伪 20260913 恢复为正确 20260911。未修改风控、F5 账本或计划任务。

最终验证：Python 124 passed / 124 条上游弃用警告；Node 58/58（首轮一项账户查询超时，单项与全量重跑通过，时延根因未消除）。报告 `docs/superpowers/specs/2026-09-13-continuous-account-verification.md`；真实原始证据位于 `data/nautilus-baseline/data-intake*-20260913.json`；最终连续示例日志 `continuous-final-20260913.sqlite3`，审查前日志仅作历史证据。独立审查后补齐 Journal 双向模式隔离、专用恢复、必需可调用校验器与禁止 HTTP 重定向。AI 影子未接入；当前缺口是可执行行情字段、证券主数据/日历与持续盘中会话，不能擅自用默认值填齐。

## 2026-09-13 隔离确定性基线与恢复（阶段 B）

新模块 `trading_system/` 已落地。调用链为 `cli → store 输入提交 → native 策略 → rules 准入/预留 → Nautilus 原生撮合/账户 → 六项对账 → store 结果提交`。contracts 统一输入，rules 不撮合，store 不生成成交。只通过离线 CLI 使用，不连接现有 API、F5、计划任务或 AI，禁止把新日志误解成第二个活动 OMS。

持久日志默认 `data/nautilus-baseline/journal.sqlite3`，每个 ID 是独立回放，不能承接上一试验持仓。相同 ID/输入幂等，内容冲突拒绝；单写者竞争拒绝；输入或结果损坏、实现版本变化失败关闭。恢复方法是全量确定性重放，并非在线增量热恢复。

本轮先复现再修复：调用方可变输入污染已提交试验、状态查询遗漏输出哈希、日志入口误接无关数据库。回归共 34 passed / 62 条 Pandas 弃用警告；子进程退出和外部 kill 均覆盖输入/输出提交后两个断点。两日实跑仅一条日志、两笔成交、现金 99,984.80、空仓，重复和恢复完全一致。证据及限制见 `docs/superpowers/specs/2026-09-13-nautilus-baseline-recovery-verification.md`；运行方法见 `trading_system/README.md`。

阶段 A 裸内核的 4 个预期失败是历史结果，不应删除；新增适配已在本阶段覆盖普通股票显式夹具规则，仍不代表全市场合规。真实主数据/日历、持续单账户会话、多证券、增量恢复和运营验收待做，之后才接 AI 影子。下方 2026-09-11 段落按当时状态保留。

## 2026-09-11 新架构研发交接（未切换活动账户）

用户批准“成熟内核评估 → 确定性基线 → AI研究/影子 → AI自主模拟 → 运营验收”路线，仅模拟。新研发选择NautilusTrader为开发主线；当前旧Agent仍退役，F5仍是运行账本，不能把开发选型解释为已部署AI。

隔离实验位于`experiments/kernel_evaluation/`，Python环境`.venv-kernel-eval`，局部.NET SDK与NuGet缓存位于`data/kernel-evaluation/`。LEAN完整Launcher/Engine、Nautilus BacktestEngine各运行10个合成场景，另用共同夹具比较原生账户数学。两个实验从未拥有活动F5执行权限。结果、差异和准入缺口见`docs/superpowers/specs/2026-09-11-kernel-evaluation-results.md`及`data/kernel-evaluation/comparison.json`。

Nautilus原生测试7 passed / 4 strict xfailed；后者是T+1、证券停牌、日价格带与整手买入尚未接入的准入要求，不能计为通过。部分成交、撤单、事件去重和内存事件重放已实测；完整进程崩溃后的账户恢复尚未验收。LEAN分钟Bar与Nautilus QuoteTick的撮合假设不同，不能用两边耗时作直接吞吐排名。NuGet传递依赖漏洞及Pandas弃用警告保留为未解决事项。

下一步围绕单一Nautilus主线完成证券主数据/交易日历、事前规则、保守容量模型、唯一账户会计与持久恢复，再接AI影子。现有项目的planner、模拟撮合和告警实现不直接复制为新内核。历史F5账本和旧运行入口在正式切换前继续保留；不删除历史事实，也不并行启动第二个活动OMS。

## 1. 权威工作区

- 唯一活动目录：`C:\Users\HYSHEN\XuanJiQuant`
- 冻结备份：`C:\Users\HYSHEN\AlphaCouncil2-AI`，禁止读取后写入、启动、测试或修改
- Qlib 根目录：`C:\Users\HYSHEN\XuanJiQuant\data\qlib`

## 2. 2026-08-13 架构决策：Agent 全面退役

用户决定删除所有 AI Agent 功能和 Web 对应控制面。已删除 Agent 运行时、规划器、工具注册、verifier、恢复、调度器、执行授权、私有 paper trader、Agent API 和 React 组件。`ai_factor_agent`、`ai_strategy_agent` 同步删除；其中可复用的纯计算已迁到普通因子/确定性研究域。

历史 SQLite 表、KV、订单字段和日志不做机械改名或删除，原因是它们是既成审计事实。任何页面、API 或健康检查不得把这些历史记录解释为当前运行状态。

## 3. 当前五层职责

1. 数据层：外部源、同步、质量门禁、`DataSnapshot`、PIT/Qlib 数据产品。
2. 因子层：内置因子、受限 DSL、IC/IR 和人工批准的动态因子读取。
3. 策略层：F4 候选定义、走样本外、组合构建、成本/容量回测和研究门禁。
4. 执行层：`data/paper/f5_ledger.db` 是唯一活动模拟账本；`quant/paper_execution` 对 F4 合格组合和满足严格安全条件的 F4 绩效失败组合分别执行 `validated_paper` / `experimental_paper`。旧 `quant.db` 账户事实仅供历史审计，不参与任何当前投影。
5. 风控层：组合风险与硬规则独立存在；F5 只能收紧，不能由页面、研究或历史 AI 配置放宽。

四层健康度的活动实现是 `quant/health.py -> scripts/risk_runner.py::action_system_health -> /api/risk`。数据层使用全市场日线覆盖和预期交易日；因子层只读一个验证完整的 research generation；策略层同时展示 F4 研究门禁和同代每日组合；执行层只读 `data/paper/f5_ledger.db` 的运行、订单、成交和对账。不得再用旧 `factor:*` 缓存数量、硬编码“策略正常”或旧 `execution:state` 生成当前健康结论。

依赖只能由上到下。数据层不调用研究/策略/执行；页面不推导权限；研究任务不产生订单。

## 4. 研究调度

`Windows 计划任务 -> scripts/research_training_scheduler.py --once -> ResearchJobStore`

`scripts/start_services.mjs` 只负责 Web 与 API，不再启动常驻研究调度器。研究时间所有权完全属于 `XuanJiQuant-Research-Daily`、`XuanJiQuant-Qlib-Weekly` 和 `XuanJiQuant-Strategy-Weekly`，避免常驻轮询与外部时钟并发认领。Qlib 周期的硬顺序是 `collect_six_years -> quality_six_years -> build_f4_references -> export_six_years -> workflow_* -> backtest_ashare`；参考数据失败不能越过导出阶段。

Windows 计划任务的进程启动边界统一归 `scripts/run_hidden_scheduled_task.ps1` 所有。该脚本只接受 `paper_daily/paper_intraday/research_daily/qlib_weekly/strategy_weekly` 五个白名单键，分别映射到原有确定性入口；所有安装脚本必须注册 `powershell.exe -NoProfile -NonInteractive -WindowStyle Hidden -File ... -TaskKey <key>`，不得重新把任务动作指向 `python.exe`。启动器以隐藏窗口等待 Python 终态并传播真实退出码，因此 Windows 重试和 `LastTaskResult` 语义不变。任务仍使用原 `Interactive/Limited` 主体：用户登录时后台无弹窗运行，但这不是“未登录也运行”的服务账户模式。2026-09-01 16:46 的盘外按需触发证据为 `XuanJiQuant-Paper-Intraday LastTaskResult=0 / State=Ready / 无残留 Python`，未改变交易或实盘权限。

后端恢复边界（2026-08-31）：8888 正常但 8880 无监听时，先核对 `logs/backend.pid`、当前 `node server/index.mjs` 进程和最新 `server-YYYYMMDD.log`。本次旧 PID 30596 已失效，日志停在 2026-08-30 23:02:11 且没有任何 Node 致命/关闭事件，属于外部终止或宿主进程丢失。唯一恢复入口是 `node scripts/start_services.mjs`；它按端口幂等检测，只补启缺失服务。本次恢复为 backend PID 19636，Web/API 和统一账本验收 19/19，Playwright 10/10，console/page error 0。不得直接并发运行第二个 `server/index.mjs`，也不得用重启前端掩盖 API 端口缺失。

- 因子日任务：固定调用 `evaluate_factors.py`。
- 每日研究选股：`research_selection_daily` 只在同版本因子成功后调用 `generate_research_portfolio.py --once`，写入版本化组合和 `data/research/selections/latest.json` 只读指针。
- 策略周任务：固定调用 `validate_strategy_portfolios.py --once`；旧 `scan_strategies.py` 不再向策略页提供权威状态。
- Qlib 周/月/季任务：调用 `qlib_schedule.py`。
- 所有任务使用确定日程、稳定幂等键和重任务互斥。
- 成功只表示研究任务完成，`promotion_state=research_only`；调度器禁止把研究结果写成 `paper_active`、`production_candidate`、`approved` 或 `live`，不能自动晋升模拟、生产或实盘。

## 5. 旧执行关闭与 F5 唯一活动账本语义

- `server/routes/execution.mjs` 对非只读 action 返回 HTTP 409 和 `automatic_execution_disabled`。
- 旧 `quant/execution` 包、`scripts/smoke_test.py` 与 `scripts/verify_paper_rules.py` 已于 2026-08-20 删除；它们没有活动路由、任务或运行时消费者。历史文档中的文件名是审计事实，不应恢复为当前实现。
- `scripts/execution_runner.py` 不再由活动路由、驾驶舱或风险模块启动；其旧读取代码只保留历史审计兼容意义。
- `server/routes/paper.mjs` 不再暴露 Agent 生命周期或自动交易动作。
- `components/ExecutionPanel.tsx`、`components/PaperPanel.tsx`、驾驶舱、组合风险、告警、日报和行情持仓订阅统一消费 `active_account_projection`。`/api/execution` 是 F5 的只读兼容入口，不再读取旧 `execution:state`。
- `quant/data/audit.py` 只维护中性审计写入与历史查询；旧自治执行协议已删除，`commit_execution_state()` 固定失败关闭。SQLite 中已经存在的旧表和字段不删除、不改写。

F5 已按用户批准的 `docs/superpowers/specs/2026-08-19-f5-deterministic-paper-execution-design.md` 独立实现，并按 `docs/superpowers/specs/2026-08-20-f5-experimental-auto-paper-trading-design.md` 增加实验模拟通道。活动账本是 `data/paper/f5_ledger.db`，状态只有 `blocked/prepared/execution_pending/executing/reconciling/completed/completed_with_rejections/halted_unknown`。普通拒单和部分成交形成终态；只有副作用无法证明时才熔断。`f4_rejected` 不再一律等于禁止模拟：仅五项绩效失败、输入完整、约束违规为 0、未来数据违规为 0 且同代候选身份验签成功时可进入 `experimental_paper`；策略质量仍明确为 `unqualified`。任何 `f4_blocked` 或安全/身份失败继续关闭。

2026-08-26 统一账本收口：`quant.paper_execution.reporting.active_account_projection` 是当前账户唯一投影，固定返回 `ledger_authority=f5`。驾驶舱、组合风险、模拟组合和兼容 `/api/execution` 的权益、持仓数必须完全相同；F5 读取失败时不得回退旧缓存。旧 `execution:state`、旧订单和 `positions_snapshots` 未被复制、删除或改写，只能通过审计回放解释历史事实。

活动验收快照：四个当前投影的权益均为 `1023672.01`、持仓均为 10，驾驶舱/F5 当日盈亏均为 `17469.87`；告警和 tick 订阅读取同一 10 个代码。跨页面一致性已经写入 `scripts/web_verify.mjs`，任何权益差超过 0.02 或持仓数不同都会失败。最终回归为 Python `1424 passed / 2 skipped`、Node `51/51`、API `17/17`、全量功能 `42/42`、Web `19/19`、UI `23/23`，TypeScript、Vite 和浏览器控制台检查通过。

模拟组合需要同时消费 `status` 与 `account`。合并数据时使用 `{ ...accountProjection, status }`，让 runtime status 保持最高优先级；相反顺序会被账户兼容字段覆盖，错误显示“未获得模拟许可/策略质量未知”。该顺序由 `scripts/paper_ledger_ui_contract_tests.mjs` 强制检查。

2026-08-27 盘中执行单位契约：`scripts.market_data._convert_tdx_quote` 明确发布 `volume_unit=hand`，`quant.paper_execution.intraday.normalize_intraday_quotes` 必须在容量计算前乘 100 转为 `volume_unit=share`，并保留 `source_volume_unit=hand`。禁止把“手”直接交给按股计算的 participation cap。修复后的首轮自动任务在 09:35 成功形成 13/13 订单与成交、10/10 对账，运行编号 `paper_run_record_63ace902e8138d8cc5b0c7b890867234802e795bb4e7663c0b88e1c6b02a5d53`；11 单全成、2 单部分成交后取消余量。

执行页的活动上下文固定为 `status.latest_run.run_id`。`orders/fills/reconciliations` 必须先按该 run ID 过滤，再渲染本轮表格；不得用累计历史数组的原始顺序决定首屏。页面顺序为：本轮摘要 -> 当前持仓管理（只读） -> 本轮订单 -> 本轮成交与对账。持仓从 `/api/paper-execution account` 读取，页面不提供手工改仓或任意下单能力。

F5 schema v4 的 `paper_orders.sequence_no` 是执行顺序权威。`store_planned_orders` 和兼容执行写入按规划器列表序号持久化，`list_orders(run_id)` 按 `created_at, sequence_no, order_id` 恢复，防止稳定哈希 ID 打乱“卖出优先”计划。2026-08-28 已发生的 `cash_insufficient` 不回写、不补成交；它是修复前顺序缺陷的审计事实。

2026-08-30 Qlib/F4/F5 解耦已实施：`ResearchTrainingScheduler(strategy_weekly)` 只校验每日完整因子 generation，不读取 Qlib 周任务账本；公共 PIT/质量/行业/基准仍由 `validate_strategy_portfolios.py` 直接失败关闭。Qlib 周任务独立负责采集、导出、Recorder、模型、双引擎回测和自身门禁；Q1-Q4 在 F4 窗口内失败时仅为 `candidate_unavailable`。F5 不读取 Qlib job/workflow/Recorder 决定模拟许可。历史 `qlib_prerequisite_missing` 不改写。活动 Qlib job `qlib_bec23322ef1a499a` 在 2375/5435 后 owner PID 消失，已通过恢复机制记为 `interrupted/owner_lost`；当前 F4 仍是 2026-08-21 的历史 `f4_rejected`，代码解耦不等于新 F4 周期完成。回归为 Python `1434 passed / 2 skipped`、Node `51/51`、API `17/17`、全量 `42/42`、Web `19/19`、UI `23/23`、浏览器 `10/10`、控制台/page error 0，TypeScript/Vite 通过。

同日全功能复巡发现 Qlib attempt 3 在 2375/5435 再次无心跳，根因是普通增量标的批量预取缺失时仍可能进入单股多源回退。`quant/qlib/collector.py` 现只在“批量预取已实际尝试且缺失、无孤儿目标产物、无退市终止历史恢复”时快速登记 `source_batch_prefetch_unavailable`；未配置批量预取的备用调用与终止历史复用保持原语义。聚焦回归 `62/62`，最终 Python `1435 passed / 2 skipped`。job 16 已达到 ResearchJobStore 最大 3 次尝试，保持 `interrupted/qlib_collector_stalled`，本轮不得篡改 attempt 或绕过统一任务账本；2026-09-05 新周任务将以新周期幂等键恢复 incomplete manifest。8 大模块浏览器逐页签验收 `49/49`，console warning/error 与 page error 均为 0；API `17/17`、全量 `42/42`、Web `19/19`、UI `23/23`、Node `51/51`、TypeScript/Vite 通过。

F5 有两个互补时钟。`XuanJiQuant-Paper-Daily` 在周一至周五 17:10 运行日频准备/结算；`XuanJiQuant-Paper-Intraday` 在工作日 09:35-11:25 与 13:05-14:50 每 5 分钟运行，共 45 个显式周触发器，均为 `IgnoreNew`。盘中周期读取上一完整 research generation，主动刷新所需证券行情，要求当日时间戳且不超过 120 秒，然后按目标差额、硬风控、容量、涨跌停、T+1、费用与滑点立即模拟并做十项对账。同一交易日、组合和政策由稳定 run key 幂等；行情暂时失败不写失败 run，允许下一触发点恢复。17:10 位于 16:20 日终研究任务之后，避免研究完整代尚未提交时 F5 以 `selection_stale` 提前受阻。API `/api/paper-execution` 的 `run_due` 与 `run_intraday` 均不接受证券、方向、数量、价格或日期；实盘权限固定为 false。

Qlib 基准/股票池边界：`data/qlib/qlib_bin/a_share_6y_daily/instruments/all.txt` 是 provider 注册表，必须包含 `SH000300`，否则 `PortAnaRecord` 无法解析基准；`instruments/market.txt` 是 Alpha158/360 与 workflow 的研究股票池，必须排除 `SH000300`。六年 walk-forward 和季度矩阵显式使用 `market`。基准参考门禁除覆盖率外还要求最新预期交易日存在；主 AkShare 源不可用时允许将已有历史与本机 TdxQuant 指数日线增量合并，产物必须记录 `source=akshare_index_zh_a_hist+tdx_quant` 和 `source_fetch_status=tdx_quant_incremental`。2026-08-20 修复快照为 1465/1465、截至 2026-08-19、缺失 0。

2026-08-19 16:18 F5 活动验收：任务已成功注册并用 Windows Task Scheduler 实际启动，`LastTaskResult=0`；动作、参数和工作目录仅指向 `C:\Users\HYSHEN\XuanJiQuant`，安装器使用当前完整 Windows 身份，避免仅用短用户名导致 `UserId` 注册失败。活动 run 为 `blocked_by_f4`，目标交易日 `20260820`，订单/成交为 0；这与真实 `f4_rejected` 一致。API 将系统能力与当前许可分开：`paper_execution_capability=true`、当前 `paper_execution_authority=false`、`live_execution_authority=false`。真实 API 只读请求 HTTP 200，首个按需启动状态请求 408ms，其余 F5 投影 3–14ms；无令牌的任意下单先被控制面以 403 拒绝，带本机控制令牌后仍由 F5 以 HTTP 409 / `arbitrary_order_action_forbidden` 拒绝。16:20 日终研究并发更新期间，因子评估/截面版本不匹配作为 HTTP 200 的失败关闭业务状态返回，页面不沿用旧因子且不再制造 500 控制台错误。浏览器检查确认“F5 确定性模拟执行”和“F5 模拟组合”口径一致，独立初始现金 100 万、空仓、无控制台警告或错误。全量证据：Python `1025 passed / 1 skipped`、Node 契约 `48/48`、Web `15/15`、UI `23/23`、TypeScript 与 Vite 构建通过。旧 `quant.db` 的 `execution:state` 值 SHA-256 保持 `a7cc9ad7dff2d8a9d4955d4a3370e883df2162a23f8b7c2dc96a649aa088cf00`。

历史快照（2026-08-20 10:45，已被盘中路径取代）：当时 generation `2f1b4e16412487670e10eb46`、实验组合 `93f6f13b6cd7286b8d99e4855eff957795c817a316c382dac86e09b402a08731` 已满足实验模拟准入，但实现仅支持日频次日链，因此没有倒填交易。该记录仅解释设计演进，不是当前运行规则。

2026-08-20 11:13 当前盘中证据：上述 20260819 组合由独立 `paper_intraday` 链消费，行情事实为 `tdx_quant / 20260820111317`；run `paper_run_record_967f5ec2919a6d46f86e738d3626f8c57b60801f1ee23a50edb0a6d68e2cf41b` 已 `completed`，5 个订单、5 笔成交、5 个持仓，十项对账通过。1 单全成，4 单按容量部分成交并取消余量；再次运行 `idempotent=true`。计划任务在 11:15 自动触发返回 0，下一触发点继续检查但不会重复成交。驾驶舱权威状态来自 `f5_paper_runner.py::status`，显示“盘中自动模拟交易已启用”；旧 `/api/execution` 历史账本仍只读且不与 F5 金额合并。最终回归：Python `1151 passed / 1 skipped`、Node `48/48`、Web `18/18`、UI `23/23`、TypeScript、Vite 均通过，浏览器控制台错误为 0。

2026-08-20 17:24 四层健康收口：数据层截止 20260820，5201/5205、覆盖率 99.9232%；因子层完整 generation `cba7d15f62bb96d3a3a3f2b1`，58 个因子、4990 只可评估股票、覆盖 99.9616%；策略层每日 5 只组合身份有效，但真实 F4 为 `f4_rejected`，因此只显示业务警告和 `unqualified`，不冒充验证通过；执行层已为 20260821 生成 4 笔 `experimental_paper` 准备单，状态 `prepared`，实盘权限 false。`XuanJiQuant-Paper-Daily` 已改为 17:10，自动运行结果 0。系统诊断全市场覆盖查询由解析 5205 个六年 JSON 数组改为读取每条末尾 512 字节，热请求约 5.1 秒降至约 1.5 秒。最终回归：Python `1158 passed / 1 skipped`、Node `50/50`、Web `18/18`、UI `23/23`、TypeScript、Vite 均通过，浏览器控制台/page error 为 0。

## 6. 普通 LLM 边界

资讯解读、估值说明等只读解释功能可以继续使用 `scripts/llm_client.py`。统一配置来源改为 `llm:settings` 或模型注册表默认值；旧 `ai:autonomous:config` 和 `ai:scheduler:config` 不再是活动配置源。LLM 没有数据写入、研究晋升、风险放宽或订单权限。

## 7. 验证要求

每次相关改动至少运行：

```powershell
python -m pytest tests/test_agent_retirement.py tests/test_factor_dsl.py tests/test_dynamic_factor_loader.py tests/test_research_training_scheduler.py -q
python -m pytest tests/test_f5_paper_*.py -q
npm run test:contracts
npx tsc --noEmit
npm run build
```

若改动数据、风险或账本，再运行全量 Python。运行态验证必须区分页面可达、API 成功、数据新鲜度和业务完成，不得把缓存或历史记录冒充当前成功。

## 8. 禁止事项

- 不得重新增加 `quant/agent` 或以其他名称恢复自治控制器。
- 不得用浏览器或普通 API 直接创建模拟订单。
- 不得让因子/策略研究自动晋升生产。
- 不得删除或改写历史审计数据库来“清理名称”。
- 不得操作冻结备份。

## 9. 因子层输入与交付契约（2026-08-14）

数据层向因子层交付的不是“任意最新缓存”，而是
`data:snapshot:a_share_daily:latest_passed` 指向的版本化日线快照。消费顺序固定为：

1. `scripts/run_daily_research_pipeline.py` 先计算预期最新完整交易日；快照过期时调用 `scripts/daily_update.py`，后者依据完整日线覆盖率发布 `DataSnapshot`。非致命抓取错误记录在 `warnings`，不会伪装成零错误。
2. `quant/factor/input_contract.py` 校验快照日期、质量、股票池哈希和数据覆盖率，并生成 `FactorInputSnapshot`。
3. `governed_daily_bars` 只返回 `date <= as_of` 的完整日线；数据更新程序也会删除缓存中晚于权威日期的盘中日线。
4. `scripts/evaluate_factors.py` 计算 58 个技术、量价和基本面因子；pickle、轻量截面、IC 评估与每日研究组合先进入 `data/research/daily/generations/<generation>.<attempt>.staging`，暂存阶段不得更新全局因子缓存。
5. `quant/research/publication.py` 复核三产物的日期、快照、数据版本、结构、覆盖率、权限与 SHA-256，随后以 `data/research/daily/latest.json` 一次切换完整 generation；兼容镜像只在指针提交后回写。刷新期 API 读取上一完整 generation，坏指针/坏 manifest/哈希损坏均失败关闭。
6. `scripts/factor_runner.py` 只展示指针所指完整版本的评估/排名；ST、退市状态、数据过期、历史不足和零成交量股票不会进入当前排名，也不会用新股票池重筛上一完整版本。
7. `scripts/validate_strategy_portfolios.py` 同时校验 F3 因子版本、六年 PIT manifest/质量报告、有效日期行业版本和基准版本；`validation_id` 绑定 manifest 哈希、质量报告 ID、行业版本和基准版本，任一缺失或不一致即以明确 reason code 失败关闭。

确定性触发任务分为三条：`XuanJiQuant-Research-Daily`（交易日 16:20，失败后每 15 分钟最多重试 3 次）执行“全市场日线更新（仅在过期时）→ `DataSnapshot` 门禁 → 同版本因子 → `research_selection_daily` → 版本化研究组合门禁”；`XuanJiQuant-Qlib-Weekly`（周六 18:30）经 `research_training_scheduler.py --once --lane qlib` 独立认领和恢复 Qlib 数据、模型、Recorder、独立回测与自身门禁；`XuanJiQuant-Strategy-Weekly`（周日 10:00，失败后每 30 分钟最多重试 2 次）经 `--lane strategy` 独立认领 F4，调度层只校验每日完整因子 generation 的哈希、权限、日期和数据版本，随后由 `validate_strategy_portfolios.py` 直接校验 PIT manifest、质量报告、历史行业和基准。策略任务不得查询或要求本周 Qlib 周任务成功；Qlib 候选失败只隔离 Q1-Q4。三项任务均为 `IgnoreNew`；每日研究和周六 Qlib 上限为 4 小时，周日 v2 F4 上限为 12 小时。任何任务自身失败均返回非零并保留审计，不沿用旧结果冒充当前。`run_due_once` 只有在租约过期且 owner PID 已消失时才回收为 `interrupted/owner_lost`；活进程不得回收。所有研究产物继续为 `research_only`、`execution_authority=false`。

2026-08-31 增加 F4 双时钟治理：`quant/strategy/f4_readiness.py` 只读汇总每日完整 generation、六年 PIT manifest/质量、历史行业、沪深300基准和最新 F4 不可变证据，输出当前准备度而不覆盖历史 F4。`run_daily_research_pipeline.py` 在每日完整代发布后记录一次轻量 readiness；`strategy_runner.py::action_market_scan` 将其与历史 F4 证据一起投影给页面。Qlib lane 完成一次周期后重新读取公共证据；只有 readiness 为 `ready` 才创建同周 `strategy_weekly:<ISO周>:<daily_data_version>:<strategy_version>` 补偿任务，周日主任务复用同一幂等身份。F4 任务标记为 heavy，与 Qlib/其他重研究任务共享互斥，子进程超时与 Windows 任务上限一致为 12 小时。当前 `daily-pit-2020-08-16-2026-08-30` incomplete 清单继续保留为审计事实，不机械改写；下一采集代改为绑定数据层最新完整交易日。

同日盘中全量更新发现并修复两个边界缺陷。第一，`daily_update.py --financial-only` 原来把 `financial_only=True` 传入却仍传 `financial=False`，命令退出 0 但没有执行财务刷新；现改为显式启用财务分支，实测 5203/5203、错误 0，回归测试覆盖真实 CLI 参数边界。第二，Jin10 `status` 把外部 MCP DNS/传输失败上抛为 HTTP 500；现仅状态动作返回成功的降级诊断并带 `healthy=false/degraded=true/mcp_transport_unavailable`，快讯、新闻、行情和日历动作仍不得用空数据冒充成功。网络恢复后强制刷新实测快讯 20 条、新闻 14 条，巨潮最新公告/业绩快报/业绩预告/定期报告均成功。新日线快照 `a-share-daily-20260828-cc327bb7010a` 已与 generation `b8391e1c898878c661fdc29e`、58 因子和10只研究组合重新对齐；PIT 仍停在 2375/5435，09:15–15:15 安全窗拒绝 `--force` 属于设计门禁，已安排一次性 15:20 续跑，后续必须核验 manifest/quality/行业/基准及事件补跑 F4，不得提前宣称六年数据完成。

F5 模拟组合名称与盈亏投影边界：`PaperLedger.paper_positions` 继续只保存可对账的代码、数量、T+1 数量、成本价、现价与已实现盈亏，不把易变化的证券名称写进交易事实表。`quant.paper_execution.reporting.active_account_projection` 负责派生成本金额、市值、浮动盈亏、盈亏率、总盈亏和仓位占比；`runtime.load_active_account_projection` 负责从当前完整研究代及市场名称缓存补充名称。所有账户消费者必须调用 runtime 的统一入口；`scripts/f5_paper_runner.py` 不得再直接调用底层 reporting 绕过名称解析。`PaperPanel` 只展示该投影，并明确显示名称、代码、数量、可卖、当日买入、成本/现价、成本金额、市值、浮动/已实现盈亏、盈亏率、仓位占比和更新时间。该增强不授予任何新增模拟或实盘权限。

`ExecutionPanel` 与 `PaperPanel` 必须消费同一个 `account` 动作，禁止各自计算另一套账户事实。执行页可在账户投影之上组合最新 run 的订单、成交和 reconciliation，但不得用订单/成交历史反推当前持仓。两个页面的账户摘要和持仓明细字段现已统一；执行页额外保留组合 ID、验证 ID、目标交易日、熔断状态、执行通道、模拟权限以及本轮订单/成交/对账证据。

2026-08-31 盘后 Qlib 恢复证据：第一次正式重跑停在 TdxQuant 端口 `SynSent`，第二次因顶层六年起点滚动导致旧标的无法增量复用；两次错误运行均被中断并由 Qlib JobManager 记录为 `interrupted`，没有伪造成功。修复后第三次任务 `qlib_873833db653f42ec` 完成：PIT `daily-pit-2020-08-16-2026-08-31`，processed 5435、completed 5414、failed 21、manifest coverage 99.6136%；质量报告 `quality_7df8360ba33e5e901da6` passed，质量覆盖99.3540%、recent coverage99.7889%、1471交易日，重复行/非法OHLC/非正复权因子/未知ST/生命周期错误均为0。行业与沪深300基准、86640个特征文件、Workflow `workflow_f5531f5c01f45909a9e5`、Recorder `855db93440564b5a8d75b881508ea96d` 和双引擎回测均已落盘。Qlib gate rejected 的原因是窗口数及独立A股费后收益/Sharpe/回撤未达标，不得改写成基础设施失败，也不得成为 F4 总开关。F4 W36 补偿任务随后正常完成，终态与 F5 重绑定证据见下文。

F5 当前持仓、订单和成交的证券名称统一由 runtime 名称解析器补充；账本事实表仍不保存易变化名称。`active_account_projection.orders/trades` 是执行页展示名称的权威只读投影，`ExecutionPanel` 不得重新回退到独立 `orders`/`fills` 原始响应。最新运行无成交时必须显示0笔和空态，不能搬用历史成交冒充本轮；历史成交只用于审计查询。

2026-09-01 02:58 F4/F5 与全功能终态验收：ResearchJobStore job 17 已 `succeeded`，F4 发布 validation `c27ca9cd7109bf45a5e9701a64336d03e10c58bb65ba6137b83a758a7b860137`、market date 2026-08-31、factory run `fafc4f7561d779be7853a7914721835b0f92cfebf474a929ed542f182f663f9f`；8 项不可变产物哈希、完整 PIT、质量报告、历史行业、沪深300基准和 F3 代际均校验通过。业务结论为 `f4_rejected`：费后超额 -50.10%、双倍成本超额 -63.79%、Sharpe -0.0500、最大回撤 -32.04%、正超额窗口 20%，约束违规与未来数据违规均为 0，不能冒充策略合格。新增的发布后重绑定边界位于 `research_training_scheduler._strategy_handler -> generate_experimental_portfolio.generate_once`：只有当前 F4 是完整、同代且纯绩效拒绝时，才允许从当前完整 generation 的 factor/selection 和新 candidate spec 确定性重建实验选择；旧 generation 与旧 validation 继续作为不可变审计事实。当前实验组合 `b60166954bc1225c11d65d5eceb0318ce20a7c8c8860f9f8b1215a977ead32c6` 已绑定新 validation，F5 readiness 为 `experimental_paper / unqualified`，休市阻挡仅为 `outside_intraday_window`。最终回归 Python `1447 passed / 2 skipped`、Node `51/51`、API `17/17`、full `42/42`、Web `19/19`、UI `23/23`，TypeScript/Vite 通过；策略与 F5 页面身份一致、名称完整，浏览器 console warning/error 为 0。同期修正了财务新鲜度测试的季度夹具（2026Q2），避免跨月后把正确的过期判定误报为产品回归。

2026-09-01 准实时同步所有权：`config/data_sync_policy.json` 统一登记20个域的 owner、主/降级源、活动/后台周期、stale阈值、事实边界和权限。Node `MarketStreamService` 拥有热行情1秒循环和完整市场8秒目标循环；客户端只提交订阅代码，服务端合并为最多200只并强制优先包含F5持仓。hot、full-market、普通读取使用独立 `PersistentRunner`，全市场慢刷新不得堵塞热行情。SSE只允许本机/允许Origin，不在URL传token；事件带单调序号和snapshot id，慢/断客户端丢弃中间值并回退到策略目录频率。市场浏览消费完整 `market_top100`，实时行情消费 `hot_quotes`，驾驶舱消费 `cockpit_mark`；任何页面不得恢复每客户端上游轮询。

F5盯市边界：`paper_live_marks` 保存每只当前持仓的最新可信价格事实，`paper_live_account` 保存单例当前估值；二者和30秒节流的历史权益都在 `f5_ledger.db`。`f5_paper_runner.py::mark_to_market` 只接受 `action/__id/token`，代码、行情、价格、数量、现金、日期等额外字段均以 `mark_to_market_parameters_forbidden` 拒绝。它从共享缓存读取 `market:hot:snapshot:latest`，校验同日/价格/来源/逐证券stale后估值；失败只标记估值不可用，不进入交易恢复态。账户投影用live mark覆盖现价，但数量、成本、现金继续来自原交易表。`risk_runner` 把 `market_snapshot_id/valuation_as_of/calculated_at` 带入风险，workbench只在快照一致时展示实时风险；系统健康10秒、目标组合日频、情绪按来源和F5 readiness 2秒缓存均不阻塞账户首屏。

验收证据：10客户端、16只持仓、12秒负载中，热行情p95 `1039ms`、权益p95 `1462ms`、workbench暖态p95 `6ms`，上游热行情调用12次而非120次；每客户端至少12个hot、12个cockpit、1个Top100事件，订单/成交/现金/数量/成本组合哈希未变。浏览器驾驶舱三个时间连续推进、休市显示正确，实时行情显示“推送中(1s)”且2.5秒内快照计数增加3次，市场浏览Top100和资金流完整，console warning/error为0。最终回归为 Python `1442 passed / 4 skipped`、Node `57/57`、API17、full42、Web19、UI23、TypeScript/Vite通过。系统Python中的MLflow集成按可选依赖跳过，但 `.venv-qlib` 同测试通过；F4训练日期字节显式固定为纳秒，避免Pandas版本单位漂移。

财务更新恢复边界：financial 模式必须是独立隐藏进程，不得与 `server/index.mjs` 同生共死。Node manager只负责启动/控制并把PID写入 `data:update:status`；Python `refresh_financials` 继续负责 `data/financial_update_progress.json` 的 `running/interrupted/completed_with_errors/completed`、universe hash、completed/failed codes和计数。后端重启时，PID存活表示继续运行；PID消失时必须先读checkpoint，terminal checkpoint按真实终态投影，只有非terminal才标记 orphan。独立日志为 `logs/financial-update-out.log` 和 `logs/financial-update-err.log`。重启后停止动作使用持久化PID并原子改checkpoint为 interrupted。2026-09-01 真实恢复从3/5203开始，PID 37992在两次后端重启后继续到90/5203，ok90/err0；任务未结束前不得宣称全市场财务完成。

2026-09-02 自动模拟巡检边界：计划任务退出码0只证明固定入口正常退出，必须再核对当前交易日run、行情时间、订单、成交和对账。09:35至11:25入口因新浪降级行情只有时分秒而在run认领前返回 `intraday_quote_timestamp_invalid:000001`；`market_data._ensure_quote_timestamp` 现在统一补当前交易日，完整14位时间不改写。随后真实入口进入planner并暴露 `portfolio_policy_incompatible:max_orders_per_run`：16只旧持仓到10只目标产生26张差额订单。禁止把硬上限20改大；`build_order_intents` 改为卖出优先截取20张，并在每张订单写 `partial_rebalance/planned_order_count/deferred_order_count`，剩余目标留给后续合法周期。策略身份升级到 `f5-paper-policy-v2-staged-rebalance`，从而不复用v1不可变blocked运行。午间行情只接受当前交易日11:30端点做估值，仍显示`midday_break`而不是实时；连续竞价继续3秒stale门禁。11:41状态为enabled=true、kill_switch=false、paper_ready=true、outside_intraday_window、next=13:05:05，下午成交尚待真实时钟验证。修复后新鲜回归为 Python `1445 passed / 4 skipped`、Node `57/57`、API `17/17`、全功能 `42/42`、Web `19/19`、TypeScript 与 Vite 构建通过；UI 功能项 `23/23`，但因子元数据、IC 与批量 IC 仍分别约 6.1 秒、6.6 秒和 22.0 秒，性能验证保留慢响应告警。

2026-09-02 下午受控分批执行证据：13:05 的 policy v2 batch 0 为20单/20成交并10/10对账。原 `portfolio + session + policy` 单一 run key 会使递延单永远被幂等短路；活动账本迁移到 schema v6，新增默认0的 `batch_index`，历史run不改写，batch>0使用独立稳定run key。14:25 batch 1 为9单/8成交/1涨停拒单，14:30 batch 2 为4单/3成交/1涨停拒单，全部十项对账通过，实盘权限始终false。`service.run_intraday` 只在上一批为可验证终态后建立下一批，非终态继续幂等返回；每批最多20单，订单ID绑定batch run。`build_order_intents` 在后续批次消费当日该证券最早订单记录的 `target_qty`，冻结日内目标股数，避免按价格/权益变化反复产生100股级追单。`active_account_projection` 只在 live account 的run ID与最新权益批次一致时使用实时估值和marks；不一致时回到最新原子权益与持仓事实，风险页、驾驶舱、执行页和F5页面不得跨批次混合。普通 `buy_limit_up` 拒单保留为 `completed_with_rejections` 并允许后续行情周期重试，不触发kill switch。

当日终态为batch 0-5共46单/40成交，6批全部终态且各自10/10对账通过；14:50入口处于收盘安全边界，只返回成功退出而没有生成batch 6。唯一活动账户持仓9只；003039差800股、600830差9700股，两者最后原因均为`buy_limit_up`，不得倒填或冒充目标已完成。下一合法入口为下一交易日09:35。最终验证为Python `1448 passed / 4 skipped`、Node `57/57`、API `17/17`、全功能 `42/42`、Web `19/19`、TypeScript/Vite通过；14:51四页面权益统一为`1043428.34`，14:56实时估值更新为`1043042.34`。并发验证期间stderr保留8条risk runner退出告警，随后8/8连续风险请求成功且日志不再增长；该历史告警不得删除，也不代表当前API失败。

2026-09-03 日内延续证据：09:35/09:40自动完成batch 0/1，分别19单/19成交与1单/1成交，20项对账全部通过；10:40、10:45继续返回0但没有第三批，目标持仓已收敛为10只。`market-stream-risk`在09:30、09:32的两次code=1根因不是账本或交易失败，而是`_markCockpit`随1秒行情每次调用5秒风险进程，违背`cockpit_risk.active_interval_ms=2000`并造成高频进程超时。`server/market-stream-service.mjs`现维护独立`lastRiskAt/riskCalls/lastRiskError`，只在2秒到期时请求风险，超时保护至少12秒；风险请求失败不得计入hot quote failure，也不得阻断F5估值。重载后218次hot/mark对应73次risk，错误日志、last risk error和hot failure均为0；Node`57/57`、Web`19/19`、API`17/17`、TypeScript/Vite通过。

2026-09-04 服务与交易边界复核：当天policy v2盘中run为20单/20成交、10/10对账，计划任务14:50返回0；日频prepared备用run属于另一policy hash，17:10前不计为盘中成交。15:10时Web/API端口同时消失，记录PID 44232/31248均不存在，后端日志无崩溃栈且最后业务输出停于14:41，故只能归类为外部/宿主终止，不能归因于F5。通过`node scripts/start_services.mjs`幂等恢复backend 20484和frontend 39748，随后Web`19/19`、API`17/17`、Node`57/57`及四页面账户一致性通过。活动对话已建立工作日9/10/11/13/14点内每5分钟巡检；只可在端口丢失且PID死亡时调用同一恢复入口，不得并发执行F5、不得启用实盘、不得修改历史账本。

2026-09-07 执行准入断点修复：当日09:35至13:55没有policy v2盘中run，当前reason为`f4_evidence_missing`，而周五完整日频generation和实验组合实际已提交。原因是周日F4失败尝试`f4_blocked/f3_pit_date_mismatch`覆盖兼容latest，F5没有按实验组合自己的validation/factory身份找回仍在权威factory-v2指针下的已提交F4证据。`quant/paper_execution/runtime.py`现增加selection-bound解析：实验组合必须属于当前完整generation，validation/factory均为64位身份；验证目录所有声明文件逐一SHA-256复核，报告必须`f4_rejected/research_only/execution_authority=false`，候选证据仍经权威factory指针验签，F4市场日到selection日不得超过`f4_strategy.stale_after_ms`。后续失败周任务保留为策略页审计，不再错误关闭仍在有效期内且绑定完整的模拟组合；任何篡改或过期仍返回空证据。

同日14:10计划任务自动创建batch 0并成交；首批仅买入000560，暴露上一交易日`today_buy_qty/available_qty`在planner之后才归零，账户短暂11只。`PaperExecutionService.run_intraday`现仅在当前session尚无run时，把旧持仓在内存规划快照中设为`available_qty=quantity/today_buy_qty=0`，账本原子结算逻辑不变。14:15 batch 1共18单/17成交、603668因`buy_limit_up`拒单，14:20后只重试该标的；累计每批十项对账全通过。另将行情3秒展示新鲜度与F5估值拆分：`hot_quotes.stale_after_ms`保持3000，`cockpit_account.stale_after_ms=15000`，data runner发布独立`valuation_stale`，F5估值使用该字段；实机`last_marked_snapshot`恢复推进。最终接口语义允许不同snapshot的权益在0.1%内随市场波动，同一snapshot仍要求精确一致，持仓数与ledger authority始终必须一致。回归证据为Python`1452 passed / 4 skipped`、Node`57/57`、API`17/17`、全功能`42/42`、Web`19/19`、TypeScript/Vite通过。

2026-09-08 本机服务所有权修正：对话巡检再次发现8880/8888和记录PID同时消失，证明后端内部watchdog与短任务生成脱离子进程均无法在宿主死亡后可靠恢复。活动实现改为三个Windows任务：`API-Service`/`Web-Service`由隐藏PowerShell同步调用`service_host.cmd`，任务本身长期拥有Node进程，AtLogOn、无限执行、IgnoreNew、失败重启；`Service-Supervisor`每5分钟只检查这两个任务是否Running并调用`Start-ScheduledTask`。旧`Service-Watchdog`已注销且代码删除。真实杀进程测试中API 39508终止后由Supervisor恢复为40628，Web未中断；日志通过cmd原始字节追加保持UTF-8。三项服务任务没有F5脚本、run_intraday或冻结目录引用。

同轮数据事实：日线权威日期`20260907`、5203/5203覆盖；前端旧值`20260903`来自服务离线缓存。F5当天两批9单/9成交、20/20对账、10持仓。财务历史checkpoint 4081成功/1122失败已原样归档；由于运行文件只保留末尾100个failed_codes，重试集合必须用股票池减completed_codes重建，得到完整1122只。PID39988以4线程仅重试失败池，10:39:17终态completed，1122成功、0失败、failed_codes为空；000592、002693、688372抽样API与financial statements契约通过。完整5203成功数来自两次审计运行相加，不得篡改旧任务的1122失败事实。

同轮增加热行情失败退避：上游异常后按2/5/10秒退避，PersistentRunner保护窗口15秒，避免每秒重试和5秒杀进程；3秒行情新鲜度规则不变。财务PID 37992最终跨重启完成5203/5203，ok4081/err1122，checkpoint为`completed_with_errors`、stderr为空；失败代码清单保留，不能宣称5203全部成功。

`research_training_scheduler.py --once` 只有在全部到期任务成功，或该幂等任务已成功完成时才返回 0；`blocked`、`failed`、`retry_backoff`、`heavy_job_active` 等未完成状态必须返回非零，让 Windows 重试策略生效，不能把失败关闭伪装成计划任务成功。

Qlib 调度的恢复边界：更新任务本身不得要求 Qlib 在运行前已等于目标市场日或已处于完整状态；完整旧版本和带有效版本的不完整检查点都可作为恢复输入。`--lane qlib` 跨到周日后只扫描同周、同目标市场日、同调度版本的 `failed/blocked/interrupted` 原任务并复用其幂等键，不能新建平行账本。策略周任务只从哈希校验通过的每日完整 generation 取得因子前置证据，不读取 Qlib 任务账本；F4 入口直接以 PIT manifest、质量报告、历史行业和基准产物证明公共数据可用。采集器对历史失败标的只允许一次全窗口批量预取；仍缺失时保留失败、快速越过并交给覆盖率/质量门禁，不能进入可能长期占用线程的单股多源回退。历史 `qlib_prerequisite_missing` 继续作为旧调度审计事实保留，不再是当前 F4 总开关。

每日研究组合身份固定为 `research_selection_daily:<market_date>:<data_version>:<factor_version>:<f4_validation_id>:<portfolio_policy_version>`。权威读取来自日频完整 generation；`data/research/selections/latest.json` 是指针提交后的兼容镜像。组合除日期、快照、F4 身份、权限和非空持仓外，还必须绑定 F4 winner 的 `factory_run_id/candidate_id/lock_hash/policy_hash`；任一缺失或错配不得静默回退。F4 被拒绝时最多生成诊断组合，不能成为交易信号。

策略页使用两个互不替代的只读动作：`market_scan` 读取 F4 周证据，`research_selection` 读取每日组合。页面标签必须分别为“F4/PIT 数据截止日”和“当前因子/选股日”；组合表显示代码、名称、行业、研究得分、研究权重、参考收盘价和研究理由，并固定显示 `research_only / 不构成交易信号`。选股投影缺失或身份、数量、权限异常时单独失败关闭，不能遮蔽 F4 证据，也不能回退到旧目标组合或历史订单。

2026-08-19 09:35 实施验证快照：日终链以 `expected_date=20260818` 验证快照 `a-share-daily-20260818-c296a0afc64b`，覆盖率 5201/5203（99.9616%），因子 58 个；随后生成组合 `061945ec954b92e98ec6f5ccbd48a109b42d339c1189d4dcf1c077636544f965`，共 20 只股票。组合明确记录 `f4_gate_status=f4_rejected`、`selection_status=diagnostic_research_portfolio`、`promotion_state=research_only`、`execution_authority=false` 和 `not_a_trade_signal=true`。三项计划任务已按项目脚本重装：交易日 16:20 / 周六 18:30 / 周日 10:00；均为 `IgnoreNew` 与 4 小时上限。Qlib 任务的 2026-08-15 历史返回码 1 保留为历史事实；2026-08-19 使用当前入口做非到期安全检查返回 `skipped`、进程退出码 0，不能据此宣称周六完整周期已成功。

2026-08-19 14:16 页面与接口验收快照：`research_selection` 实际返回上述组合的 20 只股票，API 重启后实测约 166ms；策略页明确并列显示 `F4/PIT 数据截止日=2026-08-14` 与 `当前因子/选股日=2026-08-18`，刷新组合后 20 行和组合 ID 保持一致，浏览器控制台无 warning/error。回归结果为 Python `998 passed / 1 skipped`、Node 契约 `44/44`、Web 验证 `15/15`、UI 验证 `23/23`，TypeScript 与 Vite 构建通过。该段是时间戳验收证据，不代表 F4 已通过；交易写入仍为 `automatic_execution_disabled`。

若同一 `market_date + data_version` 的因子评估已存在，调度器必须重新校验日期、版本、58 因子非空、`research_only` 和无执行权限；全部匹配后才以 `factor_version_already_evaluated + no_op` 登记成功，不能只凭文件存在跳过计算。

2026-08-14 16:14 运行证据：权威日期 `20260814`，活动股票 5203，具备完整日线 5201，可评估 4993；因子截面 4993 行、IC 评估 58 个因子，最终 `data_end_date/latest_kline_date=20260814`。该数字是时间戳快照，不是永久常量。

2026-08-18 09:27 恢复证据：流水线发现 `snapshot=20260814 / expected=20260817` 后先更新 5203 只股票，发布 `a-share-daily-20260817-5c6ce80addbf`；5196/5203 达到预期日期，覆盖率 99.865%，质量为 `passed/fresh`，1 个非致命抓取错误保留在 warnings。随后评估 4991 只股票、58 个因子，`factor_evaluation.json` 的 `data_end_date/latest_kline_date=20260817` 且 `data_version` 与快照 `content_hash` 完全相同。API `market_eval` 返回成功，计划任务实测返回码 0。以上仍是时间戳快照，不是永久常量。

2026-08-18 17:00 故障恢复证据：16:20 计划任务以 `0xC000013A` 异常终止，日线快照已发布为 `a-share-daily-20260818-c296a0afc64b`，但因子作业 owner PID 消失且账本仍停在 `running`，导致因子 API 正确返回 `factor_evaluation_version_mismatch`。修复后调度器先将孤儿作业审计为 `interrupted`，安全退避后以 attempt 2 认领；重新评估 4990 只股票、58 个因子，日终流水线验证 `expected_date=20260818`、覆盖率 5201/5203（99.9616%）、数据版本完全一致并返回成功。该段是故障时间戳证据，不是永久数据常量。

活动阶段为 **F4 多 Alpha 候选工厂 v2**（`f4-multi-alpha-candidate-factory-v2`）。F3 同版本因子证据仍是只读输入；F4 固定使用 504/126/126 交易日、20 日 purge、5 日 embargo。注册表严格限定为 24 个预登记候选：动量、反转、防御、流动性、规则组合、Qlib 六族各 4 个；每个候选身份同时覆盖 Alpha 规格与统一 Top10 组合政策。规则族由 `f4_alpha_rules.py` 使用训练段完成确定性拟合；Qlib 族由 `f4_qlib_adapter.py` 为每个窗口建立独立 Dataset/Recorder/模型/预测产物，不可用候选只记录稳定原因，禁止规则回退。每个外层窗口执行 `train 拟合 -> 本窗口 validation 比较 24 候选 -> 原子锁定 winner -> winner-only test`；只有窗口锁定胜者可以读取 test，test 不得参与窗口纳入、候选排名或重选，崩溃恢复必须复用稳定锁。

F4 状态只有 `f4_blocked`、`f4_rejected`、`f4_research_candidate`。三者均固定为 `promotion_state=research_only`、`execution_authority=false`，不得生成目标持仓、交易信号或订单。2026-08-22 22:06 的当前真实 v2 快照为 `f4_rejected_exhausted`：数据、行业、基准、版本、目标约束和未来数据门禁均已通过，失败来自候选策略绩效，不得改写为数据异常，也不得用旧市场扫描或截面代理替代。调用链为：

```text
ResearchTrainingScheduler(strategy_weekly)
  -> scripts/validate_strategy_portfolios.py --once
  -> quant/strategy/f4_dataset.py + f4_real_pipeline.py + walk_forward.py
  -> data/research/f4/cache/<panel_id>/factor_panel.parquet + daily_rank_ic.parquet
  -> f4_alpha_contracts.py（24 候选 / 六族 / 不可变身份）
  -> f4_alpha_rules.py + f4_qlib_adapter.py（训练段拟合 / validation 评分）
  -> f4_candidate_factory.py（24 候选 validation 排名 / 候选不可用隔离）
  -> data/research/f4/factory-v2/locks/<factory_run_id>/<window>.json（test 前稳定锁）
  -> winner policy + portfolio.py + portfolio_backtest.py
  -> f4_metrics.py + f4_gate.py
  -> f4_v2_publication.py（十件套完整性与权限门禁）
  -> data/research/f4/factory-v2/<factory_run_id>/（权威不可变 generation）
  -> data/research/f4/factory-v2/latest.json（单一原子权威指针）
  -> data/research/f4/latest.json（提交后的兼容只读投影）
  -> strategy_runner.py::market_scan
  -> StrategyPanel F4 组合验证页
```

研究组合与 F5 对 v1/v2 显式分支。v2 必须同时验签 `factory_version + factory_run_id + candidate_id + alpha_spec_hash + alpha_fit_hash + 可选 model_artifact_hash + lock_hash + canonical policy hash`，并要求 selection、F4 外层与 candidate spec 内层三个版本完全一致；缺失、未知或漂移一律失败关闭。F5 单次准备只解析一次完整日频 generation，从同一代读取 selection 与 factor，禁止分别读取造成跨代撕裂。所有 v2 产物固定 `promotion_state=research_only`、`execution_authority=false`；十件套完成只证明研究流水线闭合，不授予自动模拟或实盘权限。

自适应市场状态模型由 `scripts/adaptive_regime.py` 读取活动 Qlib 数据，但固定写入项目内 `data/qlib/models/regime/`。`quant/qlib/regime_model.py` 先在 `.staging-*` 完成模型重载验证，再提交不可变 `generations/<generation_id>/regime.joblib + metadata.json`，随后更新兼容 `regime-latest.joblib`，最后以 `regime-latest.json` 作为唯一提交点。加载必须先验证指针自哈希、固定代际路径、代际 metadata 一致性及 artifact SHA-256，禁止直接信任兼容镜像。

### 9.0 当前 v2 六年真实闭环（2026-08-22）

- 权威代际：`data/research/f4/factory-v2/f8bd58748ff64ec442cf6a29446acf64fec1ae29d4ebe42110b3bd311f62c3be/`；`latest.json` 于 22:06:51 切换，factory report SHA-256 为 `b7492b57950c43d1b91abe1f3aac08ee24eb26e7ed388c60372ecec1a3163d58`，代码 manifest 为 `c90da61ce68066c1e3021e9d82df71791fa096b647182dd250f18f8bd802ec96`。exact-10 文件集、5 把唯一锁、5 个 test 窗口和三档成本产物均通过严格解析。
- 数据身份：PIT `daily-pit-2020-08-07-2026-08-21`，行业 `cninfo-008002-b092a1797ca95fba`，沪深 300 基准 `000300-3456c358743fd3c3`。运行耗时 `29605.5716s`，所以 `XuanJiQuant-Strategy-Weekly` 的 `ExecutionTimeLimit` 已由 `PT4H` 调整为 `PT12H`；每日研究和周六 Qlib 仍为 `PT4H`，三者继续 `IgnoreNew`。
- 候选事实：六族各 4 个、24/24 可用；Qlib 20 个窗口级 Recorder 全部 `FINISHED`，没有规则回退。窗口胜者为 `wf-02=Q3`、`wf-03=Q4`、`wf-04=Q3`、`wf-05=Q2`、`wf-06=D4`；前四个模型产物均有独立哈希，D4 为确定性规则候选，无模型文件。
- 门禁结论：正超额窗口 40%，1.0 倍成本费后超额 `-7.9381%`、Sharpe `-0.6218`、最大回撤 `-32.0092%`、2.0 倍成本超额 `-19.8710%`；约束违规 0、未来数据违规 0。未通过五项纯绩效门槛，状态为 `f4_rejected_exhausted / unqualified`，不是数据层、Qlib 或系统阻断，禁止事后放宽阈值。
- 兼容投影恢复：此前同一 validation ID 的 `f4_blocked/candidate_score_contract_invalid` 目录保留不改；`validate_strategy_portfolios.py` 现在把成功重试写入 `data/research/f4/recoveries/<validation_id>/<recovery_id>/`，校验后再切 `data/research/f4/latest.json`。兼容投影只从已由 `resolve_committed_v2_generation` 严格校验的代际补入 `factory_version` 与六族 `family_diagnostics`；`strategy_runner.py` 不放宽完整性门禁。当前兼容状态为 `f4_rejected_exhausted`，旧阻断只用于审计，不能继续显示为当前结论。CNINFO 的 PDF 正文解析依赖 `pypdf==6.14.2`，已同时登记在普通与隔离 Qlib 依赖清单。

### 9.0.1 2026-08-26 全功能巡检与 v2 日频交付修复

- 调度边界：`Research-Daily` 只运行 `--lane daily`，`Qlib-Weekly` 只运行 `--lane qlib`，`Strategy-Weekly` 只运行 `--lane strategy`。三项任务已重新安装并手动触发验证，结果均为 0；周末不得再认领日频因子或选股任务。Qlib 市场日以 `quality_report.data_latest_date` 为准，采集执行日只保留审计含义。
- 研究交付：完整代 `817ab83fe8c3740789093130` 于 `20260825` 发布，绑定快照 `a-share-daily-20260825-135d1182d49a` 和 data version `135d1182d49af348e292f0be1e8c66111d9e1465b3093d3066733e4ab9cd0094`；58 个因子、4969 只可评估股票、10 只 D4/v2 研究组合。`generate_research_portfolio.py` 只能通过 v2 权威 resolver 和哈希一致的 `alpha-fit.json` 补全胜者规则；带符号信号复用 F4 截面预处理，不能按不存在的 `-factor` 列直接查找。
- F5 交付：`generate_experimental_portfolio.py` 只从已验证完整 generation 的 `selection.json` 派生实验组合，禁止再次读取旧 validation 目录重算。实验组合 ID 为 `0c635bab7c396e8d3c590443af160f732a16b6c3e22d792a801d84bf345c12f3`，仍为 `research_only`、实盘权限 false。F5 对 v2 以 `candidate_id + alpha_spec_hash + alpha_fit_hash + 可选 model hash + lock_hash + canonical policy hash` 为准；外层 `nested-window-policy-v1` 是验证封装名，不得覆盖胜者的 `f4-standard-top10-policy-v2`。`status` 同时返回当前只读 readiness 和历史 `latest_run`，避免午间继续显示旧 validation 阻断；热路径使用 `resolve_committed_v2_candidate_evidence` 校验 pointer、factory report/pipeline hash 和模型清单哈希，exact-10 全量审计不放入在线请求。
- 驾驶舱：`workbench.mjs` 并行读取只读 `research_selection`，`DashboardPanel.tsx` 展示组合日期、状态、股票代码、中文名称、目标权重和中文化研究理由；该区域明确“不构成订单”。
- 状态与性能：`f5_paper_runner.py`、`reporting.py` 和 `quant/health.py` 分离当前 readiness 与历史 `latest_run`；午间当前原因为 `outside_intraday_window`，旧 `validation_identity_mismatch` 仅保留为历史 run reason。F5 候选证据由选择性 resolver 校验约 407ms，Web 冷态 F5 status 由约 14.1s 降至约 1.4–1.6s；驾驶舱热请求约 1.8–3.3s，冷启动受多个 Python runner 初始化影响可到约 4–7s。
- 当日执行证据与诊断显示：2026-08-26 13:05 的权威运行 `paper_run_record_39ac0f59342024d01da8952c2b2cb44d72ebaed707361a7825d3409c56f4bcb4` 绑定当前组合 `0c635bab7c396e8d3c590443af160f732a16b6c3e22d792a801d84bf345c12f3`，形成 12 张模拟订单、12 笔成交；账本累计 40/40 对账通过，`live_execution_authority=false`。`quant/health.py` 在当前时段已有完成运行且行情事实为本交易日时投影执行层正常；休市后 readiness 仍可显示“盘中执行窗口外”，但不能覆盖当天已完成运行的审计事实。`lib/workbench-state.mjs` 负责把当前 readiness、历史原因和 F5 reason code 结构化中文显示，禁止 `[object Object]` 与裸英文原因泄漏到页面。

### 9.1 六年 PIT 与 F4 参考数据快照（2026-08-17）

以下 9.1–9.3 均是 v1 六候选时期的时间戳审计快照；活动 v2 当前结果以 9.0 为准，不能把这些旧 ID、指标或“当前”字样解释为 v2 运行结果。

- PIT 数据版本：`daily-pit-2020-08-01-2026-08-14`；manifest 哈希 `01cd59f6c14b0c73befbd30c87275b138e9c2450f06a67ac8e736f98c20ed077`。
- 采集：5425/5425 标的，主动失败 0；`historical_failed_symbols=32` 只保留此前运行失败审计，不代表当前缺口。历史区间 2020-08-03 至 2026-08-14，共 1464 个交易日。
- 质量：报告 `quality_89583d26ec22b5b25bed`，生命周期样本 7,093,127/7,206,409（98.428%），最近应交易标的覆盖率 99.942%；重复行、非法 OHLC、非正复权因子、未知 ST 样本和非法生命周期样本均为 0。
- Qlib 导出：`data/qlib/qlib_bin/a_share_6y_daily`，5425 个 instruments、1464 个 calendar days、86800 个 feature files；`quant/qlib/exporter.py` 使用两遍流式导出，避免全市场一次性驻留内存。
- 行业：`cninfo-008002-97085abce2eeb77f`，CNINFO `008002`，5425 个标的全部查询完成，5208 个标的存在有效日期记录，样本覆盖 6,878,018/7,093,131（96.967%）。空历史保留为空，不用当前分类回填过去。
- 基准：`000300-eadcbd32c1c07c91`，沪深300覆盖 1464/1464（100%）。本次东方财富连接失败，使用 2026-08-17 09:26:06 已抓取的同周期 bars 对最终 PIT 日历重校验；产物明确记录 `source_fetch_status=cache_revalidated` 和连接错误。
- 所有数据与研究产物均为 `research_only`、`execution_authority=false`。活动 Qlib 根目录只能是 `C:\Users\HYSHEN\XuanJiQuant\data\qlib`。

2026-08-18 的 v1 六候选真实闭环已经完成。panel ID `79d8927f2f13090c469772fbe4592ce44837f9c246cde78910fe04e84fda1d8b` 绑定 PIT manifest 哈希，面板 7,095,568 行、5425 标的、47 因子；6 个窗口均完成，行业覆盖率 97.64%–99.68%。validation ID `65c264ce8f7c6af48e2b6410622c9491dffeb3f1a5509c4e90c23f6db373eeaa` 的 9 个文件哈希全部复核通过。聚合结果为正超额窗口 33.33%、费后超额 -80.04%、中位 Sharpe -0.257、最差回撤 -55.61%、双倍成本超额 -90.95%；目标约束违规 0、未来数据违规 0。因此当时 v1 候选被正确判为 `f4_rejected`。该结论不代表 v2 已运行。

### 9.2 六年 PIT、Qlib 与 v1 候选工厂历史快照（2026-08-20）

- 权威 PIT：`daily-pit-2020-08-05-2026-08-19`，manifest `completed_symbols=5426`。`data/qlib/datasets/a_share_6y_daily/raw/SZ300028.json` 是不在完成清单内的退市历史残留，只保留审计；参考构建、Qlib 导出和 F4 面板均按完成清单过滤，禁止目录遍历扩大股票池。
- Qlib：1465 个交易日、5426 个选股 instruments、86832 个 feature files；`SH000300` 有特征但从 `instruments/all.txt` 排除。训练/测试分段保留最后交易日作为执行边界，不能把边界日提前泄露给模型测试。
- 参考：行业 `cninfo-008002-b092a1797ca95fba`，5426/5426 逐标的验证到 2026-08-19，覆盖率 96.983%；基准 `000300-fb5a5c1dd0236cba`，1462/1465，覆盖率 99.795%，本次为 `cache_revalidated`，不得描述为远端新抓取。
- Qlib workflow `workflow_749cb64d96c3fbfc2b63` 的 Rank IC 0.08412、Rank ICIR 0.59329。官方引擎费后年化 21.23%、IR 1.073、回撤 -19.66%；A 股约束引擎费后总收益 -15.77%、年化 -2.91%、Sharpe -0.25、回撤 -29.75%。双引擎统一门禁为 `rejected`，原因包括样本窗口少于 4、A 股费后收益非正、Sharpe 与回撤不达标。
- 当时 F4（v1 历史）：validation `5bd6ed52437f6042711ea55854b98cbf1ef83d8596fe35f5c85dcc46d132cc58`，factory `84d991755b20cdb1b18d1ef28d3a56433058590e596d2350d0589e8566c1d676`，pipeline `f4-real-pipeline-v3-nested-candidates-gross-clamp`，panel `01f62ab82e74362fc572a809f035fe505aa85c59cf4a60008a428b1d4e872008`。5 个窗口稳定锁、6 个候选；正超额窗口 20%、费后超额 -74.37%、Sharpe 0.0136、最大回撤 -45.54%、双倍成本超额 -79.11%，约束/未来数据违规均为 0。v3 修正组合浮点累加超敞口尾差并强制更换 pipeline 身份后完整重跑；最终 `f4_rejected_exhausted`，策略质量保持 `unqualified`，但满足独立安全门禁时可进入 `experimental_paper` 本地模拟。该条不是活动 v2 结果。
- 当前项目没有 `.git`，Qlib Recorder 因此无法记录 `git diff/status`；模型产物、参数、数据身份和哈希仍保留，但代码版本追溯能力不完整。后续若建立仓库，应从当前活动目录初始化并先审计敏感/运行数据，不得从冻结备份恢复旧执行代码。
- 2026-08-20 早期验收（历史）：主 Python `1109 passed / 1 skipped`；Node `48/48`、Web `15/15`、UI `23/23`、TypeScript、Vite 均通过。当时 F5 最新 run 为 `blocked_by_f4`、订单/成交均为 0；该运行事实已被同日后续 `experimental_paper` 闭环取代，不得冒充当前状态。

目标约束与持仓漂移必须分开解释：`max_name_weight/max_industry_weight` 是调仓目标硬约束；`max_realized_name_weight/max_realized_industry_weight` 是两次调仓之间价格变化后的实际集中度。实际行业峰值最高 39.04% 是风险漂移证据，不等于目标构建器违规；若业务要求持有期间也不得超过 25%，必须另立再平衡/风险规则和新版本门禁，不能篡改本轮审计事实。

### 9.3 盘中模拟与 F4/F5 状态解耦（2026-08-21）

F4 的 `f4_rejected_exhausted` 只表示六个预登记候选没有通过样本外绩效门槛，不能晋升为合格策略或实盘；它不再被驾驶舱错误解释为“盘中自动模拟未启用”。`server/routes/workbench.mjs` 以 F5 enabled、kill switch、执行通道和当前模拟许可共同投影自动模拟状态；`components/StrategyPanel.tsx` 明确说明 F5 实验模拟准入由独立硬风控判定。

2026-08-21 09:35:35，`XuanJiQuant-Paper-Intraday` 由 Windows 计划任务自动触发并返回 0。权威运行 `paper_run_record_dd8eacf7543511c00ed29807393a44c9a7521fa6a1cf0079e3c9294e944b38c1` 使用 `tdx_quant / 20260821093504` 当前行情，执行通道 `experimental_paper`、策略质量 `unqualified`、目标交易日 `20260821`；4 张订单均形成 `partially_filled_cancelled`，共 4 笔成交，剩余数量明确取消，十项对账 10/10 通过。09:40:40 第二次计划触发同样返回 0，同一组合/日期/政策只有 1 个 intraday run，订单和成交仍为 4/4，证明幂等去重有效。`paper_execution_authority=true` 只属于本地模拟，`live_execution_authority=false` 固定不变。

同日双时钟去重边界已补齐：若盘中运行已经对同一 `portfolio_id + intended_session` 形成 `completed/completed_with_rejections` 且输入包含盘中行情，17:10 日频链不得重放昨晚准备的订单，而是把该备用运行转为 `blocked`，原因 `superseded_by_intraday`。该原因在中文页面显示为“同交易日盘中模拟已完成，日频备用单已安全作废”。相关修改位于 `quant/paper_execution/service.py`、`server/routes/workbench.mjs`、`components/StrategyPanel.tsx` 和 `lib/workbench-state.mjs`；回归证据为 Python `1160 passed / 1 skipped`、Node `50/50`、Web `18/18`、UI `23/23`、TypeScript/Vite 通过，浏览器实际验证无 warning/error。

### 9.4 2026-09-10 全功能巡检、研究证据恢复与 F5 闭环

本轮从运行证据而非计划任务返回码开始：Web/API端口正常，但`Research-Daily`上一轮为`0x40010004`，20260909日线只到3933/5205，完整研究指针仍指向20260908，实验选股却停在20260904；因此下一交易日F5先形成`f4_evidence_missing`阻断。20260908研究generation `3221a53bdf326f1cddb338f9`本身已完整提交，断点位于提交后的`generate_experimental_portfolio.py`：它再次读取了新的`f4_blocked/f3_pit_date_mismatch`兼容投影，而没有消费研究选股已经绑定的旧验证身份。

修复后的研究交付链为：

```text
daily/generations/<generation_id>/selection.json
  -> generate_experimental_portfolio.py
  -> generate_research_portfolio._load_reusable_f4_evidence
  -> experimental_selections/latest.json 中的 validation_id + factory_run_id
  -> f4/<validation_id>/validation_report.json（14天TTL、research_only、无执行权限）
  -> build_experimental_selection_from_research
  -> experimental_selections/<portfolio_id>/portfolio.json
  -> experimental_selections/latest.json
  -> runtime._bound_committed_f4_evidence（逐文件哈希复核）
  -> F5 eligibility / verifier / risk gateway / paper ledger
```

若不存在旧实验组合、验证报告缺失、验证/工厂ID不一致、超过TTL、存在未来数据或组合约束违规，加载器返回当前阻断并保持关闭；它只允许复用纯绩效不达标的不可变F4证据，不修改`f4/latest.json`的失败审计。恢复后的实验组合日期为20260908、10只股票，绑定validation `c27ca9cd...`和factory `fafc4f75...`，仍为`research_only / execution_authority=false`。

09:35 F5 batch 0形成20单/20成交，000929以`7450成交 + 2550取消`成为可验证部分成交终态；09:40 batch 1只处理剩余2550股。两批累计21单/21成交、20/20对账，持仓收敛为10只，账本`quick_check=ok`，`live_execution_authority=false`。同轮数据控制面补齐1258只20260909日线、跳过3944只、记录1个非致命抓取错误，发布快照`a-share-daily-20260909-1affbd5605fc`，5191/5203覆盖率99.7694%。因子与每日研究仍截至20260908，所以页面必须显示“已过期/仅供历史参考”，不能因为publication自身状态为completed就写成当前。

展示与调度边界同时修正：`strategy_runner.py::market_scan`允许结构有效的`f4_blocked`预检投影以HTTP 200展示业务阻断，但完整v2报告、越权和损坏证据仍失败；`research_selection`比较系统预期交易日并返回`expected_latest_date/freshness_warning`。驾驶舱风险在snapshot相同时严格一致；snapshot移动时只有同一F5账本、相同持仓数、15秒内且权益差不超过0.1%才接受，否则显示不一致。目标组合指针检查从24小时改为30秒，计算任务仍保持日频。`Research-Daily`使用16:20主触发和20:30幂等恢复触发、允许电池状态运行、`IgnoreNew`与4小时上限不变。

2026-09-10验收：Python`1458 passed / 4 skipped`；Node契约`58/58`；Web`19/19`；UI功能`23/23`、浏览器console/page error为0；TypeScript与Vite通过。接口性能中绝大多数为3–600ms，估值分析约4.5秒，系统健康因全市场尾部覆盖扫描和F5准入解析约3.6–7.1秒，属于已知只读聚合慢项。Qlib隔离环境、六年PIT质量和历史完整周期可用；2026-09-05 Qlib独立任务因TdxQuant本地HTTP和BaoStock网络失败返回1，保持独立研究故障，不得解释为F5总开关，也未在盘中擅自启动重研究补跑。
