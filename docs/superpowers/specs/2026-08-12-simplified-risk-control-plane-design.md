# 简化风险控制面设计

## 目标

将驾驶舱和模拟执行页面中的风险状态收敛为四个互不重叠的权威域：综合风险、系统安全门、Agent 当前策略、最终交易模式。保留全部逐单硬风控，不降低阈值，不改变 `paper_guarded`、verifier、Agent-only 或审计边界。

## 权威状态

- `overall_risk`：`low / medium / high / unknown`，仅为监控摘要，`advisory_only=true`，不得直接批准订单。
- `safety_gate`：`open / closed`，只处理数据、账本、服务、严重告警与硬熔断等系统级阻断，并返回稳定原因码和中文主原因。组合风险等级无论低、中、高都不得直接关闭安全门。
- `agent_decision`：保留 Agent Runtime 的当前状态、策略和 `execution_eligible`，任何页面不得根据其他布尔值推测 Agent 策略。
- `effective_mode`：唯一面向页面的最终交易模式：`system_closed / waiting_agent / normal / reduce_only / no_new_position`，同时返回一个主原因。
- `order_limits`：声明 `per_order_gateway`，携带单票与总敞口解释性证据；实际批准权仍只属于 `quant/risk/gateway.py`。

## 决策顺序

1. 风险引擎生成组合指标；宏观上下文完成 30 分钟新鲜度校验；两者取最严等级形成只读综合风险。
2. 系统安全门检查关键接口、账户、风险数据、宏观新鲜度、系统健康、严重告警、日亏损/最大回撤硬熔断和 Kill Switch；组合风险等级无论低、中、高都只进入摘要。
3. 安全门关闭时，最终模式固定为 `system_closed`。
4. 安全门开启但 Agent 当前不可执行时，最终模式为 `waiting_agent`，不得显示成减仓或禁止新增。
5. Agent 当前可执行时，最终模式严格采用当前 Agent 的 `normal / reduce_only / no_new_position` 策略；未知策略失败关闭为 `waiting_agent`。
6. `normal` 只允许订单进入 verifier 和逐单风险网关，不代表订单必然通过。

## 兼容与页面

暂时保留 `risk_overview` 和 `trade_permission` 作为兼容投影，但页面只能消费 `overall_risk`、`safety_gate`、`agent_decision`、`effective_mode` 和 `order_limits`。驾驶舱主区只显示综合风险、系统安全门、Agent 当前策略、当前交易模式；详细指标和逐单阈值保留在下方。

## 完成判定

- 组合风险 `medium` 不改变安全门或 Agent 策略。
- Agent 等待、恢复、失败、盘外状态只形成 `waiting_agent`，不冒充 `reduce_only`。
- 安全门关闭优先于 Agent 策略。
- 当前可执行 Agent 的三种策略分别映射到相同名称的最终模式。
- 前端不再读取 `trade_permission.allowed / strategy_policy / new_position_allowed` 推导展示。
- 风险网关全部既有测试保持通过，硬阈值无变更。
