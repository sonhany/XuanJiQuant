# 数据、因子与策略研究调度设计

日期：2026-08-18  
状态：设计已确认，等待书面规格审阅  
适用工作区：`C:\Users\HYSHEN\XuanJiQuant`

## 1. 目标

建立一条由版本门禁驱动、可恢复且不重叠的确定性研究流水线，使数据层、因子层、每日研究选股组合和策略层使用明确且互不冲突的时间安排。

系统必须满足：

1. 每个交易日只发布一个通过质量门禁的权威日线快照。
2. 因子评估只消费当前权威快照，并在新数据版本到达后执行一次。
3. 每日研究选股组合只在同版本因子产物成功后生成一次。
4. Qlib 六年 PIT 数据先完成周更新，F4 策略验证再运行。
5. 任何过期、缺失、版本不一致或失败产物均不得被下游冒充为当前成功结果。
6. 所有产物保持 `promotion_state=research_only`、`execution_authority=false`，不得产生订单或恢复已退休的 Agent/自动执行链。

## 2. 非目标

- 不启用模拟盘或实盘交易。
- 不改变因子有效性、F4 绩效或硬风险门禁阈值。
- 不把 `f4_rejected` 自动改写为候选、批准或生产状态。
- 不引入 AI Agent 作为调度、选股或晋升所有者。
- 不把日内行情轮询等同于收盘后完整日线发布。
- 不机械改写历史日志、数据库审计记录或旧名称。

## 3. 调度原则

采用“少量外部时钟 + 内部事件链”，不为每个阶段设置互相独立的固定闹钟。

外部时钟只负责启动两条入口链：

1. 交易日后日常研究链：数据 → 因子 → 每日研究组合。
2. 周末重研究链：Qlib PIT 更新 → F4 策略与组合验证。

阶段之间以版本、质量和终态证据衔接。上游未成功时，下游失败关闭。

## 4. 权威时间安排

| 层级 | 外部启动时间 | 实际执行条件 | 目标完成时间 | 频率 |
|---|---|---|---|---|
| 日线数据层 | 周一至周五 16:20 | `get_expected_date` 已把当日视为完整交易日；节假日保持最近交易日 | 通常 16:35 前，最长 3 小时 | 每个交易日一次 |
| 因子层 | 无独立闹钟 | 当日 `DataSnapshot` 为 `passed/fresh` 且出现未评估 `content_hash` 后立即触发 | 通常 17:10 前，最长 2 小时 | 每个新数据版本一次 |
| 每日研究组合 | 无独立闹钟 | 因子产物日期、快照 ID、数据版本、股票池版本和权限全部匹配后立即触发 | 因子完成后数分钟内 | 每个交易日一次 |
| Qlib 六年 PIT | 周六 18:30 | 最新交易周数据可用；执行 manifest、生命周期、行业和基准质量门禁 | 周日策略任务前 | 每周一次；首个周末按既有月度/季度模式升级 |
| F4 策略层 | 周日 10:00 | 周五因子成功且周六 Qlib/PIT、行业、基准证据全部成功并版本一致 | 当日完成，最长 4 小时 | 每周一次 |

`DAILY_BAR_READY_TIME=15:30` 继续表示“当日日线可以被视为预期完整”的最早时间；16:20 是为上游落库预留缓冲后的日常研究入口时间。

## 5. 日常研究链

### 5.1 数据层

`scripts/run_daily_research_pipeline.py` 保持日常入口所有者。它计算预期最新完整交易日，只有现有快照未满足以下条件时才调用 `scripts/daily_update.py`：

- `as_of == expected_date`；
- `quality_status == passed`；
- `freshness_status == fresh`；
- `content_hash` 非空；
- `expected_count` 与 `available_count` 均大于零。

数据更新完成后重新读取快照，不接受更新命令返回码代替快照质量证据。

### 5.2 因子层

数据门禁通过后，日常入口调用 `scripts/research_training_scheduler.py --once`。`factor_daily` 的幂等键保持：

```text
factor_daily:<market_date>:<data_version>:<factor_factory_version>
```

同一版本已经成功时只允许经完整产物校验后登记 `factor_version_already_evaluated/no_op`；不能仅凭文件存在跳过。因子产物必须满足：

- `data_end_date/latest_kline_date` 等于权威交易日；
- `snapshot_id` 和 `data_version` 等于当前快照；
- 因子列表非空；
- `promotion_state=research_only`；
- `execution_authority=false`。

### 5.3 每日研究选股组合

新增确定性研究组合生成入口，由日常流水线在因子门禁通过后调用。它不是策略训练，也不拥有执行权限。

幂等键固定为：

```text
research_selection_daily:<market_date>:<data_version>:<factor_version>:<f4_validation_id>:<portfolio_policy_version>
```

生成条件：

1. 因子快照、因子评估与当前数据快照完全同版本。
2. F4 最新证据存在、可解析且保持研究权限边界。
3. PIT 行业版本可追溯；缺失行业进入 `industry_unknown` 并受未知行业上限约束。
4. 股票池仅包含因子输入契约认可的当日合格标的。
5. 单票、行业和现金权重满足当前 `PortfolioPolicy`。

产物写入：

```text
data/research/selections/<portfolio_id>/portfolio.json
data/research/selections/latest.json
```

当 F4 为 `f4_rejected` 时仍可生成诊断组合，但必须同时写入：

- `selection_status=diagnostic_research_portfolio`；
- `source_validation_rejected=true`；
- `not_a_trade_signal=true`；
- `promotion_state=research_only`；
- `execution_authority=false`。

页面不得把诊断组合描述为可交易、已批准或生产组合。

## 6. 周末重研究链

