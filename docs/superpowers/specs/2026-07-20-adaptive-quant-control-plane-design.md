# A股自适应量化控制平面设计

更新日期：2026-07-20

## 1. 状态

已确认方向：

- 一次设计并建设 P0-P3 完整能力。
- 市场状态采用三状态模型。
- 动态仓位默认使用四分之一凯利。
- 所有新增能力默认 `shadow-only`。
- 新能力只能收紧现有交易约束，不能绕过 verifier、risk gateway、
  T+1、涨跌停、停牌、现金、仓位、换手、最大回撤或 Kill Switch。

本设计不连接真实券商，不授权真实资金交易。

## 2. 背景与问题

当前项目已经具备：

- Qlib 独立研究环境、模型注册表和 walk-forward 评估。
- 因子与策略候选、shadow、paper 和人工批准边界。
- 官方市场情绪 shadow 信号。
- AI 目标组合、统一决策、verifier 和 risk gateway。
- 模拟盘目标权重执行、账户状态和审计回放。

当前缺口是：

1. 模型和因子的运行期健康状态没有统一契约。
2. 已批准对象缺少独立的漂移隔离机制。
3. 市场情绪不是正式的市场状态模型，不能用于策略适配。
4. 不同市场状态下的策略表现没有形成可审计路由矩阵。
5. 目标权重主要由固定配置或 LLM 给出，缺少确定性动态仓位层。
6. Qlib 研究库与运行时交易库之间缺少只读、版本化的研究快照桥接。

目标不是让 AI 高频修改模型，而是建立可检测、可降级、可回放的
自适应控制平面。

## 3. 方案选择

### 方案 A：直接自动接管

HMM 直接切换策略，凯利直接修改仓位。

不采用。状态误判、收益估计误差或数据中断可能立即影响模拟盘。

### 方案 B：完整能力、分级激活

一次建设 P0-P3，但按照权限等级逐级启用：

```text
observe
  -> route_shadow
  -> size_shadow
  -> paper_guarded
```

采用此方案。它能完成完整架构，同时保留回测、影子验证和人工批准门槛。

### 方案 C：仅 Qlib 离线研究

只评估模型，不接入运行时闭环。

不采用。无法完成盘中健康检查、策略路由和动态仓位审计。

## 4. 总体架构

```text
Qlib datasets / experiments / models
        |
        | 只读、版本化研究快照
        v
P0 Model Health & Drift Engine
        |
        +-------------------------------+
        |                               |
        v                               v
P1 Market Regime Engine          Runtime Eligibility Gate
        |                               |
        v                               |
P2 Strategy Router <--------------------+
        |
        v
AI Portfolio Proposal / Existing Strategy Signals
        |
        v
P3 Deterministic Position Sizer
        |
        v
normalize_ai_decision
        |
        v
Verifier -> Risk Gateway -> Paper Trader
```

职责边界：

- Qlib 继续使用独立数据目录和 `qlib_meta.db`。
- Qlib 研究代码不写 `data/quant.db`，不直接生成订单。
- 运行时通过版本化 JSON 快照读取研究结果。
- LLM 可以提交候选股票、理由和目标权重，但不能计算或覆盖漂移状态、
  市场状态、凯利上限和硬风控结果。
- 新增控制平面不能设置 `trade_allowed=true`。

## 5. 目录与模块

新增目录：

```text
quant/adaptive/
  contracts.py
  drift.py
  regime.py
  routing.py
  sizing.py
  activation.py
```

运行入口：

```text
scripts/adaptive_snapshot.py
scripts/adaptive_health.py
scripts/adaptive_regime.py
scripts/adaptive_control.py
```

职责：

| 模块 | 职责 |
|---|---|
| `contracts.py` | 校验所有输入输出、版本和权限字段 |
| `drift.py` | 特征、预测和绩效漂移计算 |
| `regime.py` | 市场状态训练产物加载和运行时推断 |
| `routing.py` | 根据状态概率和历史表现生成策略权重 |
| `sizing.py` | 四分之一凯利、协方差、流动性和硬上限裁剪 |
| `activation.py` | 激活等级、权限检查和安全降级 |
| `adaptive_snapshot.py` | 从 Qlib 注册表导出只读研究快照 |
| `adaptive_health.py` | 盘后模型健康评估 |
| `adaptive_regime.py` | 盘后状态模型训练或刷新 |
| `adaptive_control.py` | 组合运行 P0-P3，发布 shadow 或 guarded 输出 |

