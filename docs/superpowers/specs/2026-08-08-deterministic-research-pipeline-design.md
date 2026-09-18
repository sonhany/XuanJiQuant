# XuanJiQuant 确定性研究流水线设计

日期：2026-08-08

## 1. 目标

本设计完成四项闭环：

1. 补齐六年 A 股 PIT 日频数据并通过版本化质量门禁。
2. 清理 Qlib 控制索引中的废弃路径登记，同时保留不可变审计事实。
3. 将因子工厂和策略工厂从“Agent 可选择工具”改为交易日历驱动的确定性训练日程。
4. 将通过门禁的 Qlib 研究结果和影子因子作为只读证据接入 Agent 决策，继续禁止自动晋升 paper、production_candidate、approved 或 live。

系统仍定位为研究与模拟交易系统。本设计不授予真实交易权限，不修改硬风控阈值，不允许绕过 verifier、风险网关、Agent-only 控制面或人工生产审批。

## 2. 当前基线与问题

- 活动项目：`C:\Users\HYSHEN\XuanJiQuant`。
- 活动 Qlib 根：`C:\Users\HYSHEN\XuanJiQuant\data\qlib`。
- 冻结备份和废弃外部根不得成为运行输入。
- 2026-08-08 检查时六年数据只有一个股票原始文件；最近周任务以 `0xC000013A` 中断。
- `scripts/qlib_acceptance.py` 报告八项阻断，包括六年质量失败、模型矩阵不全、双回测缺失、shadow signal 缺失和连续调度成功不足。
- `qlib_meta.db` 中仍存在十条带废弃路径的资产登记；这些记录包含有效历史事实，但不能继续作为活动路径。
- `run_factor_factory` 与 `run_strategy_factory` 仍是 Agent 自动可选研究工具。
- Agent 上下文的 `approved_research` 目前主要来自选股器，没有统一接入经过 Qlib 质量、gate、哈希和新鲜度验证的研究证据。

## 3. 架构选择

采用独立确定性研究调度器，不把长时间训练塞入交易 Agent 周期，也不为每个工厂建立互不关联的控制面。

```text
市场数据版本 / 交易日历
  -> ResearchTrainingScheduler
       -> 日频因子训练与 IC 验证
       -> 周频策略训练与回测
       -> 周/月/季 Qlib 固定主链
       -> 独立任务账本、单实例租约、审计事件

Qlib Registry + 质量报告 + 统一 gate + 产物哈希
影子因子 + promotion history + 健康状态
  -> ResearchEvidenceProjector（只读、失败关闭）
  -> Agent context.approved_research
  -> Agent 评分、理由和目标权重
  -> verifier + risk gateway + 模拟执行边界
```

交易 Agent 只消费投影结果，不能启动、补跑、跳过或修改训练任务。

## 4. 确定性训练日程

### 4.1 日频因子

- 触发时间：每个 A 股交易日 16:20 后。
- 前置条件：数据同步完成，完整市场日期达到该交易日，因子输入快照新鲜。
- 幂等键：`factor_daily:{market_date}:{data_version}:{factory_version}`。
- 同一数据版本只产生一个终态任务；失败任务保留证据，在安全退避后按同一幂等身份补跑。
- 记录 provider、model、prompt hash、DSL hash、数据版本、IC 配置、开始/结束时间、状态和失败原因。

### 4.2 周频策略

- 触发时间：每周六 10:00。
- 前置条件：最近交易日的因子任务成功，训练/验证输入属于同一数据版本。
- 幂等键：`strategy_weekly:{iso_week}:{data_version}:{factory_version}`。
- 记录基线策略、候选参数 hash、训练/验证分段、双向成本假设、回测指标和 promotion 状态。

### 4.3 Qlib 周/月/季

- 周度：周六 18:30，运行 baseline。
- 月度：每月第一个符合条件的周六 18:30，运行 walk-forward，替代当周 weekly。
- 季度：每季度结束后的第一个符合条件周六 18:30，运行固定模型矩阵，替代当周 monthly/weekly。
- 模式优先级：`quarterly > monthly > weekly`。
- 同一时间只允许一个重型 Qlib job；任务必须登记 PID、run token、阶段、进度、心跳和终态。

## 5. 六年 PIT 数据

