# Qlib、F4 与 F5 责任解耦设计

**日期：** 2026-08-30  
**状态：** 已实施并通过全量验收  
**活动工作区：** `C:\Users\HYSHEN\XuanJiQuant`  
**替代范围：** 本规格替代 `2026-08-18-research-layer-scheduling-design.md` 中“Qlib 周任务失败即禁止整个 F4”的前置关系；不替代 F4 v2 候选、走样本外、成本、组合门禁和 F5 账本规格。

## 1. 已确认的五条架构原则

1. Qlib 周任务独立负责数据导出、模型研究、Recorder、独立回测和 Qlib 自身门禁。
2. F4 独立负责统一候选比较、走样本外验证、组合成本和绩效门禁。
3. Qlib 候选只是 F4 六个候选族之一，不是 F4 系统总开关。
4. F4 公共数据只要求六年 PIT、历史行业、基准和质量报告完整，不要求 Qlib 独立周任务先成功。
5. F5 只消费已发布、身份完整的 F4/研究组合，不直接依赖 Qlib 任务、模型、Recorder 或门禁结果。

## 2. 问题定性

当前 `research_training_scheduler.py::_block_reason()` 在 `strategy_weekly` 分支中同时要求：

- 每日完整因子 generation 与策略目标日、数据版本一致；
- Qlib manifest 完整且覆盖同一市场日；
- 同一周 Qlib 调度任务成功；
- Qlib 调度任务输出版本等于当前 manifest。

后两项把独立的 Qlib 周期变成整个 F4 的总开关。该关系与 F4 v2 既有候选隔离契约矛盾：`f4_real_pipeline.py` 已把单个 Qlib 模型失败转换为 `CandidateUnavailable`，只要其他候选仍可用，单个 Qlib 候选不可用不应阻断整个工厂。

正确区分如下：

- **公共数据不可用：** F4 无法证明 PIT、行业、基准或质量，属于 `f4_blocked`。
- **Qlib 候选不可用：** 只将 Q1–Q4 中对应候选记为 `candidate_unavailable`。
- **Qlib 独立周任务失败：** 只影响 Qlib 自身状态、报告和下一周期恢复；不能自动改变 F4、F5 或账户状态。
- **F4 绩效未通过：** 来自实际窗口胜者的样本外组合结果，属于 `f4_rejected_exhausted`，不是 Qlib 基础设施故障。

## 3. 目标与非目标

### 3.1 目标

- 删除策略周任务对 Qlib 周任务账本成功状态的硬依赖。
- 以独立、可验证的公共数据证据作为 F4 启动门禁。
- 保留 Q1–Q4 的窗口级 Qlib 训练、Recorder、模型和预测验证。
- Qlib 候选不可用时继续运行 M/R/D/L/E 候选，并完整记录族级诊断。
- 保持 F4 原有 walk-forward、winner lock、成本压力和绩效阈值不变。
- 明确 F5 只能读取 F4/研究组合发布契约，禁止读取 Qlib 调度账本或模型状态决定执行许可。
- 页面分别显示 Qlib 研究状态、F4 公共数据状态、候选族状态和 F5 准入状态。

### 3.2 非目标

- 不删除 Qlib 候选族，不减少 24 个预登记候选。
- 不把 Qlib 候选失败静默替换成规则候选并沿用同一身份。
- 不降低 F4 数据、未来数据、组合、成本或绩效门槛。
- 不把 `candidate_unavailable`、Qlib workflow 成功或 F4 工厂完成称为策略通过。
- 不扩大 F5 模拟权限，不连接实盘，不恢复 Agent 或任意下单入口。
- 不修改活动 F4 历史结果，不覆盖旧 Qlib/F4 任务账本。
- 不因本规格中断当前正在运行且仍有新鲜心跳的 Qlib 恢复任务。

## 4. 目标架构

