# F4 多 Alpha 与策略候选工厂 v2 设计

**日期：** 2026-08-21  
**状态：** 设计已获用户确认，等待书面规格审阅  
**活动工作区：** `C:\Users\HYSHEN\XuanJiQuant`  
**权限边界：** 本设计只扩展确定性研究和样本外验证。全部新产物必须保持 `promotion_state=research_only`、`execution_authority=false`，不得降低 F4 门槛，不得授予模拟盘或实盘交易权限。

## 1. 背景与问题定性

现有 `f4-nested-candidate-factory-v1` 注册六个候选，但六者共享同一训练期因子筛选、同一线性 Rank IC 加权信号，只改变 `top_k ∈ {5, 10}` 和 `rebalance_bars ∈ {5, 10, 20}`。这属于组合参数排列，不是六种独立 Alpha。

现有 `F4CandidateSpec` 虽记录因子准入阈值，但 `run_real_f4_pipeline()` 在窗口拟合时没有把候选阈值传给 `fit_window_factors()`。因此候选登记的筛选参数没有形成真实候选差异。本设计必须先修正这一契约，再引入具有不同经济含义、特征集合和拟合方法的 Alpha 候选。

当前真实 F4 结果为 `f4_rejected_exhausted`，主要指标不能通过现有门禁。扩展候选的目的不是保证通过，而是以有界、预登记、可复现且无测试集回看的方式检验新的 Alpha 假设。候选全部失败时必须继续诚实发布拒绝结果。

## 2. 目标与非目标

### 2.1 目标

1. 将候选工厂升级为 `f4-multi-alpha-candidate-factory-v2`。
2. 预登记 24 个具有独立 `alpha_spec` 的 Alpha/策略候选。
3. 覆盖动量趋势、短期反转、低波防御、量价流动性、稳健多因子和 Qlib 模型影子六个候选族。
4. 每个候选同时绑定不可变 Alpha 规格和组合政策；训练、评分、回测和发布均使用同一身份。
5. 保留当前 purged walk-forward、逐窗口嵌套选择、原子锁定和胜者独占测试集的边界。
6. 使用完整六年 PIT 数据重新进行样本外验证，输出候选族级诊断、成本压力结果和最终 F4 门禁判定。
7. 保留 v1 全部历史产物，不覆盖、不改名、不机械迁移审计事实。

### 2.2 非目标

- 不降低或绕过任何 F4 指标、组合、成本、未来数据或完整性门禁。
- 不在看到验证或测试结果后增加候选、修改公式或调整阈值。
- 不把研究工厂成功运行称为策略通过。
- 不把 Qlib 模型直接晋升为模拟盘、生产候选、批准或实盘状态。
- 不接入真实交易，不恢复已退休的 AI Agent 或自主执行路径。
- 不在本阶段引入深度学习、强化学习、自动超参数搜索或无界遗传搜索。
- 不启用尚未证明财报发布日期、可见日期和披露滞后的基本面因子。

## 3. 总体架构

```text
六年 PIT 日线 + 历史行业 + 基准 + 股票生命周期
  -> 研究数据质量门禁
  -> 规则 Alpha 特征面板 / Qlib Alpha158、Alpha360 数据集
  -> 24 个预登记候选
  -> 每个外层窗口：train 拟合全部候选
  -> 当前窗口 validation 比较
  -> 原子写入并复核当前窗口 winner lock
  -> 只允许 winner 读取当前窗口 test
  -> 1.0x / 1.5x / 2.0x 成本组合回测
  -> 聚合全部测试窗口
  -> 原有 F4 v4 门禁
  -> f4_research_candidate 或 f4_rejected_exhausted
```

实现必须分为四个独立职责单元：

1. **候选注册表：** 只定义候选，不读取市场数据、不训练、不回测。
2. **Alpha 适配器：** 按 `alpha_spec` 在训练段拟合，并在指定数据段产生横截面分数。
3. **嵌套选择器：** 只使用当前窗口 validation 指标选择胜者并生成不可变锁。
4. **F4 验证器：** 只允许锁定胜者访问当前窗口 test，执行组合与成本验证并汇总门禁。

