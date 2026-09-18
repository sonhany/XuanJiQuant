# Qlib 本机研究与训练操作手册

更新日期：2026-08-04

## 1. 当前结论

第一阶段代码主链已实施：六年日频 A 股数据、版本化质量门禁、Alpha158/Alpha360、LightGBM/XGBoost/Linear 固定矩阵、官方 Qlib Workflow/Recorder、同信号双回测、统一晋升门禁、周/月/季固定调度、中文七页签和只读验收器。

当前不能表述为“Qlib 已 100% 投用”。只有真实六年数据、四项模型矩阵、双回测、无订单 shadow artifact 和最近同模式连续两次完整调度同时通过，且下列命令返回 0，第一阶段离线验收才完成：

```powershell
.\.venv-qlib\Scripts\python.exe scripts\qlib_acceptance.py
```

Qlib 是离线研究模块，不读取或写入 `data/quant.db`，不在盘中交易进程训练，不能绕过 verifier、risk gateway、熔断、模拟盘验证或人工授权。

2026-08-04 受控验收尝试：作业 `qlib_72c0134d96444bbc` 从 5211 只股票开始六年采集，但未完成首个新检查点；TdxQuant 套接字异常、Baostock 网络接收错误、AkShare/Eastmoney 连接失败，作业最终按事实登记为 `interrupted`，原有 1 组 raw/adjusted/mask 文件未被伪报为完整数据。恢复外部数据源后从断点重新提交 `collect_six_years`。

## 2. 活动路径与环境

| 项目 | 位置或版本 |
| --- | --- |
| 活动项目 | `C:\Users\HYSHEN\XuanJiQuant` |
| 默认 Qlib 数据根 | `C:\Users\HYSHEN\XuanJiQuant\data\qlib` |
| 隔离环境 | `C:\Users\HYSHEN\XuanJiQuant\.venv-qlib` |
| pyqlib | 0.9.7 |
| LightGBM | 4.6.0 |
| XGBoost | 2.1.4 |
| XuanJiQuant 控制索引 | `data\qlib\qlib_meta.db` |
| 官方 Recorder 元数据 | `data\qlib\mlflow.db` |
| 官方 Recorder 产物 | `data\qlib\mlruns` |

冻结或废弃路径：

- `C:\Users\HYSHEN\AlphaCouncil2-AI`：冻结备份，只供审计。
- `C:\XuanJiQuant-QlibData`、`C:\AlphaCouncil-QlibData`：废弃旧数据根，不得用于当前运行。

`QLIB_DATA_ROOT` 只用于临时恢复、只读挂载或专用存储；日常保持为空。路径模块会拒绝冻结和废弃根。`data/` 已被 Git 忽略，备份代码不能替代备份数据。

重新创建隔离环境：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_qlib_env.ps1
```

## 3. 架构和产物关系

```text
Web 七页签
  -> Node /api/qlib（token、白名单、30 秒请求边界）
  -> qlib_runner.py（状态、任务提交、人工 shadow 晋升）
  -> qlib_job_worker.py（后台固定任务、stage、heartbeat、run_token）
  -> qlib_train.py
       -> workflow_bridge.py（官方 Workflow）
       -> artifact_importer.py（Recorder 校验与控制索引导入）
       -> ashare_backtest.py（A 股交易规则）
       -> promotion_gate.py（统一 gate）
```

官方 Workflow 每个成功 Recorder 必须具有：

```text
params.pkl
pred.pkl
label.pkl
sig_analysis/ic.pkl
sig_analysis/ric.pkl
portfolio_analysis/report_normal_1day.pkl
portfolio_analysis/positions_normal_1day.pkl
portfolio_analysis/port_analysis_1day.pkl
```

`qlib_meta.db` 只保存身份、版本、哈希、指标、gate 和审计；真实产物由 Recorder 保存。导入同一 recorder 是幂等操作。任何缺项、路径穿越或哈希变化都失败关闭。

## 4. Web 使用

进入左侧“Qlib 实验”，七页签含义如下：

1. 研究总览：活动数据根、override、真实能力目录、周/月/季连续成功数。
2. 数据准备：数据版本、最新交易日、质量 gate 版本、失败原因、采集与导出。
3. 模型训练：只提供周度 baseline、月度 walk-forward、季度固定矩阵，不接受任意模型 YAML。
4. 实验记录：本地 ID、Qlib Experiment ID、Recorder ID、handler/model/seed/config hash 和产物完整性。
5. 模型仓库：统一 gate；只有 candidate 可以由人工触发 shadow 复核。
6. 回测评估：Qlib 官方回测与 A 股规则回测按同一 Signal Hash 并排展示。
7. 任务日志：中文任务状态、stage、heartbeat、interrupted/failed 和最近输出。

“可用”不是根据代码文件存在推断：数据必须有通过的质量报告，Workflow 必须有成功且产物完整的 Recorder。深度学习、Meta、RL 和高频在第一阶段固定显示“未接入”。

## 5. 安全 CLI

控制动作通过 Node API 的授权边界，不在命令行打印 token：

```powershell
$headers = @{ 'X-XuanJi-Token' = $env:XUANJI_API_TOKEN }

