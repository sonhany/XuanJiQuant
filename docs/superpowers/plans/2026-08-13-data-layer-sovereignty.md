# XuanJiQuant Data Layer Sovereignty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将市场数据写权限收敛到数据层，让 Agent、模拟交易、因子、策略、风控和执行只读消费经过质量门禁的数据产品。

**Architecture:** P0 保留现有 SQLite 和数据适配器，先用契约测试切断所有越层补数与反向依赖；数据过期统一失败关闭并提交数据需求，不在业务流程内采集。P1 再增加版本化 `DataSnapshot` 发布与 Reader，逐层迁移消费者；Qlib 研究仓始终物理和语义独立。

**Tech Stack:** Python 3、SQLite、pytest、Node.js ESM、React/TypeScript、Vite。

---

## 文件结构与职责

- `quant/data/source_policy.py`：数据产品到固定来源链的声明，不承载交易逻辑。
- `quant/data/sync_service.py`：盘中数据采集与发布；不依赖 Agent。
- `scripts/daily_update.py`：数据层确定性盘后批任务，只有数据控制面/外部调度调用。
- `scripts/data_runner.py`：数据只读查询与受控采集适配；P1 再拆读写 runner。
- `scripts/sync_runner.py`、`server/routes/sync.mjs`：显式数据管理控制面。
- `ai_tools.json`、`scripts/ai_action_executor.py`：移除数据写工具后只保留 Agent 研究/验证/模拟执行工具。
- `scripts/paper_trader.py`：数据过期只失败关闭，不补数。
- `scripts/ai_data_agent.py`、`server/routes/paper.mjs`：移除旧五层自动补数与一键混合运行；历史投影只读保留到消费者迁移完成。
- `quant/data/snapshot.py`（P1 新建）：版本化发布合同与只读 Reader。
- `tests/test_data_layer_boundaries.py`（P0 新建）：跨层依赖与权限架构契约。

### Task 1: 建立数据层主权架构契约（已完成）

**Files:**
- Create: `tests/test_data_layer_boundaries.py`

- [ ] 编写失败测试，断言 `ai_tools.json` 不含 `refresh_data` 和 `run_daily_update` 别名。
- [ ] 编写失败测试，断言 Agent 执行器不导入或调用 `sync_universe/incremental_klines`。
- [ ] 编写失败测试，断言 `paper_trader.py` 不在交易路径调用 `daily_update`。
- [ ] 编写失败测试，断言 `sync_service.py` 不导入 `quant.agent`。
- [ ] 编写失败测试，断言纸面 API 不再提供 `ai_data_run auto_fix` 与 `ai_all_run`。
- [ ] 单独运行测试，确认均因现有越层代码而按预期失败。

### Task 2: 移除 Agent 数据写权限（已完成）

**Files:**
- Modify: `ai_tools.json`
- Modify: `scripts/ai_action_executor.py`
- Modify: `quant/agent/planner.py`（仅在现有提示依赖该工具时）
- Modify: `tests/test_agent_tool_registry.py`
- Modify: `tests/test_ai_action_executor_registry.py`
- Modify: 其他直接断言旧工具清单的测试

- [ ] 从工具清单移除 `refresh_data`，并删除 `run_daily_update` 别名。
- [ ] 删除执行器中 `refresh_data` 分支。
- [ ] 将旧执行账本和 Agent Run 中的 `refresh_data` 保留为历史审计事实，不改写数据库。
- [ ] 更新测试期望：数据过期时 Agent 返回阻挡或等待数据发布，不调用写工具。
- [ ] 运行工具注册、Agent Runtime、恢复和执行器测试。

### Task 3: 模拟交易数据过期失败关闭（已完成）

**Files:**
- Modify: `tests/test_data_layer_boundaries.py`
- Modify: `scripts/paper_trader.py`
- Modify: 相关模拟交易新鲜度测试

- [ ] 写行为测试：日线过期时不调用网络采集、不写 K 线，返回 `data_not_ready`/兼容跳过原因。
- [ ] 运行测试确认旧自动补数路径导致失败。
- [ ] 删除交易器内部 `incremental_klines` 调用及重新加载分支。
- [ ] 保持原有失败关闭、无订单、无成交语义。
- [ ] 运行模拟执行、风险网关、账本和 Agent 闭环相关测试。

### Task 4: 删除旧 AI 数据补数和五层一键入口（已完成）

**Files:**
- Modify: `scripts/ai_data_agent.py`
- Modify: `server/routes/paper.mjs`
- Modify: `tests/test_ai_data_factor_adaptation.py`
- Modify: Node 路由契约测试

- [ ] 写失败测试：`run_data_agent` 不接受 `auto_fix`，且模块不含 `execute_replenish`。
- [ ] 写失败测试：`ai_data_run` 只能读取数据层状态或被明确废止；`ai_all_run` 不存在。
- [ ] 删除 K 线/财务补数函数和 CLI `--auto-fix`。
- [ ] 把旧数据 AI 输出降为解释性历史投影，不再产生 `trade_allowed` 权威值。
- [ ] 更新 `ai_risk_agent` 和 Agent 上下文，使当前数据质量来自确定性 `project_data_quality(cache=...)`，不信任旧 AI 状态。
- [ ] 运行数据质量、风险、Agent 上下文和纸面 API 契约测试。

