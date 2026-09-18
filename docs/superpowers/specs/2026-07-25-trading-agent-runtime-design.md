# 交易 Agent Runtime 设计

更新日期：2026-07-25

## 1. 状态

已确认采用方案 B：保留确定性的量化、风控和执行内核，在其上新增可持久化、
可调用工具、可验证、可恢复的 Agent 控制平面。

本设计以自主模拟交易为首个交付目标。实盘只定义未来的受控边界，不在 P0/P1
接入真实券商，也不授权无人值守实盘。

## 2. 当前基础与核心问题

项目已经具备：

- 按盘前、盘中、收盘前、盘后和非交易日运行的 `ai_scheduler.py`。
- L1-L5 数据、因子、策略、执行建议和风险闭环。
- AI Operator、全市场选股、目标组合委员会和统一决策。
- `ai_tools.json` 白名单、`ai_verifier.py`、risk gateway 和模拟盘执行。
- `decision_id`、`run_id`、订单审计、经验记忆和失败降级。
- 模型注册表及 GLM/OpenCode 模型统一切换。

当前仍是固定工作流自动化，不是通用 Agent Runtime：

1. `ai_loop.py` 固定编排步骤，模型不能根据观察结果形成持久化任务图并重新规划。
2. 工具只有名称和风险等级，缺少统一输入、输出、幂等和副作用契约。
3. Verifier 主要校验结构、权重和规则一致性，不能可靠识别提示词复述、跑题、
   无证据结论或语义未完成。
4. LLM 异常时存在规则补齐或等权组合兜底；这适合研究展示，不应自动获得交易权限。
5. 经验记忆以摘要为主，尚未将决策、工具观察、实际结果和后续收益形成可归因样本。
6. 进程重启后缺少 Agent 步骤级检查点，不能严格证明恢复时不会重复执行副作用工具。
7. 实盘适配器仅为保护性占位，自动提交真实订单明确关闭。

## 3. 设计原则

1. **LLM 不直接接触订单接口。** LLM 只能提交结构化计划和决策候选。
2. **确定性内核拥有最终权限。** 数据时效、交易规则、仓位、现金、换手、止损、
   Kill Switch、订单幂等和券商对账不能由 LLM 覆盖。
3. **失败关闭。** 模型、数据、验证、工具或恢复状态不确定时，禁止新增风险；合法的
   风险降低动作仍由确定性风控决定。
4. **每个结论都有证据。** 决策必须引用带时间和哈希的数据或工具观察。
5. **先模拟、再影子、后受控实盘。** 不允许从研究结果直接跨越晋升状态。
6. **模型中立。** Agent Runtime 使用现有 `llm_registry.py`，一次运行固定 provider/model，
   运行中切换模型只影响下一次 Agent Run。
7. **不保存隐藏推理。** 只保存简短理由、证据引用、决策和工具轨迹，不要求或持久化
   模型的隐藏思维过程。

## 4. 非目标

- 不让 AI 执行任意 Shell、任意 Python、任意 SQL 或未登记网络请求。
- 不让 Coding Agent 在盘中修改、部署或热加载交易代码。
- 不让第二个 LLM 充当唯一风险门禁。
- 不以“达到目标权益”为理由放宽风险限制。
- 不在 P0/P1 重写因子、策略、模拟盘或风险引擎。
- 不在 P0/P1 接入真实券商或自动实盘下单。

## 5. 总体架构

```text
Market clock / manual request / alert event
                    |
                    v
              Agent Scheduler
                    |
                    v
             Agent Runtime FSM
       +------------+-------------+
       |                          |
       v                          v
 Context Builder             Checkpoint Store
       |
       v
 Planner -> Tool Registry -> Tool Executor -> Observation Validator
    ^                                             |
    +---------------- replan ---------------------+
                    |
                    v
             Decision Candidate
                    |
                    v
 Schema -> Evidence -> Semantic -> Temporal -> Portfolio -> Risk Verifiers
                    |
              pass  |  reject
                    v
       Deterministic Execution Policy
                    |
           Paper Execution Gateway
                    |
                    v
        Reconciliation / Outcome / Audit
                    |
                    v
             Evaluation Memory
```

Agent Runtime 只编排已有业务能力。研究、行情、风险和模拟盘继续由现有模块负责。

## 6. Agent 职责分离