## 6. 配置契约

运行时配置键：

```text
adaptive:config
```

默认值：

```json
{
  "enabled": true,
  "activation_level": "observe",
  "regime_states": 3,
  "kelly_fraction": 0.25,
  "allow_leverage": false,
  "allow_short": false,
  "min_regime_confidence": 0.65,
  "regime_confirmation_windows": 2,
  "drift_failure_windows": 3,
  "max_strategy_weight": 0.50,
  "max_adaptive_gross_exposure_pct": 80.0,
  "fallback_mode": "existing_policy",
  "human_approval_required": true
}
```

允许的激活等级：

| 等级 | 权限 |
|---|---|
| `observe` | 只记录健康、漂移和状态，不修改任何权重 |
| `route_shadow` | 生成影子策略权重，不进入决策 |
| `size_shadow` | 生成影子策略和仓位，与现有结果对比 |
| `paper_guarded` | 可收紧模拟盘目标权重，仍须 verifier 和 risk gateway |

禁止通过普通前端配置直接进入 `paper_guarded`。该等级必须通过固定控制动作、
人工确认和审计事件更新。

## 7. 研究快照桥接

Qlib 导出文件：

```text
C:\Users\HYSHEN\XuanJiQuant\data\qlib\runtime_exports\
  adaptive-research-latest.json
  adaptive-research-<timestamp>.json
```

输出契约：

```json
{
  "schema_version": "adaptive-research.v1",
  "generated_at": "2026-07-20T18:30:00+08:00",
  "dataset": {
    "id": "a_share_6y_daily",
    "latest_date": "2026-07-20",
    "quality_passed": true,
    "manifest_hash": "..."
  },
  "models": [
    {
      "model_id": "...",
      "experiment_id": "...",
      "model_type": "lightgbm",
      "status": "candidate|shadow|approved|rejected",
      "artifact_sha256": "...",
      "features": [],
      "training_distribution": {},
      "walk_forward_metrics": {},
      "regime_metrics": {}
    }
  ]
}
```

约束：

- 临时文件写完并校验后原子替换 `latest`。
- 快照必须包含 schema、时间、数据版本和模型哈希。
- 运行时只读快照，不加载任意用户指定路径。
- 哈希、schema、时间或数据质量失败时拒绝使用新快照，保留上一有效版本。

## 8. P0 模型健康与漂移

### 8.1 健康状态

晋升状态与运行健康状态分离：

```text
promotion_state:
  candidate | shadow | paper_active | production_candidate | approved | retired

health_state:
  healthy | watch | degraded | quarantined
```

运行时可用条件：

```text
promotion_state is eligible
AND health_state != quarantined
AND artifact/data freshness valid
```

这样能够保留“谁批准了模型”的生命周期证据，同时允许运行期立即隔离失效模型。

### 8.2 漂移指标

第一阶段必须支持：

- 数值特征 PSI。
- 数值特征 KS 统计量和 p 值。
- 缺失率变化。
- 预测分布 PSI。
- 滚动 Rank IC、ICIR 和正 IC 比例。
- 成本后收益、Sharpe、最大回撤和换手率。
- 预测覆盖率、样本数和数据新鲜度。
- 不同市场状态下的分段指标。

避免把单个统计量直接当作停用依据。健康状态由多项证据和连续窗口决定。

### 8.3 状态转换

```text
healthy
  -> watch       单窗口告警
  -> degraded    连续多个窗口或关键绩效失效
  -> quarantined 连续失败、数据污染或产物不可信
```

恢复规则：

- `watch` 可以在连续正常窗口后自动恢复。
- `degraded` 只可恢复到 `watch`，不能直接恢复 `healthy`。
- `quarantined` 必须经过重新训练、完整验证和人工批准。
- 数据质量硬失败直接进入 `quarantined`。

输出键：

```text
adaptive:model_health:latest
adaptive:model_health:<model_id>
adaptive:model_health:history:<model_id>
```

## 9. P1 三状态市场模型

### 9.1 状态语义

模型原始状态编号不能直接解释。训练后按照收益、波动和流动性特征排序并映射：

```text
risk_on
range
stress
```

