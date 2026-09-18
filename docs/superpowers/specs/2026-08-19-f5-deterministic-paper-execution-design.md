# F5 确定性模拟执行闭环设计

> 状态：用户于 2026-08-19 明确批准方案 A。本规格新建独立 F5 日频模拟执行链，不复活旧 Agent、旧自动执行控制面或旧内存执行引擎。

## 1. 目标与完成口径

F5 将已经通过 F4 的每日研究组合转换为可审计的模拟订单，并闭合以下事实链：

```text
研究组合 -> F4 身份门禁 -> 模拟执行计划 -> 事前硬风控
  -> 订单 -> 成交/部分成交/拒绝 -> 现金与持仓
  -> 收盘估值 -> 对账 -> 不可变审计结果
```

“闭环完成”指工程链能够在固定合格证据上走到可验证终态，并在活动数据不合格时准确阻断。它不等于当前策略已经获准交易。当前 `f4_rejected` 组合必须落为 `blocked_by_f4`，不得生成活动模拟订单。

## 2. 权限边界

F5 只有模拟权限：

- `execution_mode=paper_daily`；
- `live_execution_authority=false`；
- 不加载或调用 `LiveBrokerAdapter`；
- 不连接 CTP、XTP、QMT、PTrade 或任何券商柜台；
- 不允许 API/UI 提交任意证券、方向、数量或成交价格；
- 不允许 AI、LLM 或 Agent 修改目标组合、订单、成交或风控结论；
- 历史 `quant.db`、旧 Agent 表和旧 `execution:state` 只读保留，不迁移、不改名、不机械清洗。

F5 的模拟授权由独立的版本化执行政策产生。研究组合继续保留 `research_only`、`execution_authority=false` 和 `not_a_trade_signal=true`；只有 F5 在验证完整身份后才能生成 `paper_execution_authority=true` 的本地模拟计划，该权限不能外溢为实盘权限。

## 3. 准入门禁

每次执行计划必须同时满足：

1. `data/research/selections/latest.json` 存在且完整；
2. `selection_status == "f4_research_portfolio"`；
3. `f4_gate_status == "f4_research_candidate"`；
4. 组合 `f4_validation_id` 与 `data/research/f4/latest.json` 完全一致；
5. 组合日期、数据快照 ID、数据哈希和当前已通过因子证据一致；
6. 组合、F4、因子和数据均为当前版本，不沿用过期 `latest`；
7. F4 组合政策、成本模型和 F5 执行政策版本可兼容；
8. F4 目标持仓数量、单票权重、行业权重、总敞口和现金要求不宽于硬风险限制；
9. F5 配置为 `enabled=true` 且 kill switch 未打开；
10. 同一 `portfolio_id + intended_session + policy_hash` 尚未完成或处于活动租约。

任一门禁失败均写入阻断运行，但不写活动订单。当前 F4 Top20 与硬风险 `max_position_count=10` 存在策略—执行兼容性缺口；F5 不得截断 Top20 或放宽硬限制来掩盖该问题。只有后续 F4 候选政策改为不超过 10 只，或用户另行批准新的硬风险版本后，才能通过该门禁。

## 4. 日频执行时序

F5 采用可复现的下一交易日开盘模拟，不冒充盘中实时交易。

交易日 16:40 运行一次确定性周期：

1. 校验日线数据流水线已发布当天完整快照；未完成则退出非零并按 15 分钟重试，最多 3 次；
2. 对上一交易日准备的计划，使用当天已治理日线的开盘价、成交量、停牌/ST/涨跌停事实模拟成交；
3. 使用当天收盘价完成持仓估值、T+1 可卖数量滚动和权益快照；
4. 完成订单、成交、现金、持仓和权益对账；
5. 消费当天 16:20 后生成的研究组合，为下一交易日准备新计划。

首个合格周期只准备计划；下一完整交易日才产生模拟成交。节假日依据治理后的交易日历跳过，不依据系统工作日猜测。

## 5. 组件边界

新增 `quant/paper_execution/`，各文件职责固定：

- `contracts.py`：状态枚举、版本、规范化、内容哈希和身份校验；
- `ledger.py`：独立 SQLite 模拟账本、事务、幂等键、租约和查询；
- `eligibility.py`：数据/F4/组合/政策准入门禁；
- `planner.py`：从目标权重与当前持仓计算差额，卖出优先、买入整手；
- `simulator.py`：下一交易日开盘成交、容量、费用、滑点、部分成交和拒绝；
- `reconciler.py`：订单—成交—现金—持仓—权益不变量；
- `service.py`：一次周期的唯一编排入口，不包含模型调用；
- `reporting.py`：只读 API/UI 投影，不直接拼接数据库内部行。

