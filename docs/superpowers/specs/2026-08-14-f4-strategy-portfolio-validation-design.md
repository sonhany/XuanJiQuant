# F4 策略与组合级验证设计

## 1. 决策与阶段定义

本设计落实已确认的“方案 A：确定性 F4 主链”。F4 的目标不是产生订单，而是回答一个更严格的问题：F3 通过的因子研究结果，在无未来信息、具有 A 股交易约束、成本、容量和组合约束的样本外环境中，能否稳定形成可复现的组合结果。

阶段状态必须区分：

- `f4_building`：F4 代码、契约或测试仍在建设。
- `f4_blocked`：实现可用，但真实数据、PIT、基准或版本门禁未通过。
- `f4_rejected`：数据门禁通过，但组合级指标未达到 `f4_gate_v1`。
- `f4_research_candidate`：全部 F4 门禁通过，只代表研究候选。

无论状态如何，所有 F4 产物固定为：

```json
{
  "promotion_state": "research_only",
  "execution_authority": false
}
```

F4 不得写持仓、订单、成交、模拟盘配置或风险许可，不得恢复 Agent、自动交易或历史执行入口。F5 生产候选与执行工程不在本设计范围。

## 2. 当前事实与进入条件

截至 2026-08-14 的源码和本地产物审计结果：

- F3 `factor_evaluation.json` 已携带当日 `snapshot_id`、`data_version`、`universe_version`、`research_only` 和无执行权限。
- `strategy_scan_realistic.json` 仍是 2026-08-07 13:10 的历史扫描，缺少上述版本和权限字段，不构成 F4 证据。
- 现有 `scan_strategies.py` 实现 Top20、5 日持有、固定成本和涨跌停过滤，但未形成严格走样本外、基准、PIT 股票池、组合约束、容量、冲击和稳定性门禁。
- 六年数据 manifest 当前为 `incomplete`，尚无通过的六年质量报告。因此允许建设和测试 F4 引擎，但真实运行必须返回 `f4_blocked`，不得生成 `f4_research_candidate`。

F4 真实验证必须同时具备：

1. 当前 F3 因子评估和因子快照版本完全一致。
2. 六年 PIT 日线 manifest 为 `complete`。
3. 六年质量报告为 `passed`，且数据版本与 manifest 一致。
4. 每个历史截面具备当日上市、退市、ST/未知 ST、停牌与可交易掩码。
5. 配置的基准序列完整且版本化。

当前股票池 `current_tradeable_v1` 只用于 F3 当前截面排名。F4 历史窗口不得使用今天的股票池回看过去；否则属于幸存者偏差，必须以 `pit_universe_required` 阻断。

## 3. 推荐架构

```text
F3 versioned factor evidence
  + six-year PIT bars and daily masks
  + versioned benchmark
  + immutable F4 candidate specification
        |
        v
walk-forward window builder
        |
        v
train-only factor direction/weight fitting
        |
        v
validation selection -> frozen test configuration
        |
        v
portfolio constructor -> A-share portfolio simulator
        |
        v
cost/capacity/stress/stability metrics
        |
        v
f4_gate_v1 -> blocked / rejected / research_candidate
        |
        v
immutable evidence + latest read-only projection + research job ledger
```

F4 核心采用独立模块，不把组合级行为继续堆入 `scan_strategies.py` 或通用 `StrategyEngine`：

- `quant/strategy/f4_contracts.py`：数据类、稳定错误码、版本身份和序列化契约。
- `quant/strategy/f4_dataset.py`：读取六年 PIT 日线、每日可交易掩码、历史行业和可用因子输入，构建窗口内因子面板。
- `quant/strategy/walk_forward.py`：严格时间窗口、purge 与 embargo。
- `quant/strategy/portfolio.py`：分数到目标权重的纯函数与组合约束。
- `quant/strategy/portfolio_backtest.py`：研究态组合回测和 A 股成交规则。
- `quant/strategy/f4_metrics.py`：窗口、聚合、基准、容量和压力指标。
- `quant/strategy/f4_gate.py`：唯一的 F4 阶段判定。
- `scripts/validate_strategy_portfolios.py`：加载版本化输入、编排窗口、原子写产物。

