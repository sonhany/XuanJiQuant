# XuanJiQuant Qlib 官方工作流桥接设计

日期：2026-08-04  
状态：已完成方案评审，等待书面规范复核  
目标阶段：成熟日频 A 股研究与影子验证主链  

## 1. 背景与结论

XuanJiQuant 已经具备独立 Qlib 环境、A 股日线采集、Qlib bin 导出、`DatasetH`、`Alpha158`、LightGBM、自定义横截面评估、任务注册、定时调度和中文研究面板。现有实现不是演示壳，但模型训练、实验记录和组合回测仍主要由项目自定义代码完成，没有完整使用 Qlib 官方 Workflow、Recorder 和 Record 体系。

本轮采用“官方工作流桥接”方案：保留现有数据采集、任务控制、安全白名单、元数据索引、中文 UI 和交易晋升边界，在研究计算层接入 Qlib 官方实验主链，并将官方产物以受控方式登记回 XuanJiQuant。这样既能提高对 Qlib 的利用率和实验可复现性，也不破坏已经稳定运行的系统边界。

项目当前阶段定义为六级成熟度中的第 3 级：离线研究工程初期。第一阶段完成后应达到第 4 级：可重复、可审计、可比较、可进入影子验证的成熟研究平台。它仍不是实盘自动交易系统，任何研究结果都不得直接生成模拟盘或实盘订单。

## 2. 设计原则

1. **主动项目唯一**：所有新增代码、任务、日志和数据只使用 `C:\Users\HYSHEN\XuanJiQuant`。Qlib 活动根目录只能是 `C:\Users\HYSHEN\XuanJiQuant\data\qlib`。
2. **冻结备份不可操作**：`C:\Users\HYSHEN\AlphaCouncil2-AI` 仅作为冻结审计备份，不启动、不测试、不写入。
3. **历史事实不可改写**：历史数据库、日志、异常堆栈中出现的旧路径和旧项目名作为审计事实保留。活动读取时通过路径解析器映射，不对历史记录做机械替换。
4. **官方能力与本地控制分层**：Qlib 负责数据集、模型、实验记录、信号分析和标准组合回测；XuanJiQuant 负责任务授权、A 股业务规则、晋升门槛、影子信号、模拟执行和硬风控。
5. **失败关闭**：数据质量、实验完整性或任一回测门槛不通过时，模型只能被拒绝或保留为研究产物，不得晋升。
6. **固定流水线优先**：UI 只调用经过白名单约束的固定动作，不能接收任意 Python、YAML 路径或 shell 命令。
7. **可复现优先于模型复杂度**：第一阶段只使用 LightGBM、XGBoost 和线性模型；深度学习、Meta、RL 和高频能力在主链稳定后进入第二阶段。

## 3. 范围

### 3.1 第一阶段包含

- 修复活动路径解析和数据版本登记，不修改历史审计字段。
- 近六年 A 股日频数据的有界分批采集、断点续跑、失败分类和质量门禁。
- `Alpha158` 与 `Alpha360` 两套特征处理器。
- LightGBM、XGBoost、线性模型三类可重复实验。
- Qlib Workflow/Recorder，以及 `SignalRecord`、`SigAnaRecord`、`PortAnaRecord`。
- Qlib 官方 `TopkDropoutStrategy` 组合回测。
- XuanJiQuant A 股约束回测，与官方回测构成双重验证。
- 多窗口 walk-forward、实验比较、候选/拒绝/影子信号晋升。
- 周、月、季固定调度与失败可恢复能力。
- Qlib 研究面板的真实能力状态、数据质量、实验产物和双回测展示。
- README、交接文档和中文操作手册更新。

### 3.2 第一阶段不包含