| Agent | 运行时段 | 职责 | 最大权限 |
|---|---|---|---|
| Research Agent | 盘后/非交易日 | 数据检查、因子、策略、回测、候选晋升建议 | research |
| Market Agent | 全时段 | 行情、公告、财务、市场状态和异常观察 | read-only |
| Portfolio Agent | 盘前/盘中 | 候选池、目标权重和调仓建议 | proposal |
| Risk Sentinel | 全时段 | 确定性风险判断、止损和熔断状态 | restrict-only |
| Execution Agent | 交易时段 | 把已验证目标编译为订单意图并请求执行 | paper-guarded |
| Ops Agent | 全时段 | 进程、数据源、模型、任务超时和恢复 | operations-whitelist |
| Coding Agent | 离线 | 生成代码/策略改进提案和测试报告 | proposal-only |

Risk Sentinel 不是 LLM 风险角色的别名。它以确定性规则为准，AI只能生成解释和补充
风险线索。Coding Agent 与交易运行时使用不同的工具目录和权限域。

## 7. Agent Run 状态模型

统一契约为 `agent_run.v1`：

```json
{
  "run_id": "agent-20260725-...",
  "trigger_id": "trade-date:mode:window",
  "agent_type": "research|market|portfolio|risk|execution|ops",
  "mode": "research|shadow|paper_guarded|live_approval",
  "status": "created|observing|planning|calling_tool|validating|deciding|executing|reconciling|completed|blocked|failed",
  "provider": "opencode",
  "model": "deepseek-v4-flash-free",
  "plan_revision": 1,
  "iteration": 0,
  "context_snapshot_id": "snapshot-...",
  "current_task": {},
  "observations": [],
  "decision_id": null,
  "execution_id": null,
  "created_at": "ISO-8601",
  "updated_at": "ISO-8601",
  "deadline_at": "ISO-8601",
  "error": null
}
```

约束：

- `run_id` 创建后不可改变。
- `trigger_id` 在同一运行窗口内唯一，重复触发返回已有运行。
- provider/model 在运行创建时固定，不允许中途更换。
- 每次重新规划递增 `plan_revision`。
- 每次工具调用必须关联 `run_id`、`plan_revision` 和 `tool_call_id`。
- 只有通过完整验证链的 `decision_id` 可以进入执行状态。

## 8. 持久化与恢复

P0/P1 使用现有 SQLite，不引入新的数据库服务。新增独立表，不把完整 Agent 轨迹继续
堆入 KV：

```text
agent_runs
  run_id PK, trigger_id UNIQUE, agent_type, mode, status,
  provider, model, plan_revision, state_json, created_at, updated_at, deadline_at

agent_events
  event_id PK, run_id, seq, event_type, payload_json, created_at,
  UNIQUE(run_id, seq)

agent_tool_calls
  tool_call_id PK, run_id, plan_revision, tool_name,
  idempotency_key UNIQUE, status, input_json, output_json,
  error_json, started_at, finished_at

agent_checkpoints
  run_id PK, version, state_json, state_sha256, updated_at
```

`agent_events` 只追加不覆盖；`agent_runs.state_json` 是当前查询快照；checkpoint 与关键
事件在同一 SQLite 事务中提交。

恢复规则：

1. `created` 到 `deciding` 可以从最近 checkpoint 继续。
2. `calling_tool` 恢复时先查询 `idempotency_key`，不得直接重复执行。
3. `executing` 恢复时必须查询模拟盘订单和审计记录，再决定完成、对账或阻塞。
4. 无法证明副作用工具是否完成时，状态设为 `blocked`，不得猜测重试。
5. 超过 deadline 的运行终止为 `failed_timeout`，新开仓权限关闭。

## 9. 状态机

```text
created
  -> observing
  -> planning
  -> calling_tool
  -> validating
       -> planning       observation insufficient, iteration remains
       -> deciding       evidence sufficient
       -> blocked        hard prerequisite missing
  -> deciding
  -> validating
       -> planning       correctable semantic failure, one retry
       -> executing      all gates pass and mode permits
       -> completed      research/shadow result
       -> blocked        policy/risk rejection
  -> reconciling
  -> completed
```

默认预算：

- 盘中最多 4 次规划迭代、12 次工具调用、8 分钟运行时间。
- 盘后最多 8 次规划迭代、30 次工具调用、45 分钟运行时间。
- 同时只允许一个 `execution` Agent 进入 `executing`。
- 达到预算仍未形成有效决策时，以 `no_new_position` 结束。

## 10. 类型化工具协议