模块职责必须单一。数据加载、信号拟合、组合构建、交易仿真、指标计算和阶段判定不得互相写隐式全局状态。

## 4. 输入契约与身份

每次 F4 运行建立 `F4ValidationIdentity`：

```text
validation_id = sha256(
  market_date
  + factor_snapshot_id
  + factor_data_version
  + factor_universe_version
  + pit_dataset_version
  + benchmark_version
  + candidate_spec_version
  + portfolio_policy_version
  + cost_model_version
  + f4_gate_version
)
```

身份字段缺失、版本不匹配或产物无法解析时失败关闭。禁止以文件存在、进程存活或旧扫描成功代替身份校验。

输入对象包括：

- `FactorEvidenceRef`：F3 快照、数据、股票池版本和 58 因子评估摘要。
- `PITDatasetRef`：六年 manifest、质量报告、日线、复权口径和每日可交易掩码。
- `PITIndustryRef`：带生效日期的历史行业分类及版本；禁止用当前行业回填历史。
- `FinancialPITRef`：财报公告日、可见日和版本；仅在通过门禁时允许基本面因子进入 F4。
- `BenchmarkRef`：默认 `000300`，包含日期范围、价格口径、版本和缺失率。
- `CandidateSpec`：因子候选集合、拟合方法、TopK、调仓周期和方向规则。
- `PortfolioPolicy`：个股、行业、现金、换手、容量和整数手约束。
- `CostModel`：佣金、最低佣金、印花税、过户费、基础滑点和冲击参数。

基准缺失时不得静默换成等权股票池；返回 `benchmark_missing` 或 `benchmark_coverage_failed`。

## 5. 候选策略与防止数据窥探

F4 v1 只验证一个预先声明的主候选族 `ic_weighted_top20_v1`，避免扫描大量参数后挑选最好结果：

- 候选因子来自固定 58 因子注册表；F3 当前结果仅证明这些因子可计算，不直接提供历史窗口权重。
- F4 v1 默认只允许由当时已知日线产生的技术和量价因子。11 个基本面因子只有在 `FinancialPITRef` 具备真实公告日并通过质量门禁时才可加入；报告期加固定天数的近似值不得进入 F4 正式证据。
- 每次运行必须输出可用因子和排除因子清单及原因，不能把输入缺失解释成因子失效。
- 每个窗口只使用训练段计算 IC、方向和权重。
- 因子进入条件：训练段 `abs(median_rank_ic) >= 0.02`，方向一致率不低于 60%，至少保留 3 个、最多 10 个因子。
- 权重为训练段 `abs(median_rank_ic)` 归一化；方向由训练段符号决定。
- 验证段只用于确认候选是否满足基础稳定性，不重新拟合权重。
- 测试段使用冻结的因子集合、方向、权重和组合参数。
- 每个未通过窗口及原因必须保留，禁止只输出最佳窗口。

如果训练段不足 3 个合格因子，该窗口为 `window_rejected`；不得改用全样本 F3 权重兜底。

## 6. Walk-forward 规则

`walk_forward_v1` 使用交易日历而非自然日切片：

- 训练段：504 个交易日。
- 验证段：126 个交易日。
- 测试段：126 个交易日。
- 滚动步长：126 个交易日。
- purge：20 个交易日，覆盖最长因子前瞻和持有周期。
- embargo：5 个交易日，隔离相邻窗口信息。
- 完整样本外窗口至少 4 个。

必须满足：`train_end < valid_start < valid_end < test_start < test_end`，并在训练/验证边界和验证/测试边界应用 purge/embargo。窗口不足、重叠或日期越界返回稳定错误码，不得缩短窗口后继续。

## 7. 组合构建

默认组合 `portfolio_policy_v1`：