### 6.1 Qlib 周任务

保留 `XuanJiQuant-Qlib-Weekly`，周六 18:30 启动。该任务必须产生可校验的终态和版本证据；进程返回码、manifest、质量报告、行业数据和基准数据共同决定是否成功。

首个周六的既有月度或季度模式继续生效，但不改变下游接口。周任务失败时不得用上一周 Qlib 版本冒充本周前置条件。

### 6.2 F4 周任务

新增 `XuanJiQuant-Strategy-Weekly`，周日 10:00 调用确定性研究调度器。策略到期日从周六改为周日，确保 Qlib 周任务先完成。

F4 运行前必须同时验证：

- 最新完整交易日因子任务成功；
- 因子 `data_version` 与本周日线快照一致；
- Qlib manifest 状态完整且覆盖到本周最新完整交易日；
- PIT 质量报告、行业版本和基准版本与 manifest 绑定；
- 不存在仍在运行的同类重任务。

前置条件失败时输出明确 reason code 并保持 `f4_blocked`；不得退回旧市场扫描或截面代理。

## 7. 计划任务定义

### 7.1 `XuanJiQuant-Research-Daily`

- 触发：周一至周五 16:20。
- 入口：`python scripts/run_daily_research_pipeline.py --workers 8`。
- 工作目录：项目根目录。
- 重叠策略：`IgnoreNew`。
- 最长运行：4 小时。
- 失败重试：每 15 分钟一次，最多 3 次。
- 离线补跑：`StartWhenAvailable=true`。

### 7.2 `XuanJiQuant-Qlib-Weekly`

- 触发：周六 18:30。
- 保持既有 Qlib 虚拟环境和权威数据根目录。
- 重叠策略：`IgnoreNew`。
- 失败必须保留非零结果和原因证据。

### 7.3 `XuanJiQuant-Strategy-Weekly`

- 触发：周日 10:00。
- 入口：`python scripts/research_training_scheduler.py --once`，由调度器只认领周日到期的策略任务。
- 工作目录：项目根目录。
- 重叠策略：`IgnoreNew`。
- 最长运行：4 小时。
- 失败重试：每 30 分钟一次，最多 2 次。
- 前置数据失败时保持失败关闭，不自动改用旧版本。

计划任务安装和更新必须由项目内 PowerShell 脚本声明，不能只依赖本机手工配置。

## 8. 恢复、重试与并发

`ResearchJobStore` 继续作为研究任务账本：

- 同一幂等键原子认领。
- 任务租约过期且 owner PID 消失时记为 `interrupted/owner_lost`。
- 活进程不会因心跳暂时较旧而被回收。
- 日常任务安全退避 15 分钟；策略重任务由外部计划任务按 30 分钟重启。
- 成功、达到最大重试次数和明确取消均为终态。
- 所有尝试保留 `claimed/interrupted/retried/succeeded/failed` 审计事件。

日常流水线继续使用文件锁避免同一入口重叠；Windows 任务使用 `IgnoreNew` 形成第二道防线。

## 9. 页面与 API 状态

页面必须分别展示：

- 数据截至日期、覆盖率、快照 ID、数据版本；
- 因子评估日期、可评估股票数、因子数、数据版本；
- 研究组合生成日期、组合 ID、来源 F4 状态和研究权限；
- F4 最近验证周、输入版本、门禁状态和阻断原因。

状态文案规则：

- 版本一致且门禁成功：展示当前结果。
- 上游正在运行：展示“更新中”和当前阶段，不沿用旧结果冒充当前。
- 上游失败：展示失败原因和最近一次历史成功日期。
- 周末或节假日无新交易数据：展示最近交易日，不标记过期。
- 历史结果只能标记为历史，不能作为当前权限或成功依据。

## 10. 测试与验收

必须新增或更新以下验证：

1. 纯调度测试：交易日 16:20 因子到期、周六 18:30 Qlib 到期、周日 10:00 策略到期，其他时间不误触发。
2. 日常流水线测试：严格执行数据门禁 → 因子门禁 → 研究组合生成顺序。
3. 失败关闭测试：数据失败不运行因子；因子失败不生成组合；Qlib 失败不运行 F4。
4. 幂等测试：同一版本重复启动只产生一个成功任务和一个版本化组合。
5. 恢复测试：死进程可回收，活进程不回收，退避期内不重试。
6. 组合契约测试：F4 拒绝时只能生成诊断研究组合且执行权恒为 false。
7. 计划任务契约：三个任务的时间、工作目录、重叠策略、超时和重试设置与本规格一致。
8. 实际接口验证：因子、组合和策略 API 返回当前版本，不出现日期或哈希错配。
9. 回归验证：相关 Python 测试、Node 契约、TypeScript、Vite 构建和页面验证通过。

## 11. 完成判定

只有同时满足以下条件才算完成：

- 三个 Windows 任务按本规格存在且可被项目脚本重建。
- 一个真实交易日完成数据、因子和研究组合的同版本闭环。
- 一个周末测试场景证明 Qlib 成功后才能运行 F4。
- `ResearchJobStore` 中不存在 owner PID 已消失却长期停留 `running` 的任务。
- 页面和 API 能区分当前、运行中、失败和历史状态。
- 研究组合与 F4 产物均无交易权限。
- README 和 `docs/XUANJI_HANDOFF.md` 记录模块关系、时间安排、失败处理和操作命令。

## 12. 回滚边界

若新调度出现异常，可停用新增的 `XuanJiQuant-Strategy-Weekly` 并恢复原周策略到期日；日常数据与因子链保持独立可运行。回滚不得删除研究账本、版本化组合、F4 证据或历史任务结果。