- LSTM、GRU、Transformer、Localformer、HIST 等深度模型正式接入。
- Qlib Meta Controller、RL Order Execution、分钟级/高频数据与嵌套执行。
- RD-Agent 自动生成或自动修改策略代码。
- 研究模型直接接管模拟盘或实盘下单。
- 绕过 verifier、risk gateway、熔断规则或人工批准。
- 为了“全支持”而一次性暴露 Qlib 所有实验性模块。

上述能力归入第二阶段独立设计，前提是第一阶段连续稳定运行并通过本设计的验收门槛。

## 4. 总体架构

```text
TdxQuant / 既有兜底源
        |
        v
XuanJiQuant 数据采集与标准化
  - 未复权日线
  - 复权/点时可见性
  - 失败分类与检查点
        |
        v
数据质量门禁 ----失败----> 阻断导出/训练/晋升
        |
        v
Qlib bin + 数据版本指纹
        |
        v
Qlib DatasetH
  - Alpha158
  - Alpha360
        |
        v
Qlib Workflow / Recorder
  - LightGBM
  - XGBoost
  - Linear
        |
        +--> SignalRecord
        +--> SigAnaRecord
        +--> PortAnaRecord + TopkDropoutStrategy
        |
        v
XuanJiQuant 实验导入器
  - qlib_meta.db 控制索引
  - 产物哈希与路径
  - 官方指标标准化
        |
        +--> Qlib 官方回测门禁
        +--> A 股规则回测门禁
                    |
                    v
        rejected / candidate / shadow_signal
                    |
                    v
现有策略评估 -> paper trading -> verifier -> risk gateway
```

Qlib 的 MLflow/Recorder 存储是实验事实来源；`qlib_meta.db` 是 XuanJiQuant 的控制索引和审计入口。两者不能互相替代，也不能出现双向无约束写入。

## 5. 组件边界与接口

### 5.1 活动路径解析器

职责：统一解析项目根、Qlib 数据根、数据集目录、Qlib bin、模型、报告、任务和 Recorder 存储位置。

规则：

- 默认从当前项目根推导 `data\qlib`。
- `QLIB_DATA_ROOT` 只允许作为显式的临时恢复或专用存储覆盖；状态 API 必须显示覆盖是否生效。
- 活动读写拒绝指向 `C:\XuanJiQuant-QlibData`、`C:\AlphaCouncil-QlibData` 或冻结备份目录。
- 历史记录保留 `recorded_path`，运行时另行生成 `resolved_path`、`path_state` 和 `resolution_reason`。
- `path_state` 固定为 `active`、`mapped_legacy`、`missing_historical`、`rejected_frozen` 四类。

该组件只解决“当前应该读哪里”，不修改过去“当时写了哪里”。

### 5.2 数据采集与检查点

近六年采集使用有界批次，每批标的数由固定配置控制，并在每批结束后原子更新检查点。单个标的失败不回滚已完成标的，但任务最终状态必须反映部分失败。

失败原因标准化为：

- `missing_columns`：上游字段不满足日线契约。
- `empty_window`：请求窗口无有效记录。
- `source_network`：连接、超时或上游服务错误。
- `price_jump`：价格连续性或复权校验异常。
- `calendar_mismatch`：日期不在交易日历或数据缺口异常。
- `write_failure`：检查点、数据文件或元数据写入失败。
- `unknown`：未归类异常，必须保存脱敏后的错误摘要。

重试策略：网络类错误可指数退避重试；字段缺失和价格异常不能盲目重试，必须先由来源适配器或质量规则处理。达到重试上限后进入失败清单，下次任务只重跑失败集合和新增交易日，不重写全部标的。

### 5.3 数据质量门禁

质量报告必须绑定唯一 `dataset_version`，至少包含：

- 请求、成功、失败和无数据标的数。
- 起止交易日、最新交易日和相对当前交易日的新鲜度。
- 行数、字段完整率、标的覆盖率和交易日覆盖率。
- 重复行、非单调日期、异常价格、异常成交量、复权不连续数量。
- 失败原因聚合与逐标的失败明细路径。
- 原始数据、调整数据、点时掩码和 Qlib bin 的指纹。