### 9.2 初始特征

只使用可点时获得的市场级特征：

- 沪深300的 5、20、60 日收益。
- 中证1000的 5、20 日收益。
- 20 日实现波动率。
- 上涨股票占比和市场宽度。
- 全市场成交额及其滚动 z-score。
- 涨停数减跌停数。
- 行业收益离散度。
- 授权 CFFEX 数据可用时的基差和持仓变化。

官方市场情绪可以作为附加 shadow 特征，但不能成为唯一状态依据。

### 9.3 训练和推断

- 模型在 Qlib 独立环境盘后训练。
- 正式实现使用成熟 HMM 库，不在项目内手写核心 HMM 算法。
- 当前环境未安装 HMM 专用依赖；实施时加入 Qlib 独立依赖清单。
- 每个 walk-forward 窗口只使用训练期拟合标准化参数和模型。
- 产物保存特征顺序、均值、方差、转移矩阵、状态映射、哈希和训练区间。
- 运行时只加载通过校验的不可变产物。

输出：

```json
{
  "schema_version": "adaptive-regime.v1",
  "as_of": "2026-07-20",
  "state": "range",
  "probabilities": {
    "risk_on": 0.20,
    "range": 0.70,
    "stress": 0.10
  },
  "confidence": 0.70,
  "model_id": "...",
  "artifact_sha256": "...",
  "stale": false,
  "mode": "shadow_only",
  "can_change_trade_policy": false,
  "can_trigger_order": false
}
```

### 9.4 防抖

- 置信度低于 `min_regime_confidence` 时不切换状态。
- 新状态至少连续出现 `regime_confirmation_windows` 个窗口才生效。
- `stress` 概率达到经回测确认的紧急阈值时，允许跳过普通确认，但只能收紧风险。
- 模型或数据不可用时回退现有策略，不生成乐观状态。

输出键：

```text
adaptive:regime:latest
adaptive:regime:history
```

## 10. P2 策略路由

### 10.1 输入

- 通过晋升门槛的策略列表。
- 每个策略的 `health_state`。
- 各市场状态下的样本外成本后指标。
- 当前状态概率。
- 现有硬风险配置。

### 10.2 路由原则

- 不采用单策略 winner-take-all。
- 不允许 `quarantined` 策略获得权重。
- 不允许 LLM 修改路由分数。
- 权重必须归一化并保留现金。
- 单策略权重不得超过 `max_strategy_weight`。
- 样本不足的状态分段使用收缩后的整体指标，不使用极端小样本结果。

建议分数：

```text
strategy_score =
  regime_probability_weighted_after_cost_score
  * health_multiplier
  * evidence_multiplier
  * stability_multiplier
```

初始策略类型映射：

| 状态 | 倾向 |
|---|---|
| `risk_on` | 趋势、动量、质量成长 |
| `range` | 反转、均值回归、低换手多因子 |
| `stress` | 防御、低波动、现金和风险降低 |

这些映射只是先验，最终权重必须由 walk-forward 分段证据校准。

输出：

```json
{
  "schema_version": "adaptive-routing.v1",
  "as_of": "2026-07-20",
  "regime": "range",
  "regime_confidence": 0.70,
  "strategy_weights": [
    {
      "strategy_id": "ma_cross",
      "weight": 0.30,
      "health_state": "healthy",
      "evidence": {}
    }
  ],
  "cash_weight": 0.40,
  "mode": "shadow_only",
  "can_trigger_order": false
}
```

输出键：

```text
adaptive:routing:latest
adaptive:routing:history
```

## 11. P3 确定性动态仓位

### 11.1 位置

动态仓位位于 LLM/策略目标组合之后、`normalize_ai_decision` 和 verifier 之前。

它只能裁剪目标权重：

```text
LLM/策略提出目标
  -> adaptive sizing 裁剪
  -> normalize
  -> verifier
  -> risk gateway
```

### 11.2 四分之一凯利

单资产基础形式：

```text
full_kelly = expected_after_cost_excess_return / variance
fractional_kelly = max(0, full_kelly) * 0.25
```

预期收益必须使用：

- 样本外数据。
- 手续费、滑点和冲击成本后的收益。
- 收缩估计，避免直接使用短窗口均值。
- 至少一个规定的最小样本量。