## 4. 版本与身份

新版本固定为：

- 候选工厂：`f4-multi-alpha-candidate-factory-v2`
- F4 流水线：`f4-real-pipeline-v4-multi-alpha`
- Alpha 规格：`f4-alpha-spec-v2`
- 组合政策：`f4-standard-top10-policy-v2`
- 候选锁：`f4-candidate-selection-lock-v2`

每个候选必须包含：

```json
{
  "candidate_id": "sha256(canonical_candidate_payload)",
  "family": "momentum|reversal|defensive|liquidity|ensemble|qlib",
  "alpha_spec": {
    "version": "f4-alpha-spec-v2",
    "alpha_id": "M1",
    "input_features": [],
    "formula": {},
    "preprocessing": {},
    "fit_method": "fixed|train_rank_ic_shrinkage|qlib_model",
    "label_horizon_bars": 5,
    "minimum_coverage": 0.95,
    "seed": 20260821
  },
  "portfolio_policy": {
    "version": "f4-standard-top10-policy-v2",
    "top_k": 10,
    "rebalance_bars": 10,
    "max_name_weight": 0.095,
    "max_industry_weight": 0.25,
    "target_gross_exposure": 0.95,
    "lot_size": 100,
    "adv_participation": 0.10
  },
  "promotion_state": "research_only",
  "execution_authority": false
}
```

`candidate_id` 必须覆盖完整 `alpha_spec` 和 `portfolio_policy`。`factory_run_id` 必须覆盖工厂版本、24 个候选注册表、数据集版本、数据 manifest 哈希、行业版本与哈希、基准版本和代码版本标识。当前目录没有 Git 元数据，因此代码版本标识定义为候选注册表、Alpha 适配器、F4 流水线、组合政策、成本模型和门禁源码文件的排序 SHA-256 清单哈希，不得使用文件修改时间替代。任一字段变化都产生新的工厂身份。

## 5. 特征范围与预处理

### 5.1 规则 Alpha 输入

v2 规则 Alpha 使用当前 19 个技术指标和 28 个量价因子，共 47 个可验证输入。11 个基本面因子继续标记为 `financial_pit_not_verified`，不得进入候选。

价格尺度相关指标必须先转换为无量纲值：

- `ema_gap_12 = close / ema_12 - 1`
- `ema_gap_26 = close / ema_26 - 1`
- `macd_hist_norm = macd_hist / close`
- `atr_14_norm = atr_14 / close`
- `boll_width = (boll_upper - boll_lower) / boll_mid`

新增的派生值只允许由当日及历史数据计算，并纳入面板版本和哈希。

### 5.2 横截面预处理

每个交易日按以下固定顺序处理：

1. 将无穷值转为缺失值。
2. 使用横截面中位数和 MAD 做五倍 MAD 去极值；MAD 为零时不缩放该特征。
3. 在历史行业分类覆盖有效时做行业内去中心化。
4. 转换为 `[0, 1]` 百分位排名。
5. 候选所需输入任一缺失时，该股票对当前候选不可评分。

不得使用当前 F4 面板未提供且无法 PIT 证明的市值做规模中性化。以后若增加 PIT 市值字段，必须另立版本和规格。

### 5.3 训练期拟合

固定公式候选不做参数搜索，只在训练段验证方向和覆盖率。需要权重拟合的候选使用训练段逐日 Rank IC：

- 标签为未来 5 日收益；
- 最低单日有效横截面为 20 只；
- 候选输入覆盖率不得低于 95%；
- 方向由训练期中位 Rank IC 决定；
- 权重使用收缩后的绝对中位 Rank IC；
- 方向一致性不足 60% 的因子不得进入稳健组合；
- 相关性去冗余仅使用训练段 Spearman 相关矩阵，阈值为 `|rho| >= 0.70`；
- 同分时按因子名称字典序选择，确保确定性。