- 仅做多；每 5 个交易日调仓。
- 按冻结多因子分数选 Top20。
- 初始等权；单只股票目标权重上限 10%。
- 单一行业目标权重上限 25%。
- 无法分配的权重保留现金，不向其他股票无限递补。
- 买入数量向下取整到 100 股整数手；卖出允许清仓零股。
- 当日停牌、不可交易、ST/未知 ST、退市后、涨停买入或跌停卖出均不成交。
- T+1 生效；未成交部分不假设下一时刻自动成交，必须由下一调仓日重新生成目标差额。

行业分类必须带历史生效日期。当前行业字段不得回填历史；任一测试窗口的历史行业覆盖率低于 95% 时返回 `pit_industry_missing`。少量缺失股票进入 `industry_unknown` 桶，该桶同样受 25% 上限约束。

## 8. 成本、容量与冲击

`cost_model_v1` 必须复用现有 A 股费用语义，并在产物中写明实际参数：

- 佣金率与最低佣金。
- 卖出印花税。
- 过户费。
- 基础滑点。
- 涨跌停、停牌与 T+1 拒绝统计。

容量约束使用过去 20 个交易日的平均成交额或成交量：

- 单票单次成交不得超过 20 日 ADV 的 10%。
- 超出部分不成交并保留现金，记录 `capacity_rejected_notional`。
- ADV 历史不足时禁止交易该证券，不用当日成交额代替。

压力测试至少运行基础成本的 1.0、1.5、2.0 倍。2.0 倍成本下累计样本外超额收益必须仍为正，否则 F4 门禁不通过。

## 9. 指标与 F4 门禁

每个窗口和聚合层都必须输出：

- 组合收益、基准收益、超额收益。
- 年化收益、年化波动率、Sharpe、信息比率。
- 最大回撤、回撤持续期、Calmar。
- 胜率、换手率、交易次数、现金占比。
- 个股最大权重、行业最大权重和违规次数。
- 费用、滑点、冲击、容量拒绝金额和占比。
- 涨跌停、停牌、T+1 和数据缺失拒绝次数。
- 各成本压力场景结果。

`f4_gate_v1` 的通过条件全部为硬条件：

1. PIT、质量、F3、基准和版本身份门禁全部通过。
2. 完整样本外窗口不少于 4 个。
3. 至少 60% 的测试窗口成本后超额收益为正。
4. 聚合成本后超额收益大于 0。
5. 聚合 Sharpe 不低于 0.80。
6. 聚合最大回撤不低于 -20%。
7. 2.0 倍成本场景下聚合超额收益仍大于 0。
8. 单票、行业和 ADV 硬约束违规次数为 0。
9. 所有窗口均无未来数据、版本漂移或不可解释缺口。

数据/身份类失败映射为 `f4_blocked`；指标类失败映射为 `f4_rejected`；全部通过才映射为 `f4_research_candidate`。

## 10. 产物与审计

每次运行写入不可覆盖的证据：

```text
data/research/f4/<validation_id>/
  identity.json
  window_definitions.json
  candidate_spec.json
  portfolio_policy.json
  cost_model.json
  window_metrics.json
  aggregate_metrics.json
  gate_result.json
  validation_report.json
```

最新只读投影为：

```text
data/research/f4/latest.json
```

`latest.json` 必须原子替换，并指向完整验证目录；不得把阻断或失败写成成功。`data/strategy_scan_realistic.json` 保留为历史审计事实，但不再作为当前 F4 API 的权威来源。

`research_jobs.db` 的 `strategy_weekly` 记录至少包含 `validation_id`、输入版本、当前阶段、窗口完成数、最终状态、原因码和产物路径。相同身份重复运行返回经过完整性校验的 `no_op`；不允许只凭幂等键存在跳过。

## 11. 调度与并发

周六研究任务继续由 `XuanJiQuant-Research-Daily` 调用，但 `strategy_weekly` 处理器改为 F4 编排入口。调度依赖：

1. 最近交易日同版本 `factor_daily` 成功。
2. 没有相同或更高优先级的重型研究任务运行。
3. PIT、质量和基准输入通过门禁。