多资产时结合协方差和策略风险预算。初版可以使用稳定的对角收缩，
不采用不受约束的矩阵逆。

### 11.3 最终权重

```text
final_weight = min(
  proposed_weight,
  fractional_kelly_cap,
  regime_position_cap,
  liquidity_cap,
  adaptive_single_position_cap,
  hard_max_position_pct
)
```

总敞口：

```text
final_gross_exposure = min(
  sum(final_weights),
  regime_gross_cap,
  max_adaptive_gross_exposure_pct,
  hard_max_gross_exposure_pct
)
```

规则：

- 不允许负权重。
- 不允许杠杆。
- 不允许通过自适应配置放宽硬上限。
- 买入权重必须符合A股整手和现金要求。
- 流动性不足、方差无效、预期收益非正或样本不足时，新增仓位上限为零。
- 已有持仓的风险降低卖出继续使用现有减仓通道。
- 自适应层不可阻止合法的风险降低操作。

输出：

```json
{
  "schema_version": "adaptive-sizing.v1",
  "as_of": "2026-07-20",
  "kelly_fraction": 0.25,
  "original_weights": [],
  "sized_weights": [],
  "cash_target_pct": 0,
  "cuts": [],
  "mode": "shadow_only",
  "can_increase_hard_limit": false,
  "can_trigger_order": false
}
```

输出键：

```text
adaptive:sizing:latest
adaptive:sizing:history
```

## 12. 与现有 AI 闭环集成

在 `scripts/ai_loop.py` 中增加独立步骤：

```text
Step 1.5  P0 模型健康快照
Step 1.6  P1 市场状态推断
Step 6.65 P2 策略路由
Step 6.75 P3 目标权重裁剪
```

集成规则：

- `observe`：只把结果写入 `results["steps"]` 和审计。
- `route_shadow`：路由结果写入 shadow，不修改 `portfolio_plan`。
- `size_shadow`：同时保存原目标和影子裁剪结果，不修改决策。
- `paper_guarded`：在校验通过时用裁剪后的权重替换目标权重。
- 任一步异常均不得使交易权限更宽松。
- `paper_guarded` 下关键输入异常时，保持现有策略或收紧为
  `no_new_position`，具体由失败类型决定。

统一决策新增可选字段：

```json
{
  "adaptive": {
    "activation_level": "observe",
    "health_snapshot_id": "...",
    "regime": {},
    "routing": {},
    "sizing": {},
    "reason_codes": []
  }
}
```

## 13. 失败与降级

| 失败 | 降级行为 |
|---|---|
| 研究快照缺失 | 保持上一有效快照；无有效快照则只运行现有系统 |
| 快照哈希或schema错误 | 拒绝快照并记录高优先级审计事件 |
| HMM依赖缺失 | 状态引擎不可用，保持 `observe`，不推断状态 |
| 状态数据过期 | 标记 stale，不切换状态 |
| 状态置信度不足 | 保持确认状态或 `range` |
| 漂移指标样本不足 | `watch`，不得误判为 `healthy` |
| 活跃模型 quarantined | 禁止该模型进入路由，回退基线策略 |
| 凯利输入无效 | 新增仓位上限为零或回退固定仓位，取决于激活等级 |
| 自适应控制异常 | 不生成更积极的目标；保留现有硬风控 |
| verifier失败 | `trade_allowed=false`，现有行为不变 |

所有异常必须：

- 写入结构化原因码。
- 保留输入版本和产物哈希。
- 不记录密钥。
- 可在审计回放中重建当时决策。

## 14. 审计

新增事件：

```text
adaptive_snapshot_loaded
adaptive_snapshot_rejected
model_health_changed
model_quarantined
regime_inferred
regime_changed
strategy_route_generated
position_sizing_generated
adaptive_weight_cut
adaptive_activation_changed
adaptive_fallback
```

每个事件至少包含：

- `generated_at`
- `as_of`
- `activation_level`
- 输入数据版本
- 模型或产物哈希
- 前值、后值
- 原因码
- 是否影响模拟盘

## 15. 前端

不在驾驶舱增加新的大块配置。

驾驶舱只显示：

- 自适应控制等级。
- 当前市场状态、概率和置信度。
- 健康模型数、观察数、隔离数。
- 当前是否只在 shadow。
- 最近一次降级原因。