## 6. 24 个预登记候选

所有公式中的 `rank(x)` 表示完成第 5 节预处理后的横截面百分位。公式权重固定，不从 validation 或 test 调整。

### 6.1 动量趋势族

| ID | 分数公式 | 调仓 |
|---|---|---:|
| M1 | `0.60*rank(ret_20) + 0.40*rank(ret_60)` | 20日 |
| M2 | `0.40*rank(ret_5) + 0.35*rank(ret_10) + 0.25*rank(roc_10)` | 10日 |
| M3 | `0.60*rank(ret_20/volatility_20) + 0.40*rank(ret_60/volatility_60)` | 20日 |
| M4 | `0.35*rank(trend_strength) + 0.25*rank(ema_gap_12) + 0.20*rank(macd_hist_norm) + 0.20*rank(ret_20)` | 10日 |

分母非正、非有限或低于数值稳定下限时，该项记为缺失，不得以零替代制造有效分数。

### 6.2 短期反转族

现有 `reversal_3/5/10` 已定义为对应区间收益的负值，因此不再二次取负。

| ID | 分数公式 | 调仓 |
|---|---|---:|
| R1 | `rank(reversal_3)` | 5日 |
| R2 | `rank(reversal_5)` | 5日 |
| R3 | `rank(reversal_10)` | 10日 |
| R4 | `0.40*rank(-overnight_ret) + 0.35*rank(-intraday_ret) + 0.25*rank(-bias_20)` | 5日 |

### 6.3 低波防御族

| ID | 分数公式 | 调仓 |
|---|---|---:|
| D1 | `0.40*rank(-volatility_5) + 0.60*rank(-volatility_20)` | 10日 |
| D2 | `0.60*rank(-volatility_20) + 0.25*rank(-volatility_60) + 0.15*rank(-range_pct)` | 20日 |
| D3 | `0.45*rank(-atr_14_norm) + 0.30*rank(-range_pct) + 0.25*rank(-boll_width)` | 10日 |
| D4 | `0.60*rank(-volatility_20) + 0.25*rank(trend_strength) + 0.15*rank(ret_20)` | 20日 |

### 6.4 量价流动性族

| ID | 分数公式 | 调仓 |
|---|---|---:|
| L1 | `0.55*rank(vol_ratio_5) + 0.45*rank(turnover_5/turnover_20)` | 5日 |
| L2 | `0.50*rank(amt_ratio_5) + 0.30*rank(vol_ratio_5) + 0.20*rank(pvcorr_5)` | 5日 |
| L3 | `0.50*rank(obv_slope_10) + 0.50*rank(ad_slope_10)` | 10日 |
| L4 | `0.35*rank(mfi_14) + 0.30*rank(vwap_dev_20) + 0.20*rank(pvcorr_10) + 0.15*rank(pvbeta_20)` | 10日 |

### 6.5 稳健多因子族

E1 至 E4 只从 M/R/D/L 四族当前训练窗口可用的基础信号生成，不读取这些候选的 validation 或 test 表现。

| ID | 训练方法 | 调仓 |
|---|---|---:|
| E1 | 四族训练期合格袖套等权 | 10日 |
| E2 | 训练期收缩中位 Rank IC 加权 | 10日 |
| E3 | 训练期相关性聚类，每簇选稳定性最高的代表信号后等权 | 10日 |
| E4 | 将训练段切成四个连续子段，按方向一致性与最差子段 Rank IC 加权 | 20日 |

### 6.6 Qlib 模型影子族

| ID | 处理器 | 模型 | 调仓 |
|---|---|---|---:|
| Q1 | Alpha158 | LightGBM | 5日 |
| Q2 | Alpha360 | LightGBM | 5日 |
| Q3 | Alpha158 | XGBoost | 5日 |
| Q4 | Alpha158 | Ridge Linear | 5日 |

