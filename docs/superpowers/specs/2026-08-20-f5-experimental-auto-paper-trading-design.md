# F5 实验模拟自动交易设计

## 1. 目标

本设计把“策略研究质量”和“模拟执行许可”拆成两个独立维度，使 XuanJiQuant 在策略尚未通过 F4 生产候选门禁时，仍能以明确标记、受硬风控约束、可完整审计的方式自动运行模拟交易。

系统必须在每个到期交易周期自动完成：读取权威数据与因子代际、读取研究组合、判定执行通道、生成目标差额订单、模拟撮合、更新持仓与权益、完成对账并写入独立 F5 账本。

本设计只实现本地模拟交易，不连接券商，不发送真实订单，不恢复 AI Agent，不赋予任何实盘权限。

## 2. 问题定性

当前 F5 把 `f4_rejected` 与数据缺失、证据损坏等不可执行故障统一归入 `blocked_by_f4`。这保证了研究候选不会越权执行，但也导致已经具备完整数据、因子、研究组合和模拟撮合能力的系统长期保持零订单。

需要区分两类情况：

1. **研究质量未达标**：数据和证据完整，F4 已完成，但收益、夏普、回撤或成本指标未通过。此类组合允许进入“实验模拟”通道，用真实历史之后的逐日模拟结果继续验证。
2. **执行证据不可信**：数据过期、质量失败、F4 被阻断、版本错配、组合缺失、未来数据违规、约束违规或身份验签失败。此类情况继续失败关闭，禁止生成订单。

因此，F4 门槛不会降低，也不会被改写成通过；变化仅是 `f4_rejected` 不再等同于“完全禁止模拟”。

## 3. 不变量与权限边界

- 所有研究产物继续保持 `promotion_state=research_only`、`execution_authority=false`。
- F5 的模拟许可只存在于本次运行与 F5 账本，不回写数据、因子、F4 或研究组合产物。
- `live_execution_authority` 永远为 `false`。
- `/api/execution` 与旧 `/api/paper` 的自动写入口继续关闭，不恢复旧 Agent、planner、verifier 或任意下单接口。
- `/api/paper-execution` 不接受证券代码、买卖方向、数量、价格或任意订单参数；唯一执行入口仍是无交易参数的到期周期 `run_due`。
- F5 只能收紧研究组合，不能提高目标敞口、单票上限、行业上限、ADV 参与率或绕过整手、停牌、涨跌停、T+1、现金和熔断约束。
- 任意数据身份不一致、未知副作用或对账不平必须进入失败关闭或熔断状态，不能以“实验模式”放行。

## 4. 双通道状态模型

### 4.1 策略质量状态

F5 从 F4 权威产物派生 `strategy_quality_status`：

- `validated`：F4 为 `f4_research_candidate`。
- `unqualified`：F4 为 `f4_rejected`，且拒绝原因仅来自收益、夏普、回撤、成本压力或正超额窗口比例。
- `invalid`：F4 为 `f4_blocked`，或存在数据、身份、未来数据、组合约束、证据完整性问题。

`unqualified` 不是通过，也不得在页面、API、账本或报告中显示为合格策略。允许归入 `unqualified` 的 F4 原因只有：

- `positive_excess_window_ratio_below_0_60`
- `after_cost_excess_return_not_positive`
- `sharpe_below_0_80`
- `max_drawdown_below_minus_0_20`
- `double_cost_excess_return_not_positive`

出现任何其他 F4 原因时，策略质量必须判为 `invalid`，不能进入实验通道。

### 4.2 执行通道

- `validated_paper`：策略质量为 `validated`，执行通过现有 F5 全部门禁。
- `experimental_paper`：策略质量为 `unqualified`，实验模拟开关启用，且执行通过除“F4绩效门槛”以外的全部门禁。
- `blocked`：策略质量为 `invalid`，或其他执行门禁失败。

模拟通道不改变撮合算法、风险规则或对账标准。两条通道只改变“F4绩效拒绝是否阻断模拟”这一项准入条件。

## 5. 实验模拟准入规则

进入 `experimental_paper` 必须同时满足：

