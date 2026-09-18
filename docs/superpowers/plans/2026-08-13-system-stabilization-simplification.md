# XuanJiQuant System Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 分离业务决策、系统健康、执行资格和恢复状态，建立策略感知的组合合同及稳定的 paper-only 黄金闭环。

**Architecture:** 保留现有 Agent-only 执行链和数据库事实模型，在组合 verifier、恢复投影和工作台投影三个边界做最小修正。组合合同按 `normal/reduce_only/no_new_position` 分支验证；恢复层消费验证终态和系统级风险事实，不再从业务许可反推健康；页面只展示四个权威域及中文首要原因。

**Tech Stack:** Python 3、pytest、Node.js ESM、React/TypeScript、Vite、SQLite。

---

### Task 1: 策略感知组合合同

**Files:**
- Modify: `tests/test_agent_portfolio_control_plane.py`
- Modify: `scripts/ai_portfolio_planner.py`

- [ ] 增加 `normal`、合法 `reduce_only`、非法含买入的 `reduce_only`、合法无交易 `no_new_position` 四个合同测试。
- [ ] 单独运行新增测试，确认旧实现因只接受 `normal` 而出现预期失败。
- [ ] 提取纯函数验证计划容器、目标权重、调仓动作和总敞口；对 `reduce_only` 校验不买入、不增持、不增总敞口。
- [ ] 让 `verify_current_portfolio_plan()` 返回合同通过与执行资格两个独立事实。
- [ ] 运行组合控制面测试并确认通过。

### Task 2: 恢复健康与交易许可解耦

**Files:**
- Modify: `tests/test_agent_only_architecture.py`
- Modify: `tests/test_agent_autonomous_recovery.py`
- Modify: `scripts/ai_scheduler.py`
- Modify: `quant/agent/autonomous_recovery.py`（仅当测试证明现有接口不足）

- [ ] 增加合法 `reduce_only/no_new_position` 已知终态不会令恢复健康失败的测试。
- [ ] 增加结构损坏、未知副作用和未完成订单仍失败关闭的测试。
- [ ] 单独运行新增测试并确认旧实现按业务许可错误阻断。
- [ ] 从当前周期的 verifier 明细或明确已知业务终态派生 `verifier_passed`，从系统级硬故障派生 `hard_risk_clear`。
- [ ] 运行恢复与 Agent-only 架构测试并确认通过。

### Task 3: 工作台状态收敛

**Files:**
- Modify: `tests/test_workbench_status_contract.py`
- Modify: `server/routes/workbench.mjs`
- Modify: `components/DashboardPanel.tsx`（仅当现有布局会截断首要原因）

- [ ] 增加恢复阻挡码中文化、`reduce_only` 与恢复态互不冒充、页面不显示“未启用”的契约测试。
- [ ] 运行新增 Node/Python 驱动契约并确认旧展示失败。
- [ ] 统一阻挡码映射及首要原因投影，内部英文码移入诊断字段。
- [ ] 运行工作台契约并确认通过。

### Task 4: 六类模拟执行黄金闭环

**Files:**
- Modify: `tests/test_agent_paper_closed_loop.py`
- Modify: `tests/test_paper_order_router.py`（按缺口补充）
- Modify: `quant/agent/paper_controller.py`、`quant/execution/*`（仅对失败测试做最小修复）

- [ ] 盘点现有正常买卖、部分成交、普通拒单、未知回执和恢复后首单测试，列出缺失场景。
- [ ] 为缺失场景先写失败测试并确认红灯。
- [ ] 仅修复测试证明的账本终态或回执缺口。
- [ ] 运行完整模拟交易闭环回归并确认六类场景都有明确终态。

### Task 5: 文档与全量验证

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`

- [ ] 写明三个职责层、四个权威状态、三种交易政策和恢复健康边界。
- [ ] 运行相关 Python 测试及完整 Agent/执行回归。
- [ ] 运行 `npm run test:contracts`、TypeScript 检查和 `npm run build`。
- [ ] 运行现有 Web/UI 验证和浏览器控制台检查；若环境不具备，明确记录未验证项。
- [ ] 检查规格和计划无 `TODO/TBD`，核对所有完成声明都有本轮命令证据。

## 自检

- 规格中的职责边界、三种策略、恢复规则、展示规则和六类闭环均有对应任务。
- 计划没有占位实现或无条件生产完成声明。
- 本项目当前不是 Git 仓库，所有“提交”步骤不适用；以文件清单、测试输出和时间戳作为本轮变更证据。