Qlib 模型参数沿用版本化 `quant/qlib/workflow_config.py` 配置并固定随机种子。每个外层窗口必须新建只属于该窗口的 Dataset、Recorder、模型和预测产物。模型只在 train 拟合，在 validation 产生候选比较分数；锁定后才允许对 test 预测。

依赖不可用、训练失败、模型哈希错误、预测含非有限值或预测覆盖率低于 95% 时，该 Qlib 候选在当前窗口为 `candidate_unavailable`。不得回退到规则 Alpha 并沿用同一候选身份。只要仍有其他合格候选，单个候选不可用不把整个 F4 工厂标记为系统阻断。

## 7. 组合政策

为了比较 Alpha 而不是无界搜索组合参数，所有候选使用同一安全政策，只按经济周期使用预登记调仓频率：

- `top_k=10`
- `target_gross_exposure=0.95`
- `max_name_weight=0.095`
- `max_industry_weight=0.25`
- `lot_size=100`
- `adv_participation=0.10`
- 调仓频率使用第 6 节固定值

本轮不再将 Top5/Top10 和 5/10/20 日全排列。若 Alpha 工厂通过 F4，组合参数优化必须作为后续独立版本进行，不得回看本轮 test 选择参数。

## 8. Purged walk-forward 与测试集隔离

沿用当前窗口参数：

- train：504 个交易日
- purge：20 个交易日
- validation：126 个交易日
- embargo：5 个交易日
- test：126 个交易日
- step：126 个交易日
- minimum windows：4

每个窗口必须按以下顺序运行：

```text
train 拟合 24 个候选
  -> validation 计算候选指标
  -> 固定排序选择 winner
  -> 将 winner 与全部身份哈希原子写入稳定 lock
  -> 重新读取并验证 lock
  -> 仅 winner 读取当前窗口 test
```

候选验证排序固定为：

1. `constraint_violation_count == 0` 且 `future_data_violation_count == 0`；
2. 费用后超额收益为正者优先；
3. 费用后超额收益降序；
4. Sharpe 降序；
5. 最大回撤绝对值升序；
6. 换手率升序；
7. `candidate_id` 字典序。

不得汇总所有窗口 validation 后选择一个全局候选再回放全部 test。后续窗口 validation 可能与较早窗口 test 重叠，这种做法会形成跨窗口泄漏。

## 9. 原子锁与崩溃恢复

每个窗口锁至少包含：

- `factory_run_id`
- `window_id`
- `candidate_id`
- `alpha_spec_hash`
- `alpha_fit_hash`
- `model_artifact_hash`，规则候选为 `null`
- `portfolio_policy_hash`
- `validation_leaderboard_hash`
- `selection_scope=current_window_validation_only`
- `test_scope=locked_winner_only`
- `promotion_state=research_only`
- `execution_authority=false`
- `lock_hash`

锁必须先写同目录唯一临时文件，再用 `os.replace` 原子提交。读取 test 前必须重新计算全部子件哈希和 `lock_hash`。稳定锁位于工厂最终目录之外的代际锁目录，测试运行崩溃不得删除它。

重跑时：

- 完整有效锁存在：复用锁，禁止重新运行 validation；允许重新运行缺失的 test。
- 锁缺失：正常运行 train 和 validation。
- 锁存在但身份或哈希不匹配：`f4_blocked`，不得覆盖。
- 同一身份的完整工厂报告存在：严格验证后幂等返回，不重新训练。

## 10. A 股组合回测与成本压力

保持当前回测语义：

- 前一交易日信号，下一交易日开盘成交；
- 停牌不可交易；
- 涨停不可买，跌停不可卖；
- 卖出遵守可卖数量和 T+1；
- 100 股整数手；
- 成交量不超过 20 日平均成交量的 10%；
- 资金不足时按整手缩量；
- 记录全部拒绝、未成交容量、费用、换手和现金比例。

基础成本继续为：