训练前硬门槛：质量报告存在且状态为 `passed`；使用的数据版本与质量报告一致；最新日期满足调度允许的新鲜度；必要字段完整；无未解释的全市场系统性缺口。两只无有效行情的新股、退市股或特殊标的可以作为明确例外，但必须被记录，不能用伪造数据补齐。

质量门槛值集中配置并带版本号，不能散落在脚本和 UI 中。修改门槛属于受审计配置变更，不随单次训练参数隐式改变。

第一阶段沿用已经实现的 `qlib_phase1_gate_v1` 数据硬门槛，避免在桥接过程中暗改研究口径：

| 指标 | 门槛 |
|---|---|
| 全窗口标的覆盖率 | 不低于 98% |
| 最近窗口标的覆盖率 | 不低于 99% |
| 交易日数量 | 不少于 1200 |
| 最新日期 | 与任务数据截止日对应的最新交易日一致 |
| 重复行 | 0 |
| 非法 OHLC | 0 |
| 非正复权因子 | 0 |
| 训练集中未知 ST 状态样本 | 0 |
| 生命周期外样本 | 0 |

覆盖率门槛允许明确记录的无行情、未上市和已退市例外，但例外不能从分母中静默删除。任何门槛调整必须产生新版本，旧实验继续引用原门槛版本。

### 5.4 Qlib 数据集配置

官方工作流配置采用受控模板生成，不允许 UI 上传任意配置。每个实验明确记录：

- `dataset_version` 与 Qlib bin 路径。
- 训练、验证、测试区间。
- 处理器名称和参数：`Alpha158` 或 `Alpha360`。
- 标签定义、股票池和过滤规则。
- 模型类别、超参数、随机种子和依赖版本。
- 回测基准、交易成本和策略参数。
- 配置文件内容哈希。

时间切分必须避免未来数据泄漏。标签、特征、复权和点时可见性按照交易日切片；验证集和测试集不得参与模型拟合或超参数选择。

### 5.5 官方 Workflow 与 Recorder 桥

桥接层负责：

1. 从受控模板构造 Qlib experiment。
2. 在独立 Qlib 环境中启动 Workflow。
3. 训练模型并保存模型产物。
4. 生成 `SignalRecord`、`SigAnaRecord` 和 `PortAnaRecord`。
5. 读取 Recorder 的实验 ID、指标、参数和 artifact 清单。
6. 校验必需产物并计算哈希。
7. 将只读摘要登记到 `qlib_meta.db`。

完成条件不是“进程退出码为 0”，而是 Recorder 状态成功、三类 Record 全部存在、关键指标可解析、模型与预测产物哈希可计算。缺少任一必需产物时，实验记为 `incomplete`，不得晋升。

### 5.6 模型矩阵

第一阶段固定支持以下矩阵：

| 处理器 | 模型 | 用途 |
|---|---|---|
| Alpha158 | LightGBM | 主基线与默认候选 |
| Alpha360 | LightGBM | 更高维价格量特征对照 |
| Alpha158 | XGBoost | 树模型交叉验证 |
| Alpha158 | Linear | 低复杂度抗过拟合基线 |

XGBoost 只有在独立环境依赖已明确锁定且测试通过后才标记可用；依赖未安装时必须显示 `unavailable`，不能显示 `ready`。模型矩阵可通过后续受控版本扩展，但第一阶段不加入深度学习。

### 5.7 双回测

官方回测使用 Qlib `TopkDropoutStrategy` 和 `PortAnaRecord`，用于获得与 Qlib 生态一致的组合分析、基准比较、收益、风险、换手和成本指标。

本地 A 股约束回测使用 XuanJiQuant 既有回测边界，至少覆盖：

- 手续费与卖出印花税。
- 涨跌停与停牌不可成交。
- T+1 卖出约束。
- 成交量/成交额容量限制和滑点。
- 可交易股票池和风险过滤。
- 调仓失败、部分成交及现金约束。

