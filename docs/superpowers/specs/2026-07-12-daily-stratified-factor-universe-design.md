# 每日分层全A 500 因子评估样本池设计

状态：用户已确认设计方向  
日期：2026-07-12  
范围：因子引擎的科学评估样本，不直接生成交易订单

## 1. 目标

建立一套每日自动更新、可回放、低换样、无幸存者偏差的 500 只 A 股因子评估样本池，替代 IC 评估页面手工输入股票代码。

核心目标：

- 一键选择科学、可重复的评估样本。
- 覆盖不同行业、大中小市值和流动性层级。
- 每日检查数据和股票资格，但避免样本每天大幅变化。
- 历史评估使用历史当日样本，禁止用今天的成分股回测过去。
- 样本池与交易候选池物理分离，不能通过挑选表现好的股票美化 IC。
- 每次评估都记录样本版本、数据日期和排除原因，支持审计回放。

## 2. 非目标

- 本样本池不负责直接选出未来最赚钱的股票。
- 不根据某个因子的历史表现反向挑选样本。
- 不允许 AI 或 LLM 修改样本硬过滤条件。
- 不允许样本池结果绕过因子晋升、策略回测、paper trading 和 risk gateway。

## 3. 外部方法参考

本设计吸收以下正式方法，但按本项目的数据能力做简化：

- MSCI GIMI：使用市值、自由流通市值、流动性和交易频率等可投资性筛选。
- FTSE Russell：使用月度日成交量中位数等流动性指标，并通过层级缓冲降低指数换样。
- Microsoft Qlib PIT：使用 point-in-time 数据，防止历史评估引用当时尚未公开的信息。

参考：

- https://www.msci.com/indexes/documents/methodology/2_MSCI_Global_Investable_Market_Indexes_Methodology_202602.pdf
- https://www.lseg.com/content/dam/ftse-russell/en_us/documents/ground-rules/ftse-china-a-indexes-ground-rules.pdf
- https://qlib.readthedocs.io/en/latest/component/data.html
- https://qlib.readthedocs.io/en/latest/component/pit.html

## 4. 推荐方案

采用“每日资格检查 + 行业/市值分层 + 进入退出缓冲 + 历史版本化”的方案。

目标样本数为 500。每日构建，但普通情况下单日换样目标不超过 10%，硬上限不超过 15%。退市、风险警示、长期停牌或数据失效等硬排除不受换样上限约束。

## 5. 数据流

```text
stock:universe
  -> 点时基础信息和行业/市值数据
  -> K线、成交额、停牌和数据新鲜度检查
  -> eligibility_filter
  -> industry_size_stratifier
  -> stability_buffer
  -> deterministic_sampler
  -> factor_sample_membership 每日快照
  -> IC / 分段 IC / 批量 IC
```

## 6. 资格过滤

评估日期为 T 时，只允许使用 T 日或 T 日以前已经可获得的数据。

### 6.1 硬排除

- 排除 `920xxx`。
- 排除 ST、`*ST`、退市整理和已退市股票。
- 排除上市不足 120 个交易日的股票。
- 排除最近 20 个交易日有效交易天数少于 18 日的股票。
- 排除最近 20 日成交额中位数低于 5000 万元的股票。
- 排除连续停牌、价格小于等于 1 元或价格字段异常的股票。
- 排除最新 K 线日期落后预期交易日的股票。
- 排除名称、行业、上市日期等必要基础信息缺失的股票。

### 6.2 数据质量门禁

- 行业覆盖率必须不低于 95%。
- 市值或自由流通市值覆盖率必须不低于 90%。
- 最新 K 线覆盖率必须不低于 98%。
- 不满足门禁时不生成新的正式版本，继续使用上一有效版本并标记 `stale=true`。
- 成交额只能作为流动性指标，不能冒充市值。

## 7. 分层方式

### 7.1 一级分层：行业

使用评估日期当时有效的行业分类。每个行业首先获得最小样本配额，剩余名额按该行业合格股票数量比例分配。

### 7.2 二级分层：市值

在每个行业内按点时自由流通市值分为：

- large：前 33%
- mid：中间 34%
- small：后 33%

市值数据缺失时，该股票不能进入正式分层样本；不得使用成交额替代市值后继续标记为“市值分层”。

### 7.3 三级标签：流动性

根据最近 20 日成交额中位数标记 high、medium、low。流动性用于质量控制和结果归因，不与市值混为同一字段。

## 8. 配额与抽样

- 总样本数：500。
- 分层单元：行业 × 市值层级。
- 配额优先按合格股票数量同比例分配。
- 每个有足够成分的分层至少保留 3 只股票。
- 配额舍入使用 largest remainder 方法，保证合计严格等于 500。
- 分层内部不按收益或因子值选股。
- 使用 `effective_date + sample_policy_version + code` 的稳定哈希排序，保证相同输入得到相同结果。

## 9. 每日稳定机制

### 9.1 硬退出

出现 ST、退市、长期停牌、数据过期或不满足硬过滤时立即退出。

