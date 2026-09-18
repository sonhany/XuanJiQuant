# Qlib 六年点时数据与 Walk-Forward 研究设计

更新日期：2026-07-12

## 1. 目标

在不使用 Tushare Pro 的前提下，为独立 Qlib 研究环境建立近六年全 A 股日线、
复权、上市退市、历史 ST/名称变更和可交易状态数据，并使用滚动
walk-forward 训练评估 LightGBM 基线。

本阶段只产生离线研究数据、实验、模型和报告。任何模型最多进入 `candidate`
或 `shadow`，不能直接进入模拟盘或实盘订单链路。

## 2. 数据边界

所有新增数据写入：

```text
C:\Users\HYSHEN\XuanJiQuant\data\qlib
```

禁止读取或写入交易数据库：

```text
C:\Users\HYSHEN\XuanJiQuant\data\quant.db
```

六年数据集 ID 固定为：

```text
a_share_6y_daily
```

数据区间以任务运行日向前回溯六年并额外增加 30 个自然日，用于覆盖边界交易日。
股票代码 `920xxx` 继续排除。

## 3. 数据源职责

### 3.1 TdxQuant

TdxQuant 是行情主源，负责：

- 当前全 A 股票列表。
- 未复权日线。
- 前复权日线。
- `ForwardFactor` 或等价复权因子字段。
- 当前名称、上市日期、当前 ST、当前退市状态。
- 行业和基础证券信息。

采集按单只股票调用，保持已有 TdxQuant 串行安全锁。单只失败不终止全市场任务，
写入检查点后继续。

### 3.2 AkShare

AkShare 安装到 `.venv-qlib`，负责：

- 当前沪深京 A 股代码和名称交叉校验。
- 深交所历史简称变更及变更日期。
- 上交所终止/暂停上市公司及日期。
- 深交所终止上市公司及日期。
- 当前 ST 和退市板块信息；对应网络端点不可用时降级，不阻塞行情采集。

AkShare 数据落入独立点时目录，不写项目交易 SQLite。

### 3.3 新浪财经

新浪财经负责：

- 单股历史曾用名序列。
- 当前名称交叉校验。
- AkShare 当前列表不可用时的补充。

新浪曾用名没有准确生效日期时，只能证明“曾经出现过该名称”，不能直接生成
确定的 ST 起止区间。

### 3.4 腾讯财经

腾讯负责：

- 前复权日线交叉校验。
- 最新交易日补齐。
- TdxQuant 单股行情失败后的最终行情兜底。

腾讯不负责历史 ST、上市或退市状态判断。

### 3.5 Baostock

Baostock负责：

- `query_adjust_factor` 复权因子交叉校验。
- `query_stock_basic` 上市退市基础资料交叉校验。
- TdxQuant 历史日线异常时的行情兜底。

Baostock 登录失败时记录来源健康事件并跳过，不阻塞主任务。

## 4. 存储结构

```text
C:\Users\HYSHEN\XuanJiQuant\data\qlib\
├── datasets\
│   └── a_share_6y_daily\
│       ├── raw\
│       │   ├── SH600000.json
│       │   └── manifest.json
│       ├── adjusted\
│       │   └── SH600000.json
│       ├── point_in_time\
│       │   ├── instruments.json
│       │   ├── name_changes.json
│       │   ├── listing_intervals.json
│       │   ├── st_intervals.json
│       │   ├── source_health.json
│       │   └── daily_masks\
│       │       └── SH600000.json
│       └── quality_report.json
├── qlib_bin\
│   └── a_share_6y_daily\
├── models\
└── reports\
```

`raw` 保存未复权 OHLCV、成交额、复权因子和来源；`adjusted` 只保存用于核对的
前复权价格。Qlib bin 以未复权价格和因子为规范输入，前复权数据不覆盖原始数据。

## 5. 点时状态模型

每个股票交易日生成以下字段：

```text
listed
delisted
is_st
st_status
paused
limit_up
limit_down
tradable
status_sources
```

`st_status` 只允许：

```text
normal
st
unknown
```

判定规则：

1. 日期早于上市日：`listed=false`、`tradable=false`。
2. 日期晚于退市日：`delisted=true`、`tradable=false`。
3. 深市简称变更能够形成确定 ST 区间时：按变更日期切换 `is_st`。
4. 沪市只有曾用名但缺少生效日期时：相关不确定区间标记 `st_status=unknown`。
5. `unknown` 不允许进入严格训练截面，不能默认成普通股票。
6. 成交量为零或行情缺失：`paused=true`、`tradable=false`。
7. 涨跌停根据当日板块制度、ST 状态和前收盘价确定。
8. 每个状态保留来源列表，便于审计和重建。

当前股票池只用于启动采集。历史训练股票池由上市退市区间和可用历史行情共同生成，
不能用当前股票池直接回填六年前截面。

## 6. 复权处理

每只股票同时采集：

```text
dividend_type=none
dividend_type=front
```

规范数据使用未复权价格。复权因子采用以下优先级：

1. TdxQuant `ForwardFactor`。
2. Baostock `query_adjust_factor`。
3. 根据未复权和前复权收盘价比值推导的校验因子。