`ai_tools.json` 升级为 `ai_tools.v2`，保留现有工具名并增加：

```json
{
  "name": "run_stock_screener",
  "version": "1.0",
  "permission": "research",
  "risk": "medium",
  "side_effect": "cache_write",
  "input_schema": {},
  "output_schema": {},
  "timeout_sec": 240,
  "max_per_run": 1,
  "max_per_day": 6,
  "allowed_modes": ["research", "shadow", "paper_guarded"],
  "requires": ["fresh_market_data"],
  "idempotency": "run_id+tool+input_hash",
  "failure_policy": "return_observation"
}
```

工具类别：

- `read_only`：读取行情、财务、公告、状态和审计。
- `research`：选股、因子、策略、回测和估值。
- `cache_write`：刷新数据、保存研究候选和记忆。
- `paper_side_effect`：模拟订单和模拟调仓。
- `live_side_effect`：P0-P2 不注册；P3 以后仍需人工批准令牌。

工具执行顺序固定为：参数校验、权限校验、时段校验、依赖校验、频率校验、幂等检查、
执行、输出校验、审计、checkpoint。任何一步失败都返回结构化 observation。

## 11. Planner 与上下文

Planner 接收紧凑、版本化上下文，不直接读取整个数据库：

- 当前目标和权限模式。
- 行情、财务、公告及数据时效摘要。
- 当前持仓、现金、未完成订单和可卖数量。
- 风险状态和禁止事项。
- 已批准因子、策略和候选池。
- 本次运行已有 observation。
- 最近相关经验，不包含重复运行日志。
- 当前可用工具及输入契约。

Planner 输出只能是：

```json
{
  "goal": "...",
  "status": "need_tool|ready_to_decide|blocked",
  "tasks": [],
  "next_tool": {"name": "...", "arguments": {}},
  "evidence_refs": [],
  "summary": "简短理由"
}
```

Planner 不输出最终订单，不计算可下单数量，不修改风险参数。上下文中的“一年目标权益”
只作为展示信息；`objective_policy=advisory_only` 时不得进入仓位或交易权限计算。

## 12. Evidence 契约

所有影响交易的事实必须登记为 `evidence_ref`：

```json
{
  "evidence_id": "ev-...",
  "kind": "market|financial|announcement|factor|strategy|risk|position|tool_result",
  "source": "sqlite:daily_summary",
  "as_of": "ISO-8601",
  "content_sha256": "...",
  "freshness": "live|fresh|stale|unknown",
  "summary": "不超过300字",
  "locator": {"cache_key": "..."}
}
```

禁止把 API Key、完整提示词、未裁剪原文或任意文件路径作为 evidence。决策引用不存在、
过期或哈希不匹配的证据时验证失败。

## 13. 验证器链

验证器拆为独立、可测试的门禁：

1. **SchemaVerifier**：字段、类型、枚举、范围和版本。
2. **EvidenceVerifier**：证据存在、时间有效、哈希一致、结论有引用。
3. **SemanticVerifier**：检测提示词复述、任务未完成、股票代码错配、无依据断言和理由/动作矛盾。
4. **TemporalVerifier**：交易日、行情时点、财报可见日、决策有效期和旧模型缓存。
5. **PortfolioVerifier**：权重和、单票上限、股票池资格、现金、目标组合数学一致性。
6. **PolicyVerifier**：Agent 模式、工具权限、晋升状态、人工批准要求。
7. **RiskVerifier**：调用现有 risk gateway；只接受其结果，不能反向改写。
8. **ExecutionVerifier**：T+1、涨跌停、停牌、整手、订单次数、幂等和可执行性。

SemanticVerifier 第一阶段使用确定性检测和交叉字段验证；可增加独立模型评审作为附加证据，
但独立模型不能把确定性失败改成通过。

纠错策略：Schema/Semantic 可纠正问题最多允许一次带错误清单的重试；证据、权限、风险和执行
失败不可通过重试提示词绕过。

## 14. 决策与执行边界

统一决策升级为 `ai_decision.v2`，至少包含：

- `run_id`、`decision_id`、`plan_revision`。
- provider、model、prompt_version 和 context snapshot。
- `evidence_refs`。
- `trade_policy`、`trade_allowed` 和有效期。
- candidate_pool、target_weights 和简短理由。
- verifier results 和 risk budget snapshot。
- `execution_mode=research|shadow|paper_guarded|live_approval`。

LLM 输出目标权重后，确定性执行层负责：