任务采用 `IgnoreNew` 和研究账本租约，禁止同一 `validation_id` 并发。进程被杀或超时后记录 `interrupted`，下次只能从已校验的窗口证据恢复，不能把半成品 `latest.json` 暴露给页面。

F4 阻断不会影响数据层和 F3 日因子评估，也不会改变风险或交易状态。

## 12. API 与页面

策略页面将“市场扫描”收敛为只读“F4 策略与组合验证”，展示：

- 阶段状态、验证时间和阻断/拒绝原因。
- F3、PIT、基准、候选、组合、成本和门禁版本。
- walk-forward 窗口表及每窗测试指标。
- 组合与基准曲线、超额曲线、回撤和换手。
- 个股/行业集中度、容量和成本压力结果。
- `仅供研究，不构成目标持仓或交易信号` 标签。

页面只读取 `latest.json`。不得在页面上提供晋升生产、自动交易、写入模拟盘或绕过门禁的按钮。现有手动策略回测必须标记为 `diagnostic_only`，不得与 F4 结果合并排序。

## 13. 稳定错误码

至少包含：

- `f3_evidence_missing`
- `f3_version_mismatch`
- `pit_manifest_incomplete`
- `pit_quality_failed`
- `pit_universe_required`
- `pit_industry_missing`
- `financial_pit_missing`
- `corporate_action_schema_mismatch`
- `benchmark_missing`
- `benchmark_coverage_failed`
- `walk_forward_window_insufficient`
- `walk_forward_overlap`
- `train_factor_insufficient`
- `portfolio_constraint_failed`
- `capacity_data_missing`
- `future_data_detected`
- `artifact_integrity_failed`
- `validation_interrupted`

错误码写入研究账本、验证报告和 API；中文说明只在展示层映射，不能用自由文本作为程序判断条件。

## 14. 测试策略

实施必须遵循测试驱动：先写失败测试并观察正确失败，再写最小实现。

单元测试覆盖：

- 窗口顺序、purge、embargo、最少窗口和无重叠。
- 训练段拟合、验证段选择、测试段冻结及未来数据隔离。
- 单票、行业、现金、整数手和未知行业约束。
- 当前行业回填历史、基本面公告日在测试日之后和复权口径不一致均被阻断。
- T+1、涨跌停、停牌、退市、ST/PIT 和成本。
- ADV 容量限制及 1.0/1.5/2.0 倍压力场景。
- 所有门禁状态和稳定错误码。
- 身份哈希、原子产物和幂等完整性校验。

集成测试覆盖：

- 完整合成 PIT 数据产生 `f4_research_candidate`。
- 不完整 manifest 产生 `f4_blocked`。
- 当前股票池冒充历史 PIT 股票池被阻断。
- F3/PIT/基准任一版本不匹配被阻断。
- 指标不达标产生 `f4_rejected`。
- 调度器只调用确定性 F4 入口并保持无执行权限。
- API/UI 不再把 2026-08-07 历史扫描冒充当前结果。

回归验证至少包括相关 Python 测试、完整 Python 套件、全部 Node 契约、TypeScript、Vite 构建、Web 验证和 UI 验证。

## 15. 实施顺序与完成判定

实施顺序固定为：

1. 契约、身份、错误码和 walk-forward。
2. 组合构建和 A 股组合回测。
3. 指标、容量、压力测试和 F4 门禁。
4. 产物、研究账本、幂等和恢复。
5. 调度器接线。
6. API 与只读页面。
7. README、`docs/XUANJI_HANDOFF.md` 和项目工作流图更新。
8. 完整回归和真实输入门禁检查。

“F4 实现完成”必须满足代码、测试、调度、API、页面和文档均通过；“F4 真实验证通过”还必须由完整六年 PIT 数据、质量报告、基准和不少于 4 个真实样本外窗口产生 `f4_research_candidate`。两者必须分别报告。

在当前六年 manifest 仍为 `incomplete` 的事实下，实施完成后的最高真实状态只能是 `f4_blocked/pit_manifest_incomplete`，不得篡改门禁、降低阈值或用合成测试结果冒充真实市场验证。