# 只读状态
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8880/api/qlib' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{ action = 'status' } | ConvertTo-Json -Compress)

# 补齐六年数据（后台任务）
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8880/api/qlib' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{ action = 'collect_six_years' } | ConvertTo-Json -Compress)

# 质量、导出、固定 Workflow 和回测同样只替换 action
# quality_six_years / export_six_years / workflow_baseline
# workflow_monthly_walk_forward / workflow_quarterly_matrix / backtest_ashare
```

直接调度入口只有固定模式，没有任意命令参数：

```powershell
.\.venv-qlib\Scripts\python.exe scripts\qlib_schedule.py --mode weekly --force
.\.venv-qlib\Scripts\python.exe scripts\qlib_schedule.py --mode monthly --force
.\.venv-qlib\Scripts\python.exe scripts\qlib_schedule.py --mode quarterly --force
```

季度矩阵固定串行，禁止并行启动多个模型抢占内存。同一时间只允许一个重型 Qlib job。

## 6. 固定周/月/季主链

```text
weekly:
  collect_six_years -> quality_six_years -> export_six_years
  -> workflow_baseline -> backtest_ashare

monthly:
  collect_six_years -> quality_six_years -> export_six_years
  -> workflow_monthly_walk_forward -> backtest_ashare

quarterly:
  collect_six_years -> quality_six_years -> export_six_years
  -> workflow_quarterly_matrix -> 每个 workflow 的 backtest_ashare
```

没有新交易日返回 `succeeded + no_op`，不增加连续成功；质量、Recorder、双回测或 gate 任一不完整即记失败；季度部分成功记 `partial_failed`。调度器从不自动晋升超过 candidate。

计划任务：`XuanJiQuant-Qlib-Weekly`，每周六 18:30。重装：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_qlib_schedule.ps1
```

## 7. 状态与晋升语义

```text
research
  -> candidate       统一 gate 通过，仍只是候选
  -> rejected        硬条件失败
  -> review_required 双回测差异等需要人工判断

candidate --人工重验 model/params/pred/gate 哈希--> shadow
shadow 输出只有版本化预测，不含订单
```

shadow 仍不是模拟盘或实盘。后续进入 paper 必须经过现有策略评估、执行验证和硬风控；本阶段不授权 live。

## 8. 恢复和常见失败

恢复前：

1. 停止活动 Qlib worker。
2. 禁用 `XuanJiQuant-Qlib-Weekly`。
3. 同时备份 `data\qlib` 文件树、`qlib_meta.db`、`mlflow.db` 和 `mlruns`。
4. 核对文件数、总字节数与数据库哈希后再切换。
5. 不手工合并两套数据根；整库恢复并保留原副本。

常见原因码：

| 原因码 | 含义与处理 |
| --- | --- |
| `six_year_quality_failed` | 六年质量门禁失败；查看质量报告，不得继续训练 |
| `recorder_artifacts_incomplete` | Recorder 八项产物不全；保留失败 run，重新运行固定 Workflow |
| `dual_backtest_missing` | 缺少官方或 A 股规则回测 |
| `dual_backtest_signal_mismatch` | 两回测不是同一信号；禁止比较和晋升 |
| `unified_gate_missing_or_stale` | gate 缺失或版本不一致 |
| `schedule_successes_below_2` | 最近同 mode 的完整成功不足两次 |
| `shadow_signal_contains_orders` | shadow artifact 出现订单字段；立即失败关闭 |
| `inactive_or_unsafe_data_root` | 使用了冻结或废弃路径 |