### 9.2 缓冲区

- 新股票必须进入本分层候选排名前 85% 才能进入样本。
- 已有成分只有跌出本分层前 115% 缓冲区时才因普通排名变化退出。
- 优先保留仍然合格的昨日成分。
- 普通替换每日目标不超过 10%，硬上限 15%。

### 9.3 补位

空缺优先从相同行业、相同市值层级补位；不足时依次放宽到相同行业相邻市值层级，再放宽到市场整体，但必须记录 `replacement_reason`。

## 10. 点时与历史回放

不能只保存“当前500只”。必须保存每日成分版本。

建议新增结构化表：

### `factor_sample_versions`

- `sample_version`
- `effective_date`
- `policy_version`
- `target_size`
- `actual_size`
- `data_asof`
- `industry_coverage`
- `market_cap_coverage`
- `kline_coverage`
- `turnover_pct`
- `added_count`
- `removed_count`
- `stale`
- `status`
- `created_at`

### `factor_sample_membership`

- `sample_version`
- `effective_date`
- `code`
- `name`
- `industry`
- `size_bucket`
- `liquidity_bucket`
- `market_cap`
- `median_amount_20d`
- `is_incumbent`
- `selected_reason`
- `replacement_reason`
- `data_asof`

### `factor_sample_exclusions`

- `effective_date`
- `code`
- `reason_code`
- `details`
- `data_asof`

历史日期 T 的 IC 必须连接 T 日的 `factor_sample_membership`，不得使用最新版本替代。

## 11. 后端模块

建议新增：

- `quant/factor/universe/eligibility.py`
- `quant/factor/universe/stratifier.py`
- `quant/factor/universe/stability.py`
- `quant/factor/universe/store.py`
- `scripts/factor_universe_runner.py`

统一接口：

```python
build_factor_sample(
    effective_date,
    target_size=500,
    policy_version="stratified_a500_v1",
) -> SampleBuildResult
```

API 建议：

- `factor_sample_presets`
- `factor_sample_status`
- `factor_sample_build`
- `factor_sample_members`
- `factor_sample_exclusions`
- `evaluate` 增加 `sample_version`
- `evaluate_segments` 增加 `sample_version`
- `evaluate_all` 增加 `sample_version`

构建动作属于受保护控制面；查看状态和成员属于只读接口。

## 12. 前端设计

IC 评估页将股票代码输入框替换为“评估样本”选择器：

- 分层全A500 · 每日更新，默认
- 沪深300
- 中证500
- 中证1000
- 当前自选股
- 自定义股票池

默认样本旁显示：

- 样本版本
- 数据日期
- 实际股票数
- 行业覆盖率
- 大/中/小盘比例
- 今日新增和移除数量
- 样本换手率
- 数据是否新鲜

提供“查看成分”和“查看排除原因”抽屉，不默认渲染 500 行，避免拖慢页面。

评估结果必须显示：

- 实际参与 IC 的股票数量
- 因数据缺失被跳过的股票数量
- 样本版本和数据日期
- 是否使用历史点时成分
- Train / Valid / Test 各自实际样本覆盖率

## 13. 失败处理

- 当日样本构建失败：保留上一有效版本，页面显示黄色 `stale` 标记。
- 上一有效版本也不可用：禁止运行正式 IC，不能自动补 3 只股票后伪装成标准样本。
- 实际有效股票少于目标数的 90%：评估标记为 `insufficient_coverage`。
- 行业或市值覆盖不达标：禁止把结果用于 promotion。
- 所有降级必须写入 `audit_events`。

## 14. 调度

- 每个交易日数据更新完成后构建一次。
- 默认在收盘数据和基础信息校验完成后运行。
- 盘中只读取最近有效版本，不同步重建 500 只样本。
- 数据层发生补数后允许人工触发重建，但必须生成新版本，不能覆盖旧版本。

## 15. 测试要求

- 相同输入和版本必须生成相同样本。
- 总数必须严格等于 500，除非覆盖率门禁失败。
- 行业和市值配额总和必须正确。
- 普通每日换样不得超过 15%。
- 硬排除必须立即生效。
- 历史日期不能出现未来上市、未来行业或未来财务信息。
- 流动性不得作为市值字段使用。
- 样本构建失败不得覆盖上一有效版本。
- IC API 必须返回实际样本数和版本。
- 测试必须使用临时 SQLite，禁止污染 `data/quant.db`。

## 16. 验收标准

- 用户无需手工输入股票代码即可运行 IC 评估。
- 默认样本为每日分层全A500。
- 页面可查看样本版本、覆盖率、换样和排除原因。
- 任意历史 IC 可以回放到当日样本成分。
- 不再静默自动补充未知股票。
- promotion 只接受覆盖率和样本版本合格的评估结果。
- 默认评估结果不因单日样本大幅变化产生不可解释跳变。

## 17. 后续扩展

完成科学评估样本后，再单独设计“交易候选池”。交易候选池可以使用流动性、趋势、基本面、风险和多因子评分优化盈利空间，但不得反向影响评估样本。