两套回测使用同一个版本化信号、同一测试区间和可追溯成本配置。结果分别展示，不将两套口径混成一个指标。任一硬门槛失败，模型不得晋升；差异超出配置容差时标记 `backtest_divergence`，要求人工检查交易规则和数据对齐。

### 5.8 实验控制索引

`qlib_meta.db` 为每次实验保存控制元数据：

- 本地实验 ID、Qlib experiment/recorder ID。
- 数据版本、质量报告 ID、配置哈希。
- 特征处理器、模型、训练窗口和随机种子。
- 任务 ID、开始/结束时间、状态和失败阶段。
- Recorder artifact 根、必需 artifact 清单与哈希。
- 官方指标、本地回测指标、门禁结果和晋升状态。
- `recorded_path` 与 `resolved_path` 的分离字段。

Recorder 保留完整实验内容，本地数据库只保存查询和控制所需摘要。重新导入同一 Recorder 必须幂等，不创建重复实验。

### 5.9 晋升与影子信号

状态机固定为：

```text
official_demo_smoke
        |
        v
research_completed
   |              |
   | 门禁失败      | 全部门禁通过
   v              v
rejected       candidate
                  |
                  | 人工确认 + 版本锁定
                  v
             shadow_signal
```

`shadow_signal` 只包含版本化预测、目标日期、标的、分数/排序、模型版本、数据版本和生成时间，不包含订单。进入现有策略与模拟盘链路后，仍必须经过策略许可、paper trading、verifier、risk gateway 和熔断规则。

AI 可以解释实验和提供比较建议，但不能修改门禁结果、自动晋升模型或绕过人工确认。

第一阶段候选晋升沿用 `qlib_phase1_gate_v1`，不得因为改用官方 Recorder 而放宽：

- 至少 4 个完整测试窗口。
- 测试窗口 Rank IC 中位数不低于 0.02。
- 测试窗口 ICIR 中位数不低于 0.30。
- 至少 70% 测试窗口 Rank IC 为正。
- 聚合费用后多空收益为正。
- 聚合 Sharpe 不低于 0.80。
- 最大回撤不低于 -20%。
- 最差窗口 Rank IC 不低于 -0.03。
- 数据质量门禁通过。
- 官方 Qlib 回测与 A 股约束回测各自的费用后收益为正、Sharpe 不低于 0.80、最大回撤不低于 -20%。

双回测差异审查采用版本化默认容差：费用后年化收益绝对差超过 5 个百分点、最大回撤绝对差超过 5 个百分点，或年化换手率相对差超过 25% 时，标记 `backtest_divergence` 并阻断自动进入 `candidate`，直至人工完成差异说明。人工只能解除差异审查，不能把未达到上述硬指标的实验改为 `candidate`。

## 6. 任务与调度

保留现有 `qlib_runner.py` 白名单控制面，新增或调整的动作仍必须是固定动作、固定参数结构和独立进程。UI 不获得任意命令执行能力。

调度目标：

- **每周**：补齐最新日频数据、生成质量报告、刷新 Qlib bin、运行主基线；若本周没有新交易日则生成明确的 no-op 结果。
- **每月**：运行多窗口 walk-forward 和主模型稳定性比较。
- **每季度**：运行完整模型矩阵与 Alpha158/Alpha360 对照，生成阶段性研究报告。

同一数据集和动作只允许一个活动任务。进程被外部终止、机器重启或退出码异常时，任务状态必须记为 `interrupted` 或 `failed`，不能长期停留在 `running`。下次启动先执行陈旧任务回收，再从最近有效检查点继续。

连续两次计划任务成功，是第一阶段投用验收条件之一。成功的定义包括数据质量、工作流、产物登记和报告生成全部完成，不仅是脚本返回成功。

## 7. UI 与 API

Qlib 研究面板保留现有七个页签和中文交互，新增信息优先复用现有布局，不进行无关 UI 重构。