### 5.1 数据范围

- 当前 A 股与六年窗口内已退市 A 股的并集，排除项目既有明确不支持的市场前缀。
- 原始价、前复权价、复权因子、成交量和成交额。
- 上市日期、退市日期、历史名称变更和 ST 区间。
- 每个交易日的上市、退市、ST、停牌、涨停、跌停和可交易掩码。
- 每个产物绑定数据版本、来源、采集时间和内容哈希。

### 5.2 采集与恢复

- 使用确定顺序的符号工作队列和最多四个默认 worker；配置允许降低并发，硬上限为八。
- 每个外部源具有明确连接/读取超时、连续失败计数、临时熔断和固定降级顺序。
- 单个股票失败进入失败清单，不阻止其他股票完成。
- 每完成 25 只股票原子写入 manifest/checkpoint；重启只补失败或缺失股票。
- 已存在且哈希、schema、日期范围均匹配的产物直接复用。
- 部分完成不能被登记为质量通过，也不能进入导出或训练。

### 5.3 质量门禁

沿用 `qlib_phase1_gate_v1` 的硬条件：

- 总覆盖率不低于 98%。
- 最近窗口覆盖率不低于 99%。
- 交易日不少于 1200。
- 最新日期与预期交易日一致。
- 重复行、非法 OHLC、非正复权因子为零。
- 训练样本中的未知 ST 和非法生命周期样本为零。

覆盖率按股票在其真实上市—退市生命周期内应有的数据计算；新上市股票不因缺少上市前数据被误判，已退市股票也不因退市后无数据被误判。任何门禁失败都禁止导出、训练和研究证据发布。

## 6. Qlib 旧路径登记清理

清理过程是一次显式、可重复、带审计的迁移：

1. 只读扫描 datasets、experiments、models、workflow_runs 和 jobs 中的路径字段及嵌套 JSON。
2. 生成迁移报告，记录表、主键、原始路径、拟处理动作和目标存在性。
3. 备份 `qlib_meta.db`，记录备份和原库 SHA-256。
4. 在同一数据库事务中写入迁移审计事件并规范化活动登记。
5. 只有目标资产真实存在于当前项目 Qlib 根时才改写为当前项目路径。
6. 目标不存在时，将资产登记标记为 `invalidated` 或 `missing_historical`，清空其活动解析路径，但保留历史审计事件、原失败结果和 traceback。
7. 迁移后重新扫描，要求可被运行时解释为活动资产的废弃路径数量为零。

迁移不读取、不写入、不启动冻结备份，也不伪造缺失资产。

## 7. Agent 研究证据接入

### 7.1 Qlib 证据准入

一条 Qlib 研究证据必须同时满足：

- 数据集质量报告通过且 gate version 匹配。
- 数据日期达到当前允许的研究日期，manifest hash 与质量报告一致。
- Workflow 成功，Recorder 必需产物齐全且哈希重验成功。
- 官方 Qlib 与 A 股规则回测绑定相同 Signal Hash。
- 统一 gate 状态为 `candidate`，或存在人工哈希复核后产生的无订单 shadow artifact。
- 证据内容有限、有版本、无非有限数字、无订单或执行字段。

### 7.2 影子因子准入

- promotion state 必须是 `shadow`，健康状态不能是 quarantined/expired。
- IC、IR、样本数、分段一致性和数据日期必须可验证。
- DSL 和评估记录 hash 必须匹配。
- `execution_authority=false` 且 `can_trigger_order=false`。

### 7.3 决策使用方式

- 投影器把合格证据写入 Agent `approved_research`，每条包含 source、dataset version、signal/model/factor hash、有效期、分数和 evidence reference。
- Qlib 和影子因子可影响 Agent 的候选评分、理由、目标权重和不交易理由。
- 最终可交易股票必须与当日新鲜选股池取交集；研究证据不能扩大候选股票池。
- 研究证据失效时立即从新上下文剔除；不得沿用旧快照。
- 研究证据不可用不阻止已有仓位减仓，但不能被用于建立新仓。

## 8. 晋升和权限边界