```text
                         ┌──────────────────────────────┐
                         │ Qlib 独立周任务              │
                         │ 数据导出 / Recorder / 模型   │
                         │ 独立回测 / Qlib 自身门禁     │
                         └──────────────┬───────────────┘
                                        │ 独立状态与研究产物
                                        │ 不授予 F4/F5 权限
                                        ▼
六年 PIT + 历史行业 + 基准 + 质量报告 ───────────────┐
                                                     │
                                                     ▼
                                           ┌─────────────────┐
                                           │ F4 公共数据门禁  │
                                           └────────┬────────┘
                                                    │
                     ┌──────────────────────────────┴─────────────────┐
                     │                                                │
                     ▼                                                ▼
          M/R/D/L/E 规则与组合候选                         Q1-Q4 Qlib 候选
          始终按公共数据独立运行                            按窗口训练；失败只隔离候选
                     │                                                │
                     └──────────────────────────────┬─────────────────┘
                                                    ▼
                               validation 比较 -> winner lock -> test
                                                    ▼
                              组合成本 / 约束 / 样本外绩效 / F4 门禁
                                                    ▼
                               原子发布 F4 generation 与研究组合
                                                    ▼
                                  F5 身份与模拟准入 -> F5 账本
```

## 5. 数据与接口契约

### 5.1 F4 公共数据证据

F4 启动前必须直接验证以下产物，而不是推断 Qlib 周任务是否成功：

1. `data/qlib/datasets/a_share_6y_daily/manifest.json`
   - `status=complete`；
   - `dataset_version` 非空；
   - `completed_symbols` 非空；
   - 目标市场日与质量报告一致。
2. `quality_report.json`
   - `passed=true`；
   - 数据版本、manifest 哈希和完成股票清单绑定一致；
   - 覆盖率、最近覆盖率、交易日数、重复、OHLC、复权因子、ST 与生命周期门禁通过。
3. 历史行业参考
   - 状态通过；
   - 研究权限固定；
   - 数据版本与 manifest 一致；
   - 产物哈希可验证。
4. 沪深 300 基准参考
   - 状态通过；
   - 数据版本与 manifest 一致；
   - 覆盖目标 PIT 日历；
   - 产物哈希可验证。

上述四类证据是公共研究输入。它们可以由 Qlib 数据采集组件产生或维护，但其可用性由产物自身证明，不由 `qlib_weekly` 任务状态代替。

### 5.2 Qlib 独立周任务契约

`XuanJiQuant-Qlib-Weekly` 保留独立 lane、幂等键、重任务互斥和恢复逻辑。成功、失败、阻断和中断只写 Qlib/研究任务账本及 Qlib 研究产物。

它不得：

- 写 F4 最终状态；
- 写 F5 准入、订单、持仓、现金或权益；
- 把 Qlib 自身模型门禁结果转换为 F4 绩效门禁结果；
- 用历史 Qlib 成功任务为当前 F4 授权。

### 5.3 F4 候选可用性契约

F4 注册表仍固定 24 个候选、六族各 4 个。每个窗口执行：

- M/R/D/L/E 由规则与组合适配器训练/评分；
- Q1–Q4 由 `f4_qlib_adapter.py` 以窗口隔离 Dataset、Recorder、模型和预测运行；
- Qlib 依赖、模型、预测、覆盖率或哈希失败时，仅当前候选记为 `candidate_unavailable`；
- 不可用候选不能进入 validation 排名，不能生成 test；
- 其他候选继续运行；
- 当前窗口全部候选不可用时，当前窗口拒绝；有效 test 窗口少于 4 才形成 F4 级阻断。

F4 的 `family_diagnostics.json` 必须分别记录六族的：登记数、可用数、不可用数、胜出窗口数和稳定 reason code。

### 5.4 F5 输入契约

F5 只能读取：

- 已原子发布的 F4 generation/兼容投影；
- 已原子发布的每日研究 generation 与 selection；
- F5 政策、硬风险规则和活动 F5 账本；
- 执行时所需的治理行情事实。

F5 禁止读取以下信息决定模拟许可：

- Qlib 周任务成功/失败状态；
- Qlib job ID、workflow ID、Recorder 状态；
- Qlib 单独门禁是否通过；
- 某候选是否属于 Qlib 族。

若 F4 winner 是 Qlib 候选，F5 仍只验证已发布 F4/selection 中的候选身份、模型哈希、锁哈希和政策哈希，不访问 Qlib 运行控制面。