新增入口：

- `scripts/f5_paper_execution.py --once`：运行到期的日频模拟周期；
- `scripts/f5_paper_runner.py`：Web 使用的持久化只读/受控状态投影；
- `scripts/install_f5_paper_task.ps1`：安装 `XuanJiQuant-Paper-Daily`，交易日 16:40，`IgnoreNew`，失败后每 15 分钟重试 3 次，最长 2 小时。

现有 `quant/execution/engine.py`、`scripts/execution_runner.py` 和历史表不作为 F5 写入实现。旧引擎只保留兼容历史代码，不能被新路由调用。

## 6. 独立账本

活动账本固定为 `data/paper/f5_ledger.db`，SQLite 开启 WAL、外键和 busy timeout。数据库至少包含：

- `paper_runs`：运行身份、输入哈希、组合/F4/政策版本、目标交易日、状态、原因和租约；
- `paper_orders`：客户订单 ID、目标/当前/委托/成交数量、状态、拒绝原因；
- `paper_fills`：成交 ID、数量、价格、费用、印花税、滑点、容量来源；
- `paper_positions`：数量、可卖数量、当日买入、成本、收盘价和已实现盈亏；
- `paper_cash_ledger`：初始资金、成交、费用和余额变化；
- `paper_equity_snapshots`：现金、市值、权益、日盈亏和回撤；
- `paper_reconciliations`：每条不变量、期望值、实际值和判定；
- `paper_audit_events`：状态变化、阻断、拒单、成交、对账和停机事件。

每个表使用 F5 中性命名，不新增 Agent/AI 字段。`run_id`、`client_order_id`、`fill_id` 和现金流水 ID 都是确定性哈希或受唯一约束保护的稳定身份。

## 7. 状态机

运行状态仅允许：

```text
blocked
prepared
execution_pending
executing
reconciling
completed
completed_with_rejections
halted_unknown
```

规则：

- 数据/F4/政策不合格为 `blocked`；
- 合格但尚未到下一交易日为 `prepared`；
- 到期等待完整日线为 `execution_pending`；
- 事务内模拟订单和成交时为 `executing`；
- 订单终态后必须进入 `reconciling`；
- 全部一致为 `completed` 或 `completed_with_rejections`；
- 只有无法证明资金/持仓副作用是否发生时才进入 `halted_unknown`，并自动打开 F5 kill switch。

普通风控拒单、停牌、涨跌停、容量不足和部分成交都必须形成可验证终态，不得触发系统级恢复或长期 `running`。

租约过期时，只有 owner PID 已消失且数据库事务没有未完成写入，才能重新认领。幂等键相同的成功运行直接返回原结果，不能重复成交。

## 8. 订单与成交语义

- 目标差额基于上一收盘权益计算；
- 卖出订单先于买入订单；
- 买入数量向下取 100 股整手；卖出可一次清理不足 100 股的剩余持仓；
- T+1：当日买入数量当日不可卖，下一交易日转入可卖；
- 事前风险统一调用确定性风险网关并再次应用 `quant/risk/hard_limits.json`；
- 成本模型必须与 F4 validation ID 绑定，手续费、印花税、滑点和成交量参与率均写入成交证据；
- 成交量参与率造成的部分成交记录已成交数量，剩余数量在本周期终止为 `partially_filled_cancelled`；
- 停牌、买入涨停、卖出跌停、无有效价格或无完整市场事实为明确拒单；
- 不支持做空、融资融券、盘中撤改单、人工填价或浏览器手工成交。

## 9. 对账不变量

一次运行完成前必须逐项验证：

1. 每张订单的成交数量等于其全部 fill 数量之和；
2. 成交数量不超过委托数量；
3. 每张订单均处于终态；
4. 现金期末等于期初加卖出收入减买入支出减全部费用；
5. 持仓期末等于期初加买入成交减卖出成交；
6. 现金、持仓和可卖数量均不为负；
7. 当日买入未进入当日可卖数量；
8. 权益等于现金加按治理收盘价计算的持仓市值；
9. 订单、成交、现金流水和快照均绑定同一 run/portfolio/validation/policy 身份；
10. 同一幂等键没有第二组资金或持仓副作用。