1. F5 `enabled=true` 且 kill switch 未启用。
2. 配置 `experimental_paper.enabled=true`。
3. F4 状态严格为 `f4_rejected`，不得为 `f4_blocked`。
4. F4 `constraint_violation_count=0`、`future_data_violation_count=0`。
5. F4 输入状态中的 PIT manifest、PIT quality、历史行业、基准和 F3 证据全部存在并通过。
6. 研究组合来自当前完整 publication generation，日期、快照 ID、数据版本、因子版本与权威指针一致。
7. 研究组合非空，保持 `research_only`、`execution_authority=false`、`not_a_trade_signal=true`。
8. 组合的目标权重、单票、行业、总敞口、整手、ADV、停牌、涨跌停、T+1、现金和费用规则通过 F5 现有硬风控。
9. 当前周期不存在相同幂等键的已准备、执行中或终态运行。
10. 上一周期不存在无法证明副作用的 `halted_unknown`。

F4 拒绝原因必须存入本次运行，不允许删除、改名或仅保留“允许执行”的结论。

## 6. 研究组合语义

现有 `diagnostic_research_portfolio` 只保留展示和历史诊断用途，不能直接进入实验模拟。当前兼容镜像可能绑定旧 F4 validation 或旧 Top20 政策，直接复用会把不同策略的质量结论和执行结果混在一起。

研究域新增独立、版本化的 `experimental_research_portfolio`：

1. 输入必须是当前完整 factor generation 与当前 F4 权威产物。
2. F4 必须为 `f4_rejected`，且候选工厂状态为 `exhausted`。
3. 候选政策按确定性规则选择：取时间上最新的已完成外层窗口，使用该窗口在读取 test 前已经原子锁定的 validation winner。
4. 组合必须绑定 `factory_run_id + candidate_id + lock_hash + policy_hash + f4_validation_id`，不得使用默认政策或猜测 winner。
5. 组合状态固定为 `experimental_research_portfolio`，并保持 `not_a_trade_signal=true`、`promotion_state=research_only`、`execution_authority=false`。
6. 组合生成身份包含 `market_date + research_generation_id + data_version + f4_validation_id + candidate_id + policy_hash`，同一身份重跑必须字节语义幂等。

当 F4 为 `f4_research_candidate` 时，继续使用 `f4_research_portfolio`，并执行同样严格的四项 winner 身份验签。

实验组合由研究调度器生成，F5 只读取和验签，不能在执行进程中重新选股、替换政策或修改权重。

## 7. F5 运行流程

每个工作日 16:40 由既有 `XuanJiQuant-Paper-Daily` 触发：

1. 认领当前到期周期，生成稳定幂等键。
2. 捕获一次完整 research generation，并解析同身份的版本化实验组合，禁止分别读取不同代的 selection 与 factor。
3. 校验目标交易日、数据新鲜度、质量、版本、实验组合身份与研究权限。
4. 读取 F4 权威产物并派生策略质量状态。
5. 选择 `validated_paper`、`experimental_paper` 或 `blocked`。
6. 对允许通道计算“目标持仓减当前持仓”的差额订单。
7. 应用硬风险、交易规则、容量、现金、费用和整手约束。
8. 使用下一交易日可用价格进行确定性模拟撮合。
9. 将普通拒单、部分成交、剩余取消或待执行数量写成可验证终态。
10. 更新订单、成交、持仓、现金、权益和费用。
11. 执行订单、成交、现金、持仓、权益、费用、拒单、幂等键和输入身份对账。
12. 对账通过后完成运行；无法证明副作用时进入 `halted_unknown` 并启用熔断。

交易日 16:20 的日频研究流水线在因子 generation 发布完成后，使用最新 F4 锁定政策生成当日实验组合；16:40 的 F5 只消费完整产物。研究任务尚未完成、generation 正在刷新或实验组合缺失时，本轮不沿用旧组合，按既有任务重试策略等待下一次到期检查。

## 8. 账本与审计字段

F5 每次运行至少新增并持久化：

- `execution_lane`：`validated_paper` 或 `experimental_paper`。
- `strategy_quality_status`：`validated` 或 `unqualified`。
- `f4_status`、`f4_validation_id`、`f4_gate_version`。
- `f4_reasons`：完整拒绝原因数组。
- `research_generation_id`、`snapshot_id`、`data_version`。
- `portfolio_id`、`portfolio_policy_hash`。
- `experimental_policy_version`。
- `paper_execution_authority=true` 仅表示本次本地模拟获准。
- `live_execution_authority=false` 固定不变。

历史运行不改写。数据库迁移只能新增可空列或独立审计表，并为旧记录显示 `execution_lane=legacy_unknown`，不得伪造历史通道。

## 9. 配置

`config/f5_paper_execution.json` 增加版本化配置：