1. 再次裁剪风险上限。
2. 读取最新账户和行情。
3. 将目标差异编译为订单意图。
4. 生成确定性 `client_order_id`。
5. 通过 risk gateway。
6. 模拟下单并对账。

模型失败、语义失败、证据不足或组合验证失败时，不再生成可交易的等权兜底组合。允许返回
研究用 fallback，但必须带 `execution_eligible=false`。

## 15. 记忆、结果和学习

记忆分为四类：

- `episodic`：一次 Agent Run 的目标、计划和异常。
- `evidence`：经过哈希和时间校验的事实摘要。
- `outcome`：决策后的成交、收益、回撤、滑点和风险事件。
- `policy`：人工批准的稳定规则和禁止事项。

只有 `outcome` 与原 `decision_id`、`run_id` 成功关联后，才可进入经验评估。重复的“闭环完成”
状态不再作为高价值经验。记忆可以影响研究优先级和解释，不得覆盖风险规则或自动晋升模型。

首阶段只做检索和统计归因，不让 LLM 在线更新自身权重。

## 16. 故障处理

| 故障 | 行为 |
|---|---|
| 模型超时/不可用 | 一次同模型重试；失败后 `no_new_position` |
| 模型返回非 JSON | 严格解析失败；不把自由文本补齐为可交易决策 |
| 提示词复述/跑题 | SemanticVerifier 拒绝，可纠正重试一次 |
| 数据过期或来源未知 | 禁止新增风险，允许确定性风险检查 |
| 工具超时 | 记录 observation；可重新规划，不盲目重复副作用工具 |
| 进程崩溃 | 从 checkpoint 恢复并先执行幂等/对账检查 |
| 模型在运行中切换 | 当前 Run 继续固定模型，新 Run 使用新模型 |
| Verifier 异常 | 视为失败，不允许交易 |
| SQLite 写入失败 | 阻塞运行，不执行后续副作用 |
| 模拟盘/未来券商状态不一致 | 停止新订单并进入 reconciliation_blocked |

## 17. API 与界面

P1 增加只读接口：

```text
agent_runs
agent_run_detail
agent_run_events
agent_tool_calls
agent_replay
agent_runtime_status
```

控制动作仍受本地鉴权和控制面 token 保护：

```text
agent_run_once
agent_cancel
agent_retry_blocked
```

驾驶舱只展示：当前 Agent 状态、当前任务、最近工具、验证结果、是否可交易和阻塞原因。
完整轨迹进入审计回放，不把内部提示词或长文本堆在驾驶舱。

## 18. 迁移与回滚

迁移期间禁止旧闭环和新 Runtime 同时拥有模拟交易触发权。新增配置：

```json
{
  "agent_runtime_enabled": false,
  "agent_runtime_mode": "observe",
  "execution_owner": "legacy_ai_loop"
}
```

切换顺序：

1. P0 只增加契约和验证器，`execution_owner` 保持 `legacy_ai_loop`。
2. P1 初期 Agent Runtime 以 `observe`/`shadow` 运行，只读现有结果，不触发模拟交易。
3. Runtime 回放和恢复测试通过后，先把 `execution_owner` 切到 `agent_runtime`，再允许
   `paper_guarded`；切换必须写审计事件。
4. `ai_decision.v2` 提供只读兼容适配器生成现有 `ai_decision.v1` 所需字段，
   `paper_trader.py` 在 P1 不直接解析 Planner 原始输出。
5. 旧状态键保留至少一个完整验证周期；历史审计不迁移、不覆盖、不删除。

回滚规则：

- Runtime 异常时先将模式降为 `observe`，不在同一运行窗口立即重新授权旧闭环交易。
- 经人工确认、锁和未完成订单检查后，才能把 `execution_owner` 切回 `legacy_ai_loop`。
- 回滚不删除 Agent 表、checkpoint 或失败证据。
- 任一时刻只能有一个 execution owner；启动检查发现冲突时双方均不得执行新订单。

## 19. 分阶段建设

### P0：可靠性加固

- 新增严格 Planner/Decision/Evidence 契约。
- 拆出语义、证据和时效验证。
- 非 JSON、提示词复述和语义失败默认禁止交易。
- 规则/等权 fallback 增加 `execution_eligible=false`。
- 目标权益与风险、仓位计算彻底解耦。
- 补齐工具和订单幂等测试。

P0 不改变现有调度节奏，不增加实盘能力。

### P1：Agent Runtime 模拟盘