- 从 `ai_tools.json` 删除 `run_factor_factory` 和 `run_strategy_factory`，同时删除指向它们的 Agent tool alias。
- 工厂函数保留为确定性调度器的内部调用入口，不成为 Agent planner 可见工具。
- Qlib gate 通过只能产生 `candidate` 研究证据。
- 影子因子只能作为 `shadow` 证据参与决策。
- 研究调度器无权写入 `paper_active`、`production_candidate`、`approved` 或 live 状态。
- 进入 paper 仍需现有模拟盘验证、verifier、风险网关和显式审批；live 不在本设计授权范围内。

## 9. 故障处理

- 数据不新鲜：阻断依赖训练任务并审计，不使用缓存冒充新结果。
- 外部源异常：按固定源顺序降级；熔断期间不重复占满线程；恢复后断点补跑。
- Qlib 质量失败：禁止 export、workflow、backtest 和证据发布。
- 因子失败：本日策略依赖保持 blocked，下一安全窗口补跑。
- 策略失败：保留最近已验证研究证据，但不能标记为本周新结果。
- 研究证据校验失败：仅剔除该证据并记录原因，不修改历史产物。
- 任务进程失联：租约过期后登记 interrupted；只有确认无活进程才能重新领取。
- Agent、模拟盘和真实交易权限不因研究调度失败而扩大。

## 10. 文件职责

预计新增：

- `quant/research/training_schedule.py`：纯日历、due 规则、模式优先级和幂等身份。
- `quant/research/job_store.py`：研究任务账本、租约、心跳和状态机。
- `scripts/research_training_scheduler.py`：独立 daemon、worker 调度和审计入口。
- `quant/agent/research_evidence.py`：Qlib/影子因子只读验证与有界投影。
- `scripts/qlib_path_migration.py`：dry-run、备份、事务迁移和迁移后扫描。

预计修改：

- `quant/qlib/collector.py` 与 `quant/qlib/sources.py`：有限并发、超时、熔断和 PIT 覆盖语义。
- `scripts/qlib_schedule.py`：自动选择 weekly/monthly/quarterly，保持单重型任务。
- `scripts/agent_runner.py`：把研究证据投影合并到上下文。
- `quant/agent/runtime.py`：保持研究股票与新鲜选股池交集约束。
- `ai_tools.json`：移除两个工厂工具和相关 alias。
- 服务生命周期脚本：托管研究调度器并报告状态。
- `README.md`、`docs/XUANJI_HANDOFF.md`、`docs/QLIB_LOCAL_TRAINING.md`：记录模块关系、日程、恢复和验收方法。

## 11. 测试与验收

所有行为修改采用测试先行：先增加失败测试并确认失败原因，再写最小实现。

必须覆盖：

- 日/周/月/季 due 规则、节假日、重启幂等和模式优先级。
- 单实例租约、心跳、进程失联、补跑和禁止任务重叠。
- PIT 生命周期覆盖、退市股票、ST 历史未知、部分源失败和 checkpoint 恢复。
- 路径迁移 dry-run、备份哈希、事务原子性、缺失资产失效和迁移后旧活动路径为零。
- Agent 工具清单不再暴露两个工厂。
- 合格 Qlib/影子因子进入上下文；过期、篡改、门禁失败和含订单字段的证据被剔除。
- 研究证据与新鲜选股池取交集，不能扩大交易候选。
- 调度器不能自动写入生产晋升状态。

最终验证包括：

- Qlib 定向测试和 Python 全量测试。
- 全部 Node 契约。
- TypeScript、Vite build、Web 验证、UI 验证和浏览器控制台检查。
- `scripts/qlib_acceptance.py` 返回 0，且显示 Alpha158、Alpha360、LightGBM、XGBoost、Linear、双回测、shadow signal 和至少两次同模式完整成功。
- 对六年数据的文件数、manifest、质量报告、Registry、Recorder 和 hash 做交叉核验。

## 12. 完成判定

代码完成与数据验收分开报告：

- “代码完成”要求调度、迁移、证据接入及全部软件回归通过。
- “六年 PIT 完成”要求真实采集和质量门禁通过，不能以进程运行、部分文件、缓存或旧报告代替。
- “Qlib 第一阶段验收完成”只在只读验收器返回 0 后成立。
- 任一外部数据源长期不可用导致真实数据未达门禁时，必须报告具体阻断，不能降低阈值或伪报完成。