任务进程意外退出会登记 `interrupted`；恢复器保留原结果和 run token，不把中断伪装成成功。

## 9. 验证

只读验收：

```powershell
.\.venv-qlib\Scripts\python.exe scripts\qlib_acceptance.py
```

完整通过必须显示：

```text
passed: true
gate_version: qlib_phase1_gate_v1
handlers: Alpha158, Alpha360
models: LightGBM, XGBoost, Linear
record_types: SignalRecord, SigAnaRecord, PortAnaRecord
backtests: qlib_official, xuanji_ashare
schedule_consecutive_successes: 2 或更多
```

定向回归命令见实施计划 `docs/superpowers/plans/2026-08-04-qlib-official-workflow-bridge.md`。项目交付还必须运行 Python 全量测试、四组 Node Qlib 契约、TypeScript、Vite build 和 Web 验证。

## 10. 与日常因子流水线的边界（2026-08-14）

六年 Qlib PIT 数据集和 SQLite 日常因子快照是两个独立的数据产品：

- 日常因子任务读取 `data:snapshot:a_share_daily:latest_passed`；每日 16:20 由 `XuanJiQuant-Research-Daily` 调用 `scripts/run_daily_research_pipeline.py`，先补齐预期交易日并通过快照门禁，再触发确定性研究。
- Qlib 周/月/季任务读取 `data/qlib/datasets/a_share_6y_daily/manifest.json`，必须通过独立的六年 PIT 质量门禁。
- Qlib manifest 为 `incomplete` 时，只阻断 `qlib_*` 作业；不得再把日常因子任务错误标记为 `data_sync_incomplete`。
- 两类产物都固定为 `research_only` 且 `execution_authority=false`，不能自动晋升模拟或生产。

## 10. 第二阶段范围

第一阶段稳定且连续验收后，才评估深度学习、Meta、RL、高频与 RD-Agent。第二阶段也必须复用同一数据版本、Recorder、双回测、统一 gate、shadow/paper 和硬风控边界，不得建立旁路。

## 11. 确定性训练日程与研究产物门禁

唯一活动数据根目录为 `C:\Users\HYSHEN\XuanJiQuant\data\qlib`。废弃的 `C:\XuanJiQuant-QlibData`、`C:\AlphaCouncil-QlibData` 以及冻结备份路径都不能作为运行根目录。

固定日程如下：

- 交易日 16:20：因子工厂训练，结果最高为 `shadow`。
- 周日 10:00：`XuanJiQuant-Strategy-Weekly` 运行 F4 策略与组合验证，只消费同版本因子和本周六已通过的 Qlib/PIT 证据，结果保持 `research_only`。
- 周六 18:30：Qlib 自适应周期；季度优先于月度，月度优先于周度，同一窗口只运行一个周期。

守护进程由项目启动器托管：

```powershell
python scripts/run_daily_research_pipeline.py --workers 8
```

该命令只在全市场日线快照达到预期完整交易日并通过质量门禁后，执行当前已到期且满足前置条件的任务；稳定幂等键阻止同一窗口重复运行。错过当日窗口的因子任务会在下一周期追补，不接受外部动态提交的日期或模式。Qlib 内部仍由 `scripts/qlib_schedule.py` 和 `quant/qlib/jobs.py` 记录重任务；检测到活动重任务时返回 `heavy_job_active`，不得并发启动第二条主链。

路径治理先预演，再在确认 Qlib worker、活动重任务和周计划任务均停止后执行：

```powershell
python scripts/qlib_path_migration.py
python scripts/qlib_path_migration.py --apply
```

执行模式会先备份 `qlib_meta.db`、记录备份 SHA-256，再在单个事务中映射确实存在的活动路径或标记缺失引用失效；历史 traceback 和普通审计文本不做机械替换。迁移后扫描必须为零活动废弃路径。

合格 Qlib/影子因子进入研究候选集时必须同时满足：数据版本与质量报告一致且不超过 7 天、六年生命周期覆盖门禁通过、Workflow 成功、Recorder 八项产物及哈希完整、官方与 A 股规则回测使用同一信号、统一 gate 通过、影子信号明确 `execution_authority=false` 和 `can_trigger_order=false`。研究证据只能进入人工评审的候选/影子域，不能扩大股票池、签发订单、修改硬风控或自动晋升生产。
