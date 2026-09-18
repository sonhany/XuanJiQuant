# Qlib、F4 与 F5 责任解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 删除 Qlib 周任务对整个 F4 的总开关作用，同时保留公共研究数据门禁、Qlib 候选隔离和 F5 独立准入边界。

**Architecture:** `ResearchTrainingScheduler` 只校验每日完整因子发布后调用 F4；F4 入口继续直接校验 PIT manifest、质量报告、历史行业和基准。Q1–Q4 在 F4 窗口内按既有 `CandidateUnavailable` 语义隔离，F5 只消费已发布 F4/selection，不读取 Qlib 控制面。

**Tech Stack:** Python 3.11、pytest、SQLite ResearchJobStore、Node 契约、React/TypeScript、Vite

**Spec:** `docs/superpowers/specs/2026-08-30-qlib-f4-f5-decoupling-design.md`

## Global Constraints

- 唯一活动工作区是 `C:\Users\HYSHEN\XuanJiQuant`；不得读取后写入、运行或修改冻结备份。
- 当前目录没有 `.git`，无法创建 worktree 或提交；所有改动必须保留明确文件清单和测试证据。
- 不删除 Q1–Q4，不改变 24 候选、walk-forward 窗口、成本、组合政策或 F4 门槛。
- 不修改历史 Qlib/F4/F5 账本和既有研究结果。
- 不中断仍有新鲜心跳的 Qlib 任务。
- 所有研究产物保持 `research_only`、`execution_authority=false`；F5 保持 `live_execution_authority=false`。

---

### Task 1: 反转策略周任务的 Qlib 总开关契约

**Files:**
- Modify: `tests/test_research_training_scheduler.py`
- Modify: `scripts/research_training_scheduler.py:274-430`

**Interfaces:**
- Consumes: `run_due_once(...)`、每日完整因子发布字段、`ResearchJobStore`
- Produces: `strategy_weekly` 在因子发布有效时独立调用 handler；Qlib lane 自身恢复逻辑保持不变

- [ ] **Step 1: 写入失败测试，证明缺少 Qlib 周任务不能阻断 F4**

在 `tests/test_research_training_scheduler.py` 新增：

```python
def test_strategy_weekly_does_not_require_qlib_weekly_task(tmp_path):
    store = ResearchJobStore(tmp_path / "research_jobs.db")
    calls = []
    snapshot = {
        **_snapshot(),
        "factor_publication_complete": True,
        "factor_publication_market_date": "20260807",
        "factor_publication_data_version": "pit-v1",
        "qlib_sync_complete": False,
        "qlib_market_date": "",
        "qlib_data_version": "qlib-independent-failure",
    }
    result = run_due_once(
        now=SUNDAY_1000,
        trading_days=CALENDAR,
        data_snapshot=snapshot,
        store=store,
        factor_version="factor-v1",
        strategy_version="strategy-v1",
        qlib_version="qlib-v1",
        lane="strategy",
        handlers={
            "strategy_weekly": lambda job, *_args: calls.append(job.kind)
            or {"success": True}
        },
    )
    assert calls == ["strategy_weekly"]
    assert result[0]["status"] == "succeeded"
```

- [ ] **Step 2: 运行红测并确认失败原因是旧 Qlib 前置门禁**

Run:

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest tests\test_research_training_scheduler.py::test_strategy_weekly_does_not_require_qlib_weekly_task -q
```

Expected: FAIL，handler 未被调用，原因来自 `qlib_data_sync_incomplete` 或 `qlib_prerequisite_missing`。

- [ ] **Step 3: 最小修改调度器**

在 `_block_reason()` 的 `strategy_weekly` 分支中只保留：

```python
if data_snapshot.get("factor_publication_complete") is not True:
    return "factor_prerequisite_missing"
if compact_factor_date != compact_job_date:
    return "factor_market_date_mismatch"
if factor_publication_data_version != job.data_version:
    return "factor_data_version_mismatch"
```

删除该分支对 `qlib_sync_complete`、`qlib_market_date`、同周 Qlib 成功 job 和 Qlib 输出版本的判断。删除只为该旧门禁服务的 `_current_week_qlib_success()`；保留 `_overdue_qlib_retry()` 和 Qlib lane 的独立恢复逻辑。

- [ ] **Step 4: 反转旧测试语义**

将旧的 `test_scheduler_requires_current_week_qlib_success_before_strategy` 替换为“Qlib 任务缺失/失败不阻断策略 handler”的行为测试。保留并继续通过：

- 因子完整发布缺失时阻断；
- 因子日期错配时阻断；
- 因子数据版本错配时阻断；
- Qlib lane 独立重试、跨日恢复和幂等。

- [ ] **Step 5: 运行绿色定向回归**

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest tests\test_research_training_scheduler.py tests\test_research_training_schedule.py tests\test_qlib_schedule.py -q
```

Expected: 0 failed。

- [ ] **Step 6: 记录无 Git 边界**

确认 `.git` 不存在，不执行提交；在最终报告列出测试与修改文件。

---

### Task 2: 证明公共数据门禁、候选隔离和 F5 独立性未退化