### 7.1 能力目录

每项能力必须从真实依赖、配置、数据和最近验证结果计算状态：

- `可用`：依赖存在且最近的代表性验证通过。
- `受限`：功能存在，但数据、依赖或门禁不足。
- `运行中`：存在可验证的活动任务。
- `失败`：最近代表性运行失败。
- `未接入`：尚无实现。

不得因为代码中存在类名或 action 就显示“已就绪”。深度模型、Meta、RL、高频在第一阶段明确显示“未接入/第二阶段”。

### 7.2 数据状态

显示活动数据根、是否存在环境覆盖、数据版本、最新交易日、距当前交易日的新鲜度、覆盖率、质量门禁、失败原因和失败标的数量。历史旧路径只在审计详情中显示，并标注“历史记录，不是活动路径”。

### 7.3 实验详情

显示本地实验 ID、Recorder ID、模型、处理器、数据版本、训练/验证/测试窗口、配置哈希、运行时长、随机种子、依赖版本和产物完整性。

### 7.4 评估与晋升

官方 Qlib 回测和 A 股规则回测并排展示；每个晋升门槛显示通过/失败、实测值、阈值版本和原因。只有满足后端门禁时，人工确认按钮才可用。前端禁用不构成安全控制，后端必须重复验证。

### 7.5 运行控制

提供“数据补齐”“质量检查”“导出 Qlib”“运行基线”“运行月度 walk-forward”“运行季度比较”等固定入口。每次操作显示预计范围、当前任务和结果摘要，不显示或接受任意命令文本。

## 8. 错误处理与可观测性

每个任务生成结构化事件，至少包含 `job_id`、`stage`、`dataset_version`、`experiment_id`、时间、进度、错误分类和可读中文摘要。敏感配置、令牌和完整环境变量不得进入日志。

阶段固定为：

```text
collect -> quality -> export -> dataset -> train
        -> signal_record -> signal_analysis -> portfolio_analysis
        -> local_backtest -> register -> gate -> report
```

失败记录第一个失败阶段，同时保留此前已成功阶段的产物。恢复时只复用通过哈希校验且与当前配置一致的产物；配置、数据版本或代码版本不一致时重新执行相关阶段。

状态 API 必须区分：活动任务、已完成任务、失败任务、被中断任务和陈旧任务。进程 PID 只作为辅助证据，必须同时检查启动标识和任务心跳，避免 PID 重用造成误判。

## 9. 测试策略

### 9.1 单元测试

- 活动/历史/冻结路径解析与拒绝规则。
- 数据失败分类、重试决策和检查点幂等。
- 质量指标与门禁判定。
- Workflow 配置模板和配置哈希。
- Recorder 产物完整性校验与幂等导入。
- 双回测指标标准化和差异判定。
- 模型晋升状态机与后端授权。

### 9.2 契约测试

- Node `/api/qlib` action 白名单与中文错误响应。
- Python runner 按行 JSON 协议、超时、异常退出和陈旧任务回收。
- UI 能力状态不再把未验证能力显示为“可用”。
- 前后端数据版本、Recorder ID、双回测和门禁字段一致。

### 9.3 集成测试

- 使用小型确定性数据完成一次 Alpha158 + LightGBM 官方 Workflow。
- 验证三类 Record、模型、预测、指标和组合分析产物。
- 将 Recorder 摘要导入本地索引两次，确认幂等。
- 对同一信号运行官方回测与 A 股约束回测。
- 验证质量失败会阻断训练，回测失败会阻断晋升。
- 验证任务中断后状态正确并可从检查点恢复。

### 9.4 回归与运行验证

保持现有 Python、Node 契约、TypeScript、Vite、Web/UI 验证和 Python 冒烟测试。Qlib 使用独立 `.venv-qlib`，避免改变主服务依赖。大规模采集和完整训练不放入普通提交级测试，而由受控离线验收任务执行。