## 6. 调度规则

### 6.1 Qlib 周任务

- 周六 18:30 独立运行；
- 失败按自身账本恢复；
- 可跨日复用原幂等键恢复；
- 不触发 F4；
- 不修改 F4 或 F5 状态。

### 6.2 F4 周任务

- 周日 10:00 独立到期；
- 必须通过每日完整因子 generation 与四类公共数据证据；
- 不查询“本周 Qlib 周任务是否成功”；
- 不要求 Qlib 周任务先结束；
- 若 Qlib 重任务正在写公共数据，F4 读取端通过 manifest/质量哈希与原子发布边界得到完整旧版本或明确失败，不读取 `.pending/.staging`；
- 若完整公共数据版本未变化，F4 可在 Qlib 独立研究仍运行时使用上一完整公共数据版本，但页面必须显示该版本的实际市场截止日，不冒充新版本；
- 同一 F4 身份继续由 `ResearchJobStore` 幂等保护。

### 6.3 并发边界

Qlib 写公共数据和 F4 读公共数据可以时间重叠，但必须通过原子 manifest/质量报告和不可变引用隔离。若现有数据发布不是原子的，实施阶段必须先建立完成指针或稳定读取快照，再解除任务级互斥，不能直接并发读取正在改写的 manifest。

## 7. 状态与失败语义

| 场景 | Qlib 状态 | F4 状态 | F5 状态 |
|---|---|---|---|
| Qlib 独立 workflow 绩效不通过 | `rejected` | 不受直接影响 | 不受直接影响 |
| Qlib 周任务中断，公共完整数据仍可验证 | `interrupted` | 可使用完整公共版本运行 | 只看已发布 F4/selection |
| PIT/行业/基准/质量证据不完整 | 独立记录 | `f4_blocked` | 按 F4/selection 准入关闭 |
| Q1 训练失败，其他候选可用 | 候选诊断 | Q1 `candidate_unavailable`，F4 继续 | 只看最终发布结果 |
| 当前窗口全部候选不可用 | 独立记录 | 当前窗口拒绝；不足 4 个有效窗口则阻断 | 不直接读取原因 |
| 最终样本外绩效不达标 | 可成功或失败 | `f4_rejected_exhausted` | 按现有 validated/experimental 模拟政策判定 |
| F4 研究候选通过 | 无直接授权作用 | `f4_research_candidate` | 继续执行独立身份、风险和模拟政策门禁 |

## 8. 页面与报告

### 8.1 Qlib 页面

只显示 Qlib 数据、任务、模型、Recorder、独立回测和 Qlib 自身门禁。文案不得声称它控制 F4 或 F5。

### 8.2 策略/F4 页面

必须分开展示：

- 公共 PIT/行业/基准/质量证据；
- 六族候选可用性；
- Qlib 候选不可用原因；
- 每窗口 winner 和族；
- test 聚合、成本压力、约束和绩效门禁。

不得把 Qlib 周任务失败作为 F4 总阻断原因，除非它造成公共数据产物自身不完整；此时文案必须写具体公共数据门禁，不写 `qlib_prerequisite_missing`。

### 8.3 F5 页面

只展示 F4/selection 身份、F5 政策、风险、订单、成交、持仓、权益和对账。不得展示或使用 Qlib task/workflow/Recorder 作为执行许可。

## 9. 代码修改边界

实施阶段预计修改：

- `scripts/research_training_scheduler.py`
  - 删除 `strategy_weekly` 对 `qlib_sync_complete`、`qlib_market_date`、同周 Qlib 成功任务和 Qlib 输出版本的调度级硬依赖；
  - 保留每日完整因子 generation 门禁；
  - 不修改 Qlib lane 自身恢复逻辑。
- `scripts/validate_strategy_portfolios.py` 与 `quant/strategy/f4_dataset.py`
  - 确保 F4 直接校验四类公共数据证据；
  - 使用稳定、完整的数据发布版本，拒绝 staging/pending。