- 佣金 `0.0003`
- 最低佣金 `5`
- 卖出印花税 `0.0005`
- 过户费 `0.00001`
- 滑点 `0.0001`

每个 test 胜者运行 `1.0x`、`1.5x` 和 `2.0x` 成本。`1.0x` 是主结果，`1.5x` 用于诊断，`2.0x` 进入硬门禁。不得为了使策略通过而修改成本口径。

## 11. 最终 F4 门禁

沿用 `f4-gate-v4`，不修改阈值。只有同时满足以下条件才输出 `f4_research_candidate`：

1. 有效样本外窗口不少于 4 个；
2. 正超额收益窗口比例不低于 60%；
3. 合计费用后超额收益大于 0；
4. 各窗口 Sharpe 中位数不低于 0.80；
5. 任一窗口最大回撤不低于 -20%；
6. 双倍成本下合计超额收益大于 0；
7. 组合约束违规数为 0；
8. 未来数据违规数为 0。

状态语义：

- `f4_blocked`：数据、PIT、行业、基准、身份、完整性或未来数据失败。
- `candidate_unavailable`：单个候选依赖、拟合、模型或覆盖率失败。
- `candidate_validation_rejected`：候选可运行但未赢得当前窗口验证。
- `f4_rejected_exhausted`：24 个候选已按规则评估，最终 test 聚合仍未通过硬门禁。
- `f4_research_candidate`：全部门禁通过，但只有研究权限。

## 12. 证据与发布

新工厂使用独立目录，不复用 v1 目录：

```text
data/research/f4/factory-v2/<factory_run_id>/
  registry.json
  window_definitions.json
  alpha_fits.json
  model_artifacts.json
  validation_leaderboards.json
  candidate_selection_locks.json
  test_window_metrics.json
  cost_stress_metrics.json
  family_diagnostics.json
  factory_report.json
```

`factory_report.json` 必须记录所有子件 SHA-256、运行耗时、候选族状态、最终聚合指标、门禁版本、失败原因和权限字段。发布前验证：

- 工厂、数据、行业、基准和代码身份一致；
- 24 个候选 ID 唯一且与规范化内容哈希一致；
- 每个 test 指标都有对应且有效的窗口锁；
- 非胜者没有 test 产物；
- Qlib 模型和预测哈希与锁一致；
- 全部 JSON 为有限数值，不含 NaN 或 Infinity；
- 所有产物均为 `research_only` 且无执行权限。

只有全部子件验证通过后才原子切换 F4 最新研究指针。v1 产物和旧指针历史继续保留为审计事实。

## 13. 页面与报告

策略页面应明确展示：

- F4 工厂版本和数据截止日；
- 24 个候选的六族分布；
- 每个窗口 validation 胜者、候选族和锁哈希；
- 每族可用数、不可用数、胜出窗口数和淘汰原因；
- test 聚合指标和 1.0x/1.5x/2.0x 成本结果；
- 最终状态及全部门禁原因；
- `研究结果，不代表已获交易权限`。

页面不得把以下状态称为自动交易可用：候选生成完成、validation 胜出、模型训练成功、Qlib workflow 成功、工厂运行成功或 `f4_rejected_exhausted`。

## 14. 错误处理

- 单个规则候选输入不足：当前候选 `candidate_unavailable`，记录覆盖率和缺失字段。
- 单个 Qlib 候选依赖或模型失败：当前候选 `candidate_unavailable`，不得静默回退。
- 当前窗口全部候选不可用：窗口拒绝；导致有效窗口少于 4 时最终 `f4_blocked`。
- test 前锁校验失败：立即 `f4_blocked`。
- test 或成本回测失败：保留锁和失败账本，重试只能复用同一锁。
- 发布失败：不切换最新指针，保留上一完整 F4 版本。
- 产物篡改或跨版本混用：`f4_blocked`，不得自动修补或覆盖原证据。

## 15. 测试策略

实现必须测试驱动，至少覆盖：

