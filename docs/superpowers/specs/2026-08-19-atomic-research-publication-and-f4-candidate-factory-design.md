# 原子研究发布与 F4 确定性候选工厂设计

**日期：** 2026-08-19  
**状态：** 用户已批准方案 A  
**权限边界：** 全部产物仅供研究；`promotion_state=research_only`、`execution_authority=false`，不得降低 F4 门槛、不得产生真实交易权限。

## 1. 问题与目标

当前日终链路先发布数据快照，再依次覆盖因子截面、IC 评估和研究选股。更新期间，读取端会把“上一完整研究版本”与“正在构建的数据版本”比较，产生可预期但对用户可见的版本不一致。F4 又只验证一个固定 `ic-weighted-top20-v1` 候选，拒绝后没有确定性下一步，因而“工程任务成功”与“研究闭环完成”被错误混用。

本设计完成两个闭环：

1. 日终研究采用版本化暂存目录和单一原子指针，页面在刷新期间继续读取上一完整版本并明确显示目标版本；
2. F4 拒绝后运行有限、预登记、可复现的候选工厂，只能由最终保留窗口门禁决定 `f4_research_candidate`，全部失败则诚实落为 `f4_rejected_exhausted`。

## 2. 日终研究两阶段发布

权威目录：

```text
data/research/daily/
  status.json
  latest.json
  generations/<generation_id>/
    factor_snapshot_latest.json
    factor_evaluation.json
    selection.json
    manifest.json
```

`status.json` 只描述运行态：`refreshing/completed/failed`、目标交易日、目标数据版本、开始/结束时间、失败原因和上一完整 generation。`latest.json` 是唯一完成版本指针，只有三个产物完成同版本校验后才用 `os.replace` 原子切换。

运行期间不得覆盖 `latest.json`。因子和策略只读 API 解析 `latest.json` 指向的产物，并附带 `research_refresh`；当目标版本仍在生成时返回上一完整版本，明确 `is_current=false`、`target_date` 和 `refresh_state=refreshing`，不得称为当日实时结果。

固定路径 `data/factor_snapshot_latest.json`、`data/factor_evaluation.json` 和 `data/research/selections/latest.json` 作为兼容镜像，在指针切换后再原子更新；它们不是新链路的跨文件一致性权威。

失败时保留上一完整 pointer，`status.json` 记录失败原因；下一次重试使用新的暂存目录。孤立暂存目录不得被读取端使用。

## 3. F4 确定性候选工厂

候选注册表固定为六个组合：

- `top_k ∈ {5, 10}`；
- `rebalance_bars ∈ {5, 10, 20}`；
- 因子准入保持当前门槛：绝对中位 Rank IC `0.02`、方向一致性 `0.60`、至少 3 个、最多 10 个；
- 个股、行业、整手、容量和成本模型沿用现有硬约束；任何候选均不得超过 F5 的 10 只上限，总目标暴露不得超过 `0.95`。Top5/Top10 的单票上限分别不得超过 `0.19/0.095`，同时继续受全局单票 20% 硬限制约束。

候选规格使用规范 JSON 的 SHA-256 生成不可变 `candidate_id`。候选工厂版本、输入数据身份和注册表共同生成 `factory_run_id`，相同输入必须幂等复用。

现有每个 walk-forward window 已分为 `train_dates`、`valid_dates`、`test_dates`。由于滚动窗口的后续 validation 可能与较早 test 重叠，禁止先汇总所有 validation 再选择一个全局候选。候选工厂必须按每个外层窗口独立执行嵌套选择：

```text
当前窗口 train 拟合全部候选
  -> 当前窗口 validation 比较
  -> 原子写入该窗口 candidate_selection_lock
  -> 只允许该 winner 读取当前窗口 test
```

每个窗口的 validation 按以下稳定顺序锁定候选：

1. 约束和未来数据违规必须为 0；
2. 正超额窗口占比降序；
3. 扣费后超额收益降序；
4. Sharpe 降序；
5. 最大回撤绝对值升序；
6. 换手率升序；
7. `candidate_id` 字典序。

每个窗口只有自己的已锁定候选可以读取该窗口 `test_dates`；其他候选不得生成该窗口测试指标。最终聚合的是“候选选择程序”的多窗口样本外表现，而不是事后挑选的静态最佳参数。门槛保持不变。通过时状态仍为 `f4_research_candidate`；失败时为 `f4_rejected`，候选池无更多未评估项时增加 `candidate_factory_status=exhausted`，页面显示 `f4_rejected_exhausted` 语义，但不得伪造通过。

工厂证据写入：

```text
data/research/f4/factory/<factory_run_id>/
  registry.json
  validation_leaderboard.json
  candidate_selection_locks.json
  factory_report.json
```

F4 原有九份不可变证据继续保留，并增加 `factory_run_id`、逐窗口选中候选哈希和 validation/test 职责说明。每个窗口的 selection lock 必须在该窗口任何 test 读取前原子落盘并通过哈希复核。

## 4. 调度、API 与页面

- `strategy_weekly` 调用候选工厂驱动的 `validate_strategy_portfolios.py --once`，不再只跑固定 Top20。
- `/api/strategy` 的 `research_selection` 是纯只读动作，加入无需控制令牌的只读白名单。
- 因子页显示“正在更新目标日期，当前展示上一完整版本”；不再把可控刷新窗口显示成系统错误。
- 策略页展示候选数量、选中规格、validation 排名、最终 test 门禁和“已穷尽/待下一数据版本”，明确区分研究失败与系统故障。
- F5 只接受最终 `f4_research_candidate`，其余状态继续失败关闭。

## 5. 测试与完成判定

必须先出现失败测试，再完成实现：

1. 刷新开始后，完成 pointer 不变且 API 返回上一完整版本和 refreshing 元数据；
2. 任一步失败不发布半成品，状态为 failed；
3. 三产物同版本后才切换 pointer，兼容镜像内容一致；
4. `research_selection` 无令牌只读访问成功，控制动作仍拒绝；
5. 候选注册表有界、稳定、均不超过 10 股；
6. 候选选择只读取 validation 指标，未选候选不运行 test；
7. 最终门槛不变，全部失败落为 exhausted 且无执行权限；
8. 相关 Python、全部 Node 契约、TypeScript、Vite、Web/UI 验证全部通过；
9. README 与 `docs/XUANJI_HANDOFF.md` 写明权威指针、候选工厂和失败关闭边界。