校验规则：

- 因子必须为正数。
- 同一除权事件前后因子变化必须能够解释价格跳变。
- TdxQuant 前复权价与推导前复权价偏差超过 1% 时记录质量异常。
- 无可靠因子时保留未复权行情，但该股票不进入需要收益连续性的训练窗口。

## 7. 数据质量门槛

六年数据集只有满足以下条件才允许启动正式训练：

- 请求股票覆盖率不低于 98%。
- 最近 250 个交易日覆盖率不低于 99%。
- 有效交易日不少于 1200。
- 最新交易日与市场最近交易日一致。
- 重复 `instrument/datetime` 为零。
- OHLC 关系错误为零。
- 复权因子非正值为零。
- 训练截面的 `st_status=unknown` 样本已剔除。
- 上市前和退市后样本已剔除。
- 数据源健康、失败股票和异常原因写入报告。

未通过门槛时数据集状态为 `incomplete` 或 `quality_failed`，训练按钮和调度任务必须
拒绝正式训练。

## 8. Walk-Forward 训练

固定窗口：

```text
训练：36 个月
验证：6 个月
测试：6 个月
滚动步长：3 个月
```

每个窗口：

1. 只使用当时已经上市且未退市的股票。
2. 剔除 `st_status=st` 和 `st_status=unknown`。
3. 剔除停牌、涨跌停不可交易和上市不足 120 个交易日的样本。
4. 使用 Alpha158 和未来 5 日收益标签。
5. 训练独立 LightGBM 模型。
6. 保存窗口级预测、指标、模型和数据版本。

聚合报告包括：

- 每窗口 Rank IC、ICIR、正 IC 比例。
- 费用后多空收益、Sharpe、最大回撤。
- 不同年份和市场状态下的指标。
- 窗口通过率、最差窗口和中位数指标。
- 特征重要性稳定性。

## 9. 晋升门槛

六年 walk-forward 模型只有同时满足以下条件才登记为 `candidate`：

- 至少 4 个完整测试窗口。
- 测试窗口 Rank IC 中位数不低于 0.02。
- 测试窗口 ICIR 中位数不低于 0.30。
- 至少 70% 测试窗口 Rank IC 为正。
- 聚合费用后多空收益为正。
- 聚合 Sharpe 不低于 0.80。
- 最大回撤不低于 -20%。
- 最差窗口 Rank IC 不低于 -0.03。
- 不存在数据质量硬失败。

任一条件不满足则登记为 `rejected`。LLM、AI Agent 和人工界面均不能修改这些
计算结果，只能查看报告或在 `candidate` 之后人工决定是否进入 `shadow`。

## 10. 任务与调度

新增独立任务：

```text
collect_six_years
build_point_in_time
export_six_years
train_walk_forward
```

任务依赖顺序：

```text
collect_six_years
  -> build_point_in_time
  -> quality_gate
  -> export_six_years
  -> train_walk_forward
```

任务支持断点续跑，每 25 只股票写一次检查点。盘中不启动导出和训练；采集任务可在
盘后运行。任何阶段失败都保留上一版数据和模型，临时文件不得覆盖已验证产物。

每周任务继续维护近一年数据。六年全量重建不放入每周任务，只执行：

- 每周增量更新最近交易日。
- 每月重建点时状态和质量报告。
- 每季度或人工触发 walk-forward 重训。

## 11. 前端

Qlib 数据准备页增加：

- 六年原始行情进度。
- 点时状态覆盖率。
- 复权校验异常数。
- 退市股票数。
- ST 确定区间数和未知区间数。
- 数据质量门槛结果。

模型训练页增加 `Walk-Forward 六年基线` 固定任务。实验和回测页面展示窗口级指标，
不能只展示聚合平均数。

## 12. 错误处理

- TdxQuant 不可用：任务失败，不使用免费公网源替代整个全市场主链。
- 单股 TdxQuant 失败：依次尝试 Baostock、腾讯，并记录来源。
- AkShare 交易所端点失败：保留缓存点时数据；无缓存时相应状态标记 `unknown`。
- Baostock 登录失败：记录健康事件并跳过。
- 新浪曾用名失败：不推断 ST，标记 `unknown`。
- 数据源结果冲突：保留全部来源值，按主源优先级裁决并写入冲突报告。
- 训练中断：实验标记 `failed`，已完成窗口可保留，但不能计算晋升状态。

## 13. 验证

自动测试覆盖：

- 复权因子生成和冲突检测。
- 上市退市区间。
- 深市 ST 名称变更区间。
- 沪市不确定 ST 状态的保守剔除。
- 每日可交易掩码。
- 当前股票池不能回填历史截面。
- 数据质量门槛所有拒绝原因。
- Walk-forward 窗口无重叠和无前视。
- 聚合指标与候选晋升门槛。
- 任务依赖、断点续跑和失败保留。
- API 鉴权和固定动作白名单。
- 中文前端、任务进度和窗口指标展示。

运行验证包括：

```text
Python 单元测试
TdxQuant 小样本真实采集
AkShare 深市名称变更与沪深退市数据验证
六年小股票池端到端训练
前端构建
API 冒烟
浏览器逐页验证
```