- `quant/strategy/f4_real_pipeline.py`、`f4_candidate_factory.py`、`f4_qlib_adapter.py`
  - 复核并固化 Qlib 候选不可用隔离；
  - 不改变候选注册表、门槛、窗口或成本。
- F5 eligibility/reporting
  - 增加禁止依赖 Qlib 控制面或任务状态的契约测试；仅在发现现有直接依赖时修改实现。
- 页面、README、`docs/XUANJI_HANDOFF.md`
  - 更新状态解释和调用关系。

## 10. 测试策略

实施必须先写失败测试，至少覆盖：

### 10.1 调度解耦

- 公共数据、每日因子完整但 Qlib 周任务缺失时，`strategy_weekly` 仍调用 F4 handler；
- Qlib 周任务为 `failed/interrupted/running` 时，不作为 F4 总阻断；
- 每日因子 generation 缺失、日期或版本错配时仍阻断 F4；
- Qlib lane 的独立恢复、幂等和失败返回码不因解耦退化。

### 10.2 公共数据门禁

- manifest、质量、行业、基准全部一致时通过；
- 任一缺失、状态失败、版本错配、哈希错配或日期错配时 `f4_blocked`；
- staging/pending 产物不能成为 F4 输入；
- Qlib 任务成功但公共数据证据损坏时仍阻断，证明任务状态不能代替数据事实。

### 10.3 候选隔离

- Q1–Q4 全部依赖不可用时，20 个非 Qlib 候选继续；
- 单个 Qlib 候选失败不取消同窗口其他候选；
- 不可用 Qlib 候选无 test 产物、无 winner lock、无规则回退；
- 全部候选不可用才按窗口/最小窗口规则形成 F4 阻断；
- 族级诊断准确记录可用数、不可用数和 reason code。

### 10.4 F5 无直接依赖

- F5 准入在相同 F4/selection 输入下不因 Qlib 任务状态变化而改变；
- F5 代码和 API 不查询 Qlib job/workflow/Recorder；
- F4 winner 为 Qlib 候选时，F5 只校验已发布身份和哈希；
- F5 实盘权限恒为 false，任意下单继续拒绝。

### 10.5 回归

- 相关 Python 定向测试；
- 全量 Python；
- Node 契约；
- TypeScript；
- Vite 构建；
- API、全量功能、Web、UI 和浏览器控制台验证。

## 11. 迁移与历史事实

- 不删除或改写历史 `qlib_prerequisite_missing`、Qlib 失败、F4 拒绝和 F5 运行记录。
- 新行为由代码版本、测试和文档生效时间区分。
- 旧调度规格中的“Qlib 成功后才能运行 F4”保留为历史设计，但明确被本规格替代。
- 当前 Qlib 恢复任务继续按原 job ID 和账本运行；实施不得为了演示停止、改成功或跳过质量门禁。
- 当前 F4 状态不因代码解耦自动改变；只有新 F4 周期完成并原子发布后才能更新。

## 12. 完成判定

只有同时满足以下条件才算解耦完成：

1. `strategy_weekly` 不再查询或要求 Qlib 周任务成功。
2. F4 直接验证 PIT、行业、基准和质量报告，并拒绝损坏或跨版本输入。
3. Qlib 候选失败只形成 `candidate_unavailable`，其他候选继续运行。
4. F4 原有候选注册表、窗口、成本、组合和绩效门槛没有变化。
5. F5 对 Qlib 控制面无直接依赖，活动账本仍唯一为 F5。
6. 页面能区分 Qlib 独立状态、F4 公共数据门禁、候选状态和 F5 准入。
7. 历史任务和研究事实未删除、未机械改名、未伪造成功。
8. 定向测试、全量回归、构建、接口和页面验证全部通过。
9. README 与 `docs/XUANJI_HANDOFF.md` 清楚记录新的模块责任和调用边界。

## 13. 回滚边界

若解耦后发现 F4 读取公共数据存在并发撕裂，只允许暂停 `XuanJiQuant-Strategy-Weekly` 或恢复数据级互斥，不能恢复“Qlib 模型/周任务成功决定整个 F4”的业务依赖。回滚不得删除新旧任务账本、候选失败记录、F4 generation 或 F5 账本。
