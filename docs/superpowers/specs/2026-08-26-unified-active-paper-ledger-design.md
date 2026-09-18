# 统一活动模拟账本设计

## 目标

`data/paper/f5_ledger.db` 是唯一活动模拟账户事实源。投资驾驶舱、组合风险、综合风险、告警、日报、行情持仓订阅、模拟执行、模拟组合以及只读 `/api/execution` 必须投影同一现金、持仓、权益、当日盈亏、订单、成交和时间戳。

## 问题事实

当前运行时存在三个读口径：驾驶舱读取旧 `execution:state` 的缓存估值，组合风险读取旧 `execution:state` 后再次套用行情，模拟组合读取 F5 SQLite。2026-08-26 的同刻证据分别为驾驶舱权益 1,022,388.31、风险权益 1,034,812.22、F5 权益 1,023,672.01；持仓数量分别为 8、8、10。差异来自数据源分裂，不是市场价格变化。

## 权威边界

- 活动账本：`data/paper/f5_ledger.db`。
- 活动投影：`quant.paper_execution.reporting.active_account_projection`。
- 历史审计：旧 `execution:state`、`positions_snapshots`、旧订单、旧成交和旧数据库字段保持原样，只能由审计回放读取。
- 禁止把旧现金、持仓或成交复制到 F5；否则会重复计算成本、资产和收益。
- 实盘权限继续固定为 false；本设计不增加下单参数、实盘接口或风险绕过能力。

## 数据流

```text
F5 PaperLedger
  -> active_account_projection
     -> f5_paper_runner account/all/status/positions/orders/fills
     -> /api/paper-execution
     -> /api/execution 只读兼容别名
     -> /api/workbench 驾驶舱
     -> risk_runner portfolio_risk
     -> alert_runner
     -> tick_collector 持仓订阅
     -> daily_report
```

`/api/execution` 保留现有只读动作名，写动作仍返回 `automatic_execution_disabled`；其读取结果改为 F5 投影。`scripts/execution_runner.py` 不再由活动路由、驾驶舱或风险模块启动，只作为历史审计兼容代码保留，后续可在单独清理任务中删除。

## 投影契约

统一投影必须包含：

- `ledger_authority = "f5"`
- `ledger = "data/paper/f5_ledger.db"`
- `account.initial_capital/cash/market_value/total_equity/daily_pnl/total_pnl/total_pnl_pct/position_count/updated_at`
- `positions`：当前非零 F5 持仓列表
- `orders`：F5 模拟订单
- `trades`：F5 模拟成交
- `equity_history`：按时间升序的 F5 权益序列

总权益以最近一次已对账的 `paper_equity_snapshots` 为准；没有快照时才使用现金加持仓市值计算。所有消费者必须保留 `ledger_authority`，不得静默回退到旧缓存。

## 故障处理

- F5 账本无法读取时，驾驶舱、风险和告警明确返回 `active_paper_ledger_unavailable`，不得回退旧账本。
- 空账户是合法状态：初始现金、零持仓、零风险。
- 历史 F5 运行失败不覆盖当前已对账账户事实。
- 兼容 `/api/execution` 的写动作继续 HTTP 409 失败关闭。

## 页面要求

- 驾驶舱标明“统一 F5 模拟账本”，权益、今日盈亏、持仓数量与模拟组合完全一致。
- 组合风险的 `position_count` 和 `total_equity` 与驾驶舱一致。
- 模拟组合删除“不与历史执行账本合并”的提示，改为“全系统唯一活动模拟账本”。
- 旧账本只能在审计回放中以“历史审计”标签出现。

## 完成判定

1. 驾驶舱、组合风险、模拟组合、`/api/execution` 四处权益和持仓数量一致。
2. 告警和 tick 持仓订阅只使用 F5 当前持仓。
3. 日报 `account_source` 为 `f5_ledger`。
4. 活动源代码中除历史审计、测试夹具和交接文档外，不再使用 `execution:state` 计算当前账户。
5. 旧审计记录没有被修改或导入 F5。
6. Python、Node 契约、TypeScript、Vite、API、Web/UI 和浏览器交互验证全部通过。