详细配置和诊断放入“策略运行”页面：

- 模型健康表。
- 漂移指标趋势。
- 市场状态时间线。
- 固定方案与自适应方案对比。
- 策略路由权重。
- 原始权重与裁剪后权重。
- 激活等级变更入口。

`paper_guarded` 激活必须二次确认，并显示影响范围和审计说明。

## 16. 测试

### 16.1 单元测试

- PSI、KS、缺失率和预测漂移。
- 健康状态转换和连续窗口规则。
- `quarantined` 模型不能进入运行时集合。
- 市场状态概率归一、状态映射和防抖。
- 状态特征无未来数据。
- 策略权重非负、归一和单策略上限。
- 四分之一凯利公式、收缩和无效输入。
- 最终权重永不超过任一硬上限。
- 自适应层不能阻止合法减仓。
- 任意污染权限字段都不能获得下单权限。

### 16.2 集成测试

- Qlib 快照只读桥接。
- Qlib 代码不写 `data/quant.db`。
- `observe` 不修改目标权重。
- `route_shadow` 不修改目标权重。
- `size_shadow` 同时保存固定和自适应结果。
- `paper_guarded` 只能减少或保持目标风险。
- verifier 和 risk gateway 仍是最终门禁。
- 模型、数据或依赖失败时安全降级。
- AI 闭环、paper trader 和审计回放保持兼容。

### 16.3 研究验证

- 多窗口 point-in-time walk-forward。
- 等权数据与不同时间衰减半衰期比较。
- 固定策略与自适应策略比较。
- 分状态样本数量和置信区间。
- 手续费、滑点、涨跌停、停牌、T+1和成交量约束。
- 参数选择必须嵌套在训练/验证窗口内。
- 禁止仅用2024年单一年份证明全行情有效。

### 16.4 浏览器验证

- 桌面和窄屏无重叠、横向溢出和信息重复。
- `shadow-only` 状态清晰。
- 任何诊断页操作不提交模拟订单。
- 激活等级确认流程不能被普通刷新或前端状态绕过。

## 17. 激活门槛

### `observe -> route_shadow`

- 快照桥接、健康评估和状态推断连续稳定运行。
- 无前视、数据版本和哈希测试通过。
- 状态切换频率和持续时间合理。

### `route_shadow -> size_shadow`

- 路由权重在多个 walk-forward 窗口中不劣于固定基线。
- 成本后表现和最大回撤通过预设硬门槛。
- 不存在单策略长期垄断权重。

### `size_shadow -> paper_guarded`

- 至少20个交易日影子对比。
- 自适应权重从未超过硬风控。
- 自适应方案的成本后收益、回撤和换手均有完整证据。
- 故障演练证明能够回退现有策略。
- 人工确认并写入审计事件。

进入 `paper_guarded` 也不代表可以连接真实券商。

## 18. 实施顺序

1. 建立 `contracts.py`、激活配置和只读研究快照。
2. 实现 P0 漂移指标、健康状态和运行时资格门。
3. 修复已批准对象缺少运行期隔离的问题。
4. 在 Qlib 环境实现三状态模型训练和不可变产物。
5. 实现运行时状态推断、置信度和防抖。
6. 实现策略分状态绩效矩阵和影子路由器。
7. 实现四分之一凯利和确定性仓位裁剪。
8. 接入 AI 闭环，默认 `observe`。
9. 接入策略运行页面和驾驶舱摘要。
10. 完成回测、影子对比、故障演练和浏览器验证。

## 19. 非目标

- 不实现真实券商自动下单。
- 不让 LLM 训练、批准或直接切换 HMM 模型。
- 不让市场情绪直接替代市场状态。
- 不根据一次异常自动永久退役模型。
- 不允许动态仓位提高硬风控上限。
- 不把单次回测、接口成功或页面绿灯解释为收益有效性。

## 20. 完成定义

本阶段开发完成需要同时满足：

- P0-P3 均有独立模块、契约、测试和审计。
- 默认激活等级为 `observe`。
- 固定基线结果和自适应影子结果可并列回放。
- 所有新增输出均不能直接触发订单。
- `paper_guarded` 未经人工确认不可启用。
- 现有模拟盘、verifier、risk gateway 和硬限制测试全部通过。
- README 明确说明数据、模型、shadow、paper 和真实交易边界。
