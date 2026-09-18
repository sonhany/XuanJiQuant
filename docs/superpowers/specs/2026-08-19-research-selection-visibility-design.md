# 研究选股可见性与日期口径设计

> 状态：用户已于 2026-08-19 批准按既定优先级处理。本规格只解决 P0 可见性与事实口径，不扩大研究或交易权限。

## 1. 目标

让策略页面同时、准确展示两个独立事实域：

1. F4 使用的六年 PIT/Qlib 数据截止日与组合门禁结果；
2. 当前每日因子快照生成的研究选股组合及其选股日期。

禁止把 PIT 周数据日期描述成当前行情日期，也禁止把诊断研究组合描述成目标持仓、买卖信号或可执行订单。

## 2. 范围

本轮包括：

- `strategy_runner.py` 新增只读 `research_selection` 投影；
- `StrategyPanel.tsx` 展示研究组合、选股理由、权重、行业、参考价和来源状态；
- 将“市场数据日”改为“F4/PIT 数据截止日”，并显示独立的“当前因子/选股日”；
- 新增失败关闭、权限和 UI 契约测试；
- 更新 README 与交接文档。

本轮不包括：

- 修改 F4 门槛、因子、候选策略、成本模型或组合约束；
- 自动晋升、模拟下单、真实下单或 Agent；
- 从诊断研究组合生成订单。

## 3. API 契约

新增 `/api/strategy` 请求：

```json
{"action":"research_selection"}
```

runner 只读取 `data/research/selections/latest.json`，并验证：

- `portfolio_id`、`selection_date`、`generated_from_snapshot_id`、`snapshot_data_version` 非空；
- `positions` 是非空数组且 `position_count` 一致；
- `promotion_state == "research_only"`；
- `execution_authority == false`；
- `not_a_trade_signal == true`；
- `selection_status` 仅为 `diagnostic_research_portfolio` 或 `f4_research_portfolio`。

文件缺失返回 `research_selection_missing`；身份或权限异常返回 `research_selection_integrity_failed`。二者均不得回退到旧市场扫描、旧目标组合或历史订单。

## 4. 页面设计

F4 顶部指标改为：

- F4 状态；
- F4/PIT 数据截止日；
- 当前因子/选股日；
- 样本外窗口；
- F4 生成时间。

在 F4 证据下新增“每日研究选股组合”区：

- 页头显示组合 ID、选股日期、F4 来源状态、股票数；
- 诊断组合使用黄色提示，明确“F4 未通过，仅供诊断研究”；
- 表格显示代码、名称、行业、研究得分、目标研究权重、参考收盘价、研究理由；
- 理由列允许换行并在右侧占用最大宽度；
- 任意状态都显示 `research_only / 不构成交易信号`。

选股 API 失败不能遮蔽 F4 证据；页面单独显示选股错误及重试入口。

## 5. 数据流

```text
data/research/selections/latest.json
  -> strategy_runner.py::action_research_selection
  -> /api/strategy action=research_selection
  -> StrategyPanel 只读展示
```

F4 仍保持独立链路：

```text
data/research/f4/latest.json
  -> strategy_runner.py::action_market_scan
  -> StrategyPanel F4 门禁与绩效展示
```

两条链路只在页面并列展示，不合并身份、不推导执行权限。

## 6. 测试与完成判定

完成必须同时满足：

1. Python 测试证明有效组合可读取，缺失、权限异常、数量不一致均失败关闭；
2. Node/UI 契约证明页面请求 `research_selection`，显示双日期和研究边界；
3. 当前 API 返回 2026-08-18 的 20 只研究组合；
4. TypeScript、Vite、全部 Node 契约、相关 Python 与 UI 验证通过；
5. `/api/execution` 和 `/api/paper` 写权限仍为关闭。

## 7. 后续阶段

P0 完成后单独启动“F4 候选改进”研究规格。只有新候选成为 `f4_research_candidate`，才允许设计 F5 确定性模拟交易闭环；F5 必须重新经过人工批准，不能由本规格隐含授权。