### Task 5: 切断数据层对 Agent 的反向依赖（已完成）

**Files:**
- Modify: `quant/data/sync_service.py`
- Modify: `quant/agent/realtime.py` 或 Agent 调度消费者（仅在需要恢复只读消费时）
- Modify: `tests/test_sync_service_status.py`
- Modify: `tests/test_agent_realtime.py`

- [ ] 写失败测试，断言同步服务发布报价后不直接调用 Agent。
- [ ] 删除 `process_quote_snapshot` 导入和 `sync_agent_realtime()`。
- [ ] Agent 快路径改为自己读取已发布 `stock:realtime:*` 快照；不得取得订单权限。
- [ ] 验证实时报价 TTL、持仓估值和 Agent 监控语义不回退。

### Task 6: 收紧读写控制面

**Files:**
- Modify: `scripts/data_runner.py`
- Modify: `scripts/sync_runner.py`
- Modify: `server/routes/data.mjs`
- Modify: `server/routes/sync.mjs`
- Modify: 数据浏览与同步契约测试

- [ ] 列出 `/api/data` 所有可能请求外部源或写缓存的 action。
- [ ] 为纯读 action 增加测试：不得更新历史市场事实。
- [ ] 把显式采集/更新 action 收到 `/api/sync`，带幂等、互斥和审计。
- [ ] 保留实时展示缓存，但必须返回来源、业务时点、新鲜度和覆盖口径。
- [ ] 运行所有数据浏览、Top100、实时行情、财务和同步控制面契约。

### Task 7: 建立版本化数据发布合同（P1，合同与日线发布已完成；消费者迁移待 Task 8）

**Files:**
- Create: `quant/data/snapshot.py`
- Create: `tests/test_data_snapshot_contract.py`
- Modify: `scripts/daily_update.py`
- Modify: `quant/data/control_plane.py`

- [ ] 先写 `DataSnapshot` schema、时点、覆盖、哈希、来源链和质量状态测试。
- [ ] 实现不可变发布清单和只读 Reader；失败发布不得覆盖最后通过版本。
- [ ] 日 K、实时监控集和财务批任务分别发布独立数据产品。
- [ ] 控制面同时展示服务存活、任务状态、数据业务时点、发布时点、覆盖和质量。
- [ ] 运行快照损坏、部分覆盖、源冲突、过期和原子发布测试。

### Task 8: 逐层迁移消费者（P1）

**Files:**
- Modify: 因子输入适配器与测试
- Modify: 策略扫描/回测输入适配器与测试
- Modify: 风险定价输入适配器与测试
- Modify: 执行实时行情 Reader 与测试
- Modify: Agent context/decision evidence 与测试

- [ ] 因子结果记录 `data_snapshot_id/as_of`，禁止边算边采集。
- [ ] 策略信号记录因子和数据版本，过期时失败关闭。
- [ ] 风控区分行情业务时点和风险计算时点，不让宏观/AI 改硬阈值。
- [ ] 执行只消费实时行情发布和交易账本，绝不补历史数据。
- [ ] Agent 只读消费各层已发布证据；计划必须绑定版本。
- [ ] 增加跨层一致性和可回放测试。

### Task 9: 文档、全景图与全量验收

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Modify: ComfyUI 式本地全景图数据（若该图已纳入项目维护）

- [ ] 记录数据产品、来源、更新周期、存储、质量门禁和五层权限矩阵。
- [ ] 标注旧 `ai:data:latest`、旧五层入口和历史工具账本为历史兼容事实。
- [ ] 更新图中的唯一写入链、只读依赖、数据版本和失败关闭路径。
- [ ] 运行相关与全量 Python 测试、全部 Node 契约、TypeScript、Vite 构建、Web/UI 验证和控制台检查。
- [ ] 只读核对 SQLite `quick_check`、覆盖、新鲜度、数据源回执和服务运行态。
- [ ] 检查规格、计划和文档无 `TODO/TBD`、无不受证据支持的生产完成声明。

## 实施顺序和回滚

- P0 按 Task 1→5 执行；每个任务先红灯、后最小实现、再局部回归。
- Task 6 在 P0 边界稳定后执行，防止同时改变页面查询语义和底层写权限。
- Task 7→8 是 P1，不与 P0 同批切换；先双读验证，再逐层迁移，最后删除兼容投影。
- 任一阶段若发现下游仍依赖被移除的写入口，保持失败关闭并恢复该阶段代码，不回写数据库历史。
- 当前目录无 Git 元数据，无法通过提交回滚；实施时必须记录文件清单、测试输出和数据库只读校验，且不执行破坏性数据迁移。