任何不变量不一致均不得显示“模拟执行成功”。可确定回滚的事务失败记为失败并允许安全重试；副作用无法确定才记为 `halted_unknown`。

## 10. API 与页面

新增 `/api/paper-execution`，默认动作全部只读：

- `status`、`runs`、`orders`、`fills`、`positions`、`equity`、`reconciliations`、`audit`。

受控动作只有：

- `set_enabled`：启用或暂停后续模拟周期；
- `set_kill_switch`：立即阻止新的风险增加订单；
- `run_due`：按当前时间和幂等键运行到期周期，不能传入代码、方向、数量或价格。

受控动作必须通过项目 API token、固定 action 白名单和服务端参数模式验证。`place_order`、`fill_order`、`cancel_order`、任意目标组合上传及实盘动作始终返回拒绝。

页面调整：

- “模拟执行”展示 F5 状态、准入原因、来源组合、下次交易日、订单、成交和对账；
- “模拟组合”展示 F5 现金、持仓、权益、日盈亏、回撤和权益曲线；
- 策略页“历史模拟配置”改为“F5 模拟政策”，删除 AI/Agent、模型供应商、模型测试、旧策略和手工股票池配置；
- 页面明确区分“F5 已启用但被 F4 阻断”“等待下一交易日”“已完成并对账”“未知副作用已停机”；
- 页面不把历史 `execution:state` 与 F5 当前账本相加，历史账本仅在独立审计区显示。

## 11. 故障与恢复

- 过期数据、缺少市场事实、F4 拒绝、政策不兼容：写 `blocked`，无订单；
- 普通风控拒单：订单 `rejected`，运行可 `completed_with_rejections`；
- 部分成交：订单 `partially_filled_cancelled`，成交和剩余量同时可核验；
- 数据库事务失败且已回滚：保持待执行并安全重试；
- 进程退出：下轮按租约、PID 和事务证据恢复；
- 对账不平或副作用未知：`halted_unknown`、开启 kill switch、禁止后续风险增加订单；
- 恢复必须产生审计事件，不能删除失败运行或覆盖原始原因。

## 12. 测试要求

必须先有失败测试，再写实现。覆盖：

- F4 rejected、身份错配、过期数据和政策不兼容均不生成订单；
- 合格固定组合从准备到下一交易日开盘成交、收盘估值和对账；
- 重复运行不重复订单、成交或现金流水；
- 买入整手、卖出零股、T+1、停牌、涨跌停和现金不足；
- 费用、滑点、容量和部分成交终态；
- 普通拒单不触发系统停机；
- 回执/事务未知触发 `halted_unknown` 和 kill switch；
- owner 丢失恢复、活动 owner 不回收；
- API 白名单、鉴权和任意下单拒绝；
- UI 状态、中文原因、订单/成交/对账展示；
- 历史 `quant.db` 和 `execution:state` 在 F5 测试前后哈希/计数不变；
- 全量 Python、全部 Node 契约、TypeScript、Vite、Web/UI 与浏览器控制台验证。

端到端成交测试使用临时数据库、固定 F4 candidate、固定两日行情和固定时钟；不得篡改活动 F4 结果来制造成功。活动运行验收预期首先显示 `blocked_by_f4` 或 `portfolio_policy_incompatible`，直到真实研究证据通过全部门禁。

## 13. 实施顺序

1. 契约、状态机和独立账本；
2. 准入门禁和策略—风控兼容性检查；
3. 目标差额、订单和模拟成交；
4. 现金、持仓、权益和对账；
5. 服务编排、幂等、租约和恢复；
6. API、计划任务和 UI；
7. 文档、全量回归和活动阻断验收。

不得先开放 API 写入再补账本或对账，也不得通过修改活动 F4 状态、降低 F4 门槛或放宽硬风险来完成演示。

## 14. 最终交付判定

F5 只有同时满足以下条件才算交付：

- 固定合格证据端到端产生模拟订单、成交、持仓、现金、权益和通过的对账记录；
- 活动 `f4_rejected` 证据端到端写入明确阻断且零活动订单；
- 重启和重复调度不产生重复副作用；
- 所有订单都有终态，所有完成运行都有对账结论；
- 受控页面能解释“为何执行/为何阻断/发生了什么/账是否一致”；
- 真实券商、旧 Agent、任意手工订单和旧执行写路径仍保持关闭；
- README、`docs/XUANJI_HANDOFF.md` 和系统工作流图记录新旧边界及运维方法；
- 全部规定测试与运行态验收通过。