## 10. 投用顺序

1. 路径解析、元数据扩展和真实能力状态。
2. 六年数据失败修复、断点续跑与质量门禁。
3. 官方 Workflow/Recorder 桥和 Alpha158 基线。
4. 三类 Record 与官方 TopkDropout 回测。
5. A 股约束回测对接和双门禁。
6. Alpha360、XGBoost、Linear 和 walk-forward 矩阵。
7. 调度恢复、连续运行验证、UI/API 完整展示。
8. README、交接文档和中文操作手册定稿。

每一步都必须保持已有服务可运行；数据库变更采用向前兼容迁移。新字段或表上线后，旧实验仍可查询，但缺失的新字段显示为“历史实验未记录”，不能伪造默认成功值。

## 11. 验收标准

第一阶段只有同时满足以下条件才算完成：

1. 活动 Qlib 根唯一且正确，旧路径只作为历史审计信息出现。
2. 近六年数据完成有界、可恢复采集；质量报告存在并通过配置化门禁。
3. Alpha158 与 Alpha360 均能在活动数据上构建可重复数据集。
4. LightGBM、XGBoost、Linear 三类模型均至少有一次可复现实验；不可用依赖会被真实标记，不虚报。
5. 每次正式实验都具有 Qlib experiment/recorder ID、模型产物、预测、`SignalRecord`、`SigAnaRecord` 和 `PortAnaRecord`。
6. 官方 TopkDropout 回测和 XuanJiQuant A 股规则回测使用同一信号版本完成，指标分别可查。
7. 数据、实验完整性和双回测任一门禁失败都会在后端阻断晋升。
8. 影子产物只生成版本化信号，不生成订单，也不能绕过现有策略许可、模拟盘和硬风控。
9. 周期任务发生异常中断后能被正确标记并恢复；至少连续两次计划任务完整成功。
10. Qlib 面板用中文准确显示数据新鲜度、失败原因、真实能力状态、实验配置、Recorder ID、双回测和晋升门槛。
11. 现有 Python、Node、TypeScript、Vite、Web/UI 与安全回归保持通过。
12. `README.md`、`docs/XUANJI_HANDOFF.md` 和 `docs/QLIB_LOCAL_TRAINING.md` 清楚说明模块关系、运行边界、操作命令、故障恢复和第二阶段范围。

## 12. 第二阶段进入条件与方向

第一阶段通过验收并连续稳定运行后，第二阶段才单独立项。候选方向依次为：

1. LSTM/GRU 作为深度时序基线。
2. Transformer/Localformer/HIST 等模型的受控对照。
3. Qlib Meta Learning 的滚动任务选择或参数适配实验。
4. 分钟数据、高频研究和嵌套执行。
5. RL 订单执行，仅在高质量成交数据和模拟执行评估成熟后研究。
6. RD-Agent 等自动研究工具，只允许生成隔离实验建议，不自动修改生产代码或晋升策略。

第二阶段沿用本设计的数据版本、Recorder、双回测、晋升和审计边界，不另建绕过主链的实验系统。

## 13. 官方依据

- Qlib 主仓库与总体说明：<https://github.com/microsoft/qlib>
- Qlib v0.9.7：<https://github.com/microsoft/qlib/releases/tag/v0.9.7>
- Workflow：<https://github.com/microsoft/qlib/blob/main/docs/component/workflow.rst>
- Recorder：<https://github.com/microsoft/qlib/blob/main/docs/component/recorder.rst>
- Strategy：<https://github.com/microsoft/qlib/blob/main/docs/component/strategy.rst>
- Online serving：<https://github.com/microsoft/qlib/blob/main/docs/component/online.rst>
- 官方 LightGBM + Alpha158 工作流示例：<https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml>

这些官方能力是第一阶段的实现依据，但 XuanJiQuant 的 A 股交易规则、任务安全和模型晋升边界仍由本项目控制。