### 15.1 候选注册表

- 恰好 24 个候选、六族各 4 个；
- 所有候选 ID 唯一、稳定且覆盖 Alpha 与组合政策；
- 修改公式、输入、调仓周期或风险参数会改变候选 ID；
- 非法 TopK、敞口、单票、行业、整手或容量参数失败关闭；
- 基本面因子不能进入 v2 注册表。

### 15.2 Alpha 计算

- 每个固定公式有手工可验证的小样本结果；
- 价格尺度特征正确无量纲化；
- MAD 去极值、行业去中心化和百分位排名顺序固定；
- 非有限分母、缺失输入和不足覆盖率失败关闭；
- 相关性去冗余和同分排序确定性；
- 候选阈值和 Alpha 规格真实传入拟合与评分，不再只是登记字段。

### 15.3 Qlib 适配器

- train、validation、test 数据段严格分离；
- 固定种子重复训练产生一致身份；
- 模型/预测哈希篡改失败关闭；
- 依赖不可用、预测缺失、非有限值或覆盖率不足不会回退规则 Alpha；
- validation 未锁定前不得生成 test 预测。

### 15.4 嵌套选择与恢复

- 全部候选只读取当前窗口 validation；
- 只有锁定胜者读取当前窗口 test；
- 后续窗口 validation 不参与早期窗口胜者选择；
- test 运行崩溃后锁仍存在，重试不重跑 validation；
- 锁缺失、身份漂移、哈希错误和策略错配失败关闭；
- 同一完整工厂身份重复运行是幂等 no-op。

### 15.5 门禁与发布

- 1.0x、1.5x、2.0x 成本均使用同一锁定胜者；
- 原有 F4 v4 门槛保持不变；
- 全部失败诚实输出 `f4_rejected_exhausted`；
- 合成通过数据只能输出 `f4_research_candidate` 和无执行权限；
- 任一证据缺失、哈希错误、NaN、权限错误或跨版本漂移不切指针；
- v1 历史产物不被覆盖。

### 15.6 集成回归

- 相关 Python 定向测试；
- 全量 Python 回归；
- 全部 Node 契约；
- TypeScript；
- Vite 构建；
- Web 验证；
- UI 验证和浏览器控制台检查。

## 16. 实施顺序

1. 新增 v2 候选和 Alpha 规格契约及红测。
2. 实现规则 Alpha 预处理、拟合和评分适配器。
3. 实现 Qlib 窗口模型适配器和产物身份。
4. 将 Alpha 适配器接入逐窗口嵌套选择，升级稳定锁。
5. 扩展组合回测、族级诊断和 v2 原子发布。
6. 更新策略 API、页面、README 和 `docs/XUANJI_HANDOFF.md`。
7. 完成定向与全量回归。
8. 在当前通过的数据版本上运行完整六年样本外验证。
9. 报告真实结果；失败时保留原因，不调整门槛后重跑。

## 17. 完成判定

“v2 实现完成”必须同时满足：

- 24 个候选与六族契约实现并通过测试；
- Alpha 规格真实贯穿训练、评分、锁和 test；
- Qlib 候选具备同窗口、同身份、无回退的样本外路径；
- 原子锁、崩溃恢复、证据发布和读取端失败关闭通过测试；
- 全部规定回归通过；
- README 和交接文档准确更新。

“重新样本外验证完成”还必须满足：

- 使用当前通过的完整六年 PIT 数据、历史行业和基准；
- 生成不少于 4 个有效 test 窗口；
- 24 个候选按预登记规则完成验证或留下明确不可用证据；
- 发布完整 v2 工厂证据和族级诊断；
- 给出真实 F4 门禁结果。

“策略通过”只在最终结果为 `f4_research_candidate` 时成立；即使成立，也仍为 `research_only`。如果最终为 `f4_rejected_exhausted`，实现和重新验证仍可判定完成，但不得宣称获得有效策略或交易权限。