- 新增状态机、SQLite 表、checkpoint 和恢复。
- `ai_scheduler.py` 改为触发 Agent Run。
- 把现有 L1-L5、选股、组合、验证和模拟盘封装为类型化工具。
- Planner 支持观察后最多四轮重新规划。
- 新增运行列表和审计回放 API/界面。
- 仅允许 `research`、`shadow` 和 `paper_guarded`。

### P2：评估与影子验证

- 历史决策回放和故障注入。
- 模型、提示词和 Planner 版本对比。
- 记录 shadow 决策与实际市场结果。
- 连续 30-60 个交易日验证恢复、重复订单、语义失败和风控门禁。

### P3：受控实盘边界

- 只读账户、持仓、订单和成交同步。
- 影子订单与券商可执行性检查。
- 人工批准令牌、资金上限、Kill Switch 和强制对账。
- 首阶段每张订单人工批准；不建设无人值守实盘。

### P4：有限自主实盘

只有 P3 证据满足验收后，才允许在人工预批准的策略、股票池、资金、时段和风险额度内自动执行。
任何越界、对账失败、模型异常或数据异常立即退回 `no_new_position` 或人工审批。

## 20. P0/P1 文件边界

建议新增：

```text
quant/agent/
  contracts.py       Agent、计划、证据、工具和决策契约
  store.py           SQLite run/event/tool/checkpoint 持久化
  runtime.py         状态机与预算控制
  planner.py         模型中立 Planner 适配
  tool_registry.py   类型化工具目录和权限
  verifiers.py       验证器链
  policies.py        模式、失败关闭和执行资格
  replay.py          轨迹重建

scripts/
  agent_runner.py    CLI/子进程入口
```

需要修改但不重写：

```text
scripts/ai_scheduler.py
scripts/ai_loop.py
scripts/ai_operator.py
scripts/ai_action_executor.py
scripts/ai_verifier.py
scripts/paper_trader.py
server/routes/paper.mjs
components/AutonomousSchedulingDrawer.tsx
```

## 21. 测试策略

- 契约测试：所有 schema、边界值、未知字段和版本迁移。
- 状态机测试：每个合法/非法转换、预算、取消和超时。
- 恢复测试：每个副作用点前后模拟崩溃，证明不会重复下单。
- 工具测试：输入输出、权限、时段、频率、幂等和超时。
- 语义测试：提示词复述、跑题、错误股票、无证据结论和矛盾动作。
- 风控测试：任何 Agent 输出均不能放宽 risk gateway。
- 回放测试：同一快照和模型输出产生相同确定性决策/订单编译结果。
- 安全测试：任意 Shell、路径、SQL、未登记 URL 和工具注入均被拒绝。
- 前端契约：不暴露密钥、完整提示词或隐藏推理。

## 22. 验收标准

P0 完成条件：

1. 当前已观察到的提示词复述结果被 SemanticVerifier 拒绝。
2. 非 JSON 或 LLM 故障不能产生 `execution_eligible=true` 的 fallback。
3. 每个可交易决策至少有行情、持仓、风险和策略/组合证据。
4. 所有旧测试通过，并新增失败关闭回归测试。

P1 完成条件：

1. Agent Run 可以从创建运行到模拟执行或安全结束。
2. 任意步骤崩溃后可恢复，模拟订单不重复。
3. 每个 Run、计划、工具调用、验证和订单都可按 ID 回放。
4. 模型切换只影响新 Run，历史轨迹保持原模型标识。
5. 模型、Verifier、SQLite 或工具异常时不新增风险。
6. Risk gateway 拒绝不能被 Planner、模型或人工普通配置覆盖。
7. 现有模拟盘、调度器、数据同步和驾驶舱基础功能无回归。

## 23. 已确定决策

- P0/P1 使用项目内轻量状态机，不引入 LangGraph、Temporal 或新的数据库服务。
- 持久化使用现有 SQLite，Agent 轨迹使用独立表。
- P0/P1 仅模拟盘；实盘自动提交保持关闭。
- 一次 Agent Run 固定模型。
- SemanticVerifier 可使用辅助模型，但确定性失败具有最高优先级。
- fallback 可以用于研究展示，不能自动获得交易资格。
- Coding Agent 与交易 Agent 永久隔离权限域。
- 本工作区没有有效 Git 仓库；实施阶段以测试检查点和变更文件审阅替代提交检查点，
  不擅自初始化 Git。