**Files:**
- Test: `tests/test_f4_validation_pipeline.py`
- Test: `tests/test_f4_pipeline_v2.py`
- Test: `tests/test_f4_candidate_factory.py`
- Test: `tests/test_f4_qlib_adapter_v2.py`
- Test: `tests/test_f5_paper_*.py`
- Modify only if a failing behavioral test exposes a real gap

**Interfaces:**
- Consumes: `run_validation()`、`run_v2_nested_window()`、`fit_qlib_window()`、F5 eligibility/service
- Produces: 数据级失败继续阻断 F4；Qlib 候选级失败只隔离候选；F5 准入不读取 Qlib 控制面

- [ ] **Step 1: 运行公共数据门禁测试**

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest tests\test_f4_validation_pipeline.py -q
```

必须覆盖并通过：incomplete manifest、缺失 benchmark、版本错配、F3/PIT 日期错配和成功公共证据。

- [ ] **Step 2: 运行 Qlib 候选隔离测试**

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest tests\test_f4_pipeline_v2.py tests\test_f4_candidate_factory.py tests\test_f4_qlib_adapter_v2.py tests\test_f4_metrics.py -q
```

必须证明：Qlib 依赖/训练/预测/覆盖失败形成 `CandidateUnavailable`，规则候选继续，失败候选无 test 预测且不回退规则身份。

- [ ] **Step 3: 运行 F5 独立准入与账本测试**

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest tests\test_f5_paper_*.py -q
```

必须证明 F5 只消费已发布 F4/selection、政策、风险与行情，当前账户仍来自 `data/paper/f5_ledger.db`，实盘权限为 false。

- [ ] **Step 4: 若发现缺口，严格按红—绿循环修复**

只允许针对失败行为做最小实现，不增加新候选、不改变阈值、不修改活动账本。每个生产修改必须先保留能够复现缺口的失败测试，再实现并重新运行对应测试文件。

- [ ] **Step 5: 运行研究边界 Node 契约**

```powershell
node scripts\research_schedule_contract_tests.mjs
node scripts\research_boundary_contract_tests.mjs
node scripts\f5_paper_execution_contract_tests.mjs
```

Expected: 三项均退出 0。

---

### Task 3: 更新权威文档与完成全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/superpowers/specs/2026-08-30-qlib-f4-f5-decoupling-design.md`
- Verify: `scripts/full_validation.py`、`scripts/web_verify.mjs`、`scripts/ui_verify.mjs`

**Interfaces:**
- Consumes: Task 1–2 的最终行为和测试证据
- Produces: 可交接的职责、调用链、失败语义、验证结果与当前运行态说明

- [ ] **Step 1: 更新 README 调用链**

明确写入：

```text
Qlib-Weekly -> 独立 Qlib 数据/模型/Recorder/回测/门禁
Strategy-Weekly -> 每日因子发布 + PIT/行业/基准/质量 -> F4
F4 Qlib family unavailable -> 只隔离 Q1-Q4
F5 -> 已发布 F4/selection -> 独立模拟准入与账本
```

删除或改写“周日任务必须看到本周六 Qlib 成功账本”的当前规则；历史段落继续保留并标记为旧设计事实。

- [ ] **Step 2: 更新交接文档**

在 `docs/XUANJI_HANDOFF.md` 记录：

- 新规格替代旧任务级依赖；
- 公共数据证据仍失败关闭；
- Qlib 候选隔离语义；
- F5 无 Qlib 控制面依赖；
- 历史 `qlib_prerequisite_missing` 记录不改写。

- [ ] **Step 3: 将规格状态更新为已实施待验收**

仅在 Task 1–2 全部通过后，把规格状态改为“已实施，等待全量验收”；全量验证完成后再改为“已实施并验收”。

- [ ] **Step 4: 运行全量 Python**

```powershell
& '.\.venv-qlib\Scripts\python.exe' -m pytest -q
```

Expected: 0 failed；记录 passed/skipped 精确数量。

- [ ] **Step 5: 运行全部 Node、TypeScript 和构建**

```powershell
npm run test:contracts
npx tsc --noEmit
npm run build
```

Expected: 0 failed，Vite 退出 0。

- [ ] **Step 6: 运行接口与页面验证**

```powershell
& '.\.venv-qlib\Scripts\python.exe' scripts\test_api.py
& '.\.venv-qlib\Scripts\python.exe' scripts\full_validation.py
node scripts\web_verify.mjs
node scripts\ui_verify.mjs
```

Expected: API、全量功能、Web、UI 均 0 failed；浏览器控制台无 warning/error。

- [ ] **Step 7: 核对当前运行态而不伪造完成**

读取 Web/API 端口、Qlib 当前 job、F4 最新发布和 F5 活动账本。代码解耦成功不等于当前 Qlib 或 F4 长任务已完成；报告必须把“代码验收”和“运行中研究任务”分开。

- [ ] **Step 8: 最终自检**

确认：

- `strategy_weekly` 不查询 Qlib 周任务成功；
- F4 公共数据门禁仍存在；
- Qlib 候选隔离测试通过；
- F5 实盘权限仍为 false；
- README、交接文档和规格一致；
- 没有修改冻结备份、历史账本或硬风控阈值。