```json
{
  "experimental_paper": {
    "enabled": true,
    "policy_version": "f5-experimental-paper-v1",
    "allowed_f4_statuses": ["f4_rejected"],
    "require_zero_constraint_violations": true,
    "require_zero_future_data_violations": true
  }
}
```

`allowed_f4_statuses` 不允许包含 `f4_blocked`。配置加载器发现未知状态、缺失版本或试图赋予实盘权限时必须拒绝启动该通道。

## 10. API 与页面口径

F5 状态 API 必须同时返回：

- `paper_execution_capability`
- `paper_execution_authority`
- `live_execution_authority=false`
- `execution_lane`
- `strategy_quality_status`
- `f4_status`
- `f4_reasons`
- `latest_run`

页面不得再把所有 F4 拒绝统一显示为“无法执行”。应显示：

- `实验模拟自动交易`：系统正在按未通过 F4 的研究组合进行本地模拟。
- `策略质量：未通过 F4`：列出费后超额、夏普、回撤和压力成本原因。
- `模拟执行：已授权/已完成/部分成交/已阻断`。
- `实盘权限：未启用`。

实验模拟的订单、成交、持仓、权益和盈亏必须正常展示，并始终带有“未通过F4，仅用于实验模拟”的醒目标识。

## 11. 故障处理

- F4 绩效拒绝：允许实验模拟，不触发系统熔断。
- F4 数据或证据阻断：禁止执行，reason code 保留具体原因。
- 实验组合绑定旧 validation：返回 `selection_validation_mismatch`；日频研究任务必须按当前 F4 锁定政策重新生成当日实验组合。
- 数据或因子过期：返回对应新鲜度原因，禁止沿用缓存冒充当日输入。
- 普通拒单：记录拒绝原因并完成本轮，不触发系统级恢复。
- 部分成交：记录已成交量和剩余量终态，继续对账。
- 未知成交副作用或对账不平：进入 `halted_unknown`，启用 kill switch，必须人工审计。

## 12. 测试策略

实施必须遵循测试驱动，先观察失败再修改生产代码。至少覆盖：

1. `f4_rejected` 且仅绩效门禁失败时进入 `experimental_paper`。
2. `f4_blocked` 仍返回 blocked，不得实验放行。
3. 约束违规或未来数据违规仍失败关闭。
4. 实验配置关闭时 `f4_rejected` 继续阻断。
5. 当前实验组合与 F4 validation 不一致时阻断。
6. 相同周期幂等重跑不重复生成订单或成交。
7. 实验通道产生订单、成交、持仓、现金、权益和完整对账。
8. 普通拒单和部分成交形成终态，不触发未知副作用熔断。
9. API 正确区分 capability、paper authority、execution lane 与 live authority。
10. 页面明确显示实验模拟和 F4 未通过原因。
11. 任意下单 API、旧 execution 写入口和实盘权限保持关闭。
12. 现有 `validated_paper` 路径不回归。

完成后运行相关 Python 聚焦测试、完整 Python 回归、全部 Node 契约、TypeScript、Vite 构建、Web/UI 验证和浏览器控制台检查。

## 13. 完成判定

只有同时满足以下条件才算闭环完成：

1. 日频研究任务可根据当前完整因子代际和当前 F4 最新窗口锁，自动生成版本化 `experimental_research_portfolio`。
2. 到期任务可原子读取当前完整研究代际和同身份实验组合。
3. 当前真实 `f4_rejected` 策略进入 `experimental_paper`，而不是 `blocked_by_f4`。
4. 在不伪造行情、不修改 F4 结论的情况下产生真实 F5 模拟订单与确定性成交结果。
5. 订单、成交、持仓、现金、权益、费用和十项对账全部落账。
6. 重跑同一周期不重复交易。
7. 页面和 API 同时显示“F4未通过”与“实验模拟正在运行”，不再混淆研究质量和模拟执行许可。
8. `live_execution_authority=false`、旧自动执行入口关闭、任意下单永久拒绝。
9. 全部规定测试通过，README 与 `docs/XUANJI_HANDOFF.md` 更新模块关系和操作说明。

## 14. 非目标

- 不接入 QMT、PTrade、XTP、CTP 或其他券商柜台。
- 不处理真实资金、真实委托或交易所回报。
- 不恢复 AI Agent 或由大模型控制交易。
- 不降低、删除或篡改 F4 研究门槛。
- 不把实验模拟收益宣传为实盘或合格策略收益。
- 不允许页面按钮构造任意证券订单。
