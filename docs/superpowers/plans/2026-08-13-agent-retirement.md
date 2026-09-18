# XuanJiQuant AI Agent Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底删除自治 AI Agent 及其 Web/API/生命周期，把项目收敛为确定性数据、因子、策略、风控与只读模拟账本。

**Architecture:** 先用静态契约锁定“无 Agent”目标，再从外到内删除 Web/API/manager 和 Python 控制面。仍有价值的因子 DSL 与固定研究任务迁入普通研究模块；模拟订单写入口关闭，历史事实保留。

**Tech Stack:** Python 3、SQLite、pytest、Node.js ESM、React 19、TypeScript、Vite。

---

### Task 1: 建立 Agent 退役架构契约

**Files:**
- Create: `tests/test_agent_retirement.py`

- [ ] 断言生产源码无 `quant.agent` 导入且 `quant/agent` 生产文件不存在。
- [ ] 断言 Agent runner/control/scheduler/tool manifest 和旧 AI 五层生产文件不存在。
- [ ] 断言 Node manager、watchdog、router、paper/workbench 路由无 Agent action。
- [ ] 断言 React 无 Agent 组件、自治抽屉、API action 和当前态文案。
- [ ] 断言研究调度不导入 `ai_factor_agent/ai_strategy_agent`。
- [ ] 运行测试并确认因当前代码而红灯。

### Task 2: 迁移确定性因子与策略研究能力

**Files:**
- Create: `quant/factor/dsl.py`
- Create/Modify: `quant/factor/dynamic_factor_loader.py`
- Modify: `scripts/research_training_scheduler.py`
- Modify: factor/strategy runner and tests as required

- [ ] 为 DSL 公式白名单和非法表达式写失败测试。
- [ ] 从 `ai_factor_agent` 提取纯确定性计算到 `quant/factor/dsl.py`。
- [ ] 消除 `quant/factor` 对 `scripts.ai_factor_agent` 的导入。
- [ ] 将固定日程工厂改为直接调用普通 factor evaluation / strategy scan。
- [ ] 运行因子、策略、研究日程和 Qlib 边界测试。

### Task 3: 删除 Web Agent 功能

**Files:**
- Delete: `components/AgentRuntimeStatus.tsx`
- Delete: `components/agentRuntimeLifecycle.ts`
- Delete: `components/AutonomousSchedulingDrawer.tsx`
- Modify: `components/DashboardPanel.tsx`
- Modify: `components/PaperPanel.tsx`
- Modify: `components/WorkbenchStatus.tsx`
- Modify: `lib/workbench-state.mjs`
- Modify: `lib/ui-workbench.mjs`

- [ ] 删除所有 Agent 状态请求、状态映射、工作轨迹和自治配置 UI。
- [ ] 驾驶舱改为展示数据、风险、组合与“研究/只读账本模式”。
- [ ] 模拟盘页保留账户、持仓、订单、成交和报告，删除 Agent 选股/决策/诊断区。
- [ ] TypeScript 与前端退役契约通过。

### Task 4: 删除 Node Agent 生命周期与 API

**Files:**
- Delete: `server/ai_scheduler_manager.mjs`
- Modify: `server/watchdog.mjs`
- Modify: `server/router.mjs`
- Modify: `server/routes/paper.mjs`
- Modify: `server/routes/workbench.mjs`

- [ ] 移除 scheduler manager 导入、启动、状态、重启和 watchdog 事件。
- [ ] 从 `/api/paper` 白名单及 handler 删除全部 Agent/自治/旧五层 action。
- [ ] workbench 不再派发 Agent runner/control/scheduler 请求。
- [ ] 返回稳定的 `research_only`/`automatic_execution_disabled` 产品状态。
- [ ] Node 契约和路由安全测试通过。

### Task 5: 删除 Python Agent 与旧 AI 五层模块

**Files:**
- Delete: `quant/agent/*.py`
- Delete: `scripts/agent_runner.py`, `scripts/agent_control.py`, `scripts/ai_scheduler.py`, `scripts/ai_action_executor.py`, `scripts/ai_verifier.py`, `scripts/ai_memory.py`, `scripts/ai_self_improver.py`
- Delete: `scripts/ai_data_agent.py`, `scripts/ai_execution_agent.py`, `scripts/ai_risk_agent.py`, `scripts/ai_portfolio_planner.py`, `scripts/ai_stock_screener.py`, `scripts/ai_objective.py`, `scripts/ai_status.py`, `scripts/ai_validation_universe.py`, `scripts/ai_factor_agent.py`, `scripts/ai_strategy_agent.py`
- Delete: `ai_tools.json`
- Modify: remaining imports and callers

- [ ] 删除文件前完成调用者迁移。
- [ ] 删除 Agent 专属 paper controller/session/authority 生产链。
- [ ] 保留历史 SQLite 表和记录，不运行删除或迁移 SQL。
- [ ] 静态退役契约转绿。

### Task 6: 关闭模拟订单写入口

**Files:**
- Modify: `server/routes/execution.mjs`
- Modify: `scripts/execution_runner.py`
- Modify: `components/ExecutionPanel.tsx`
- Modify: security and execution contracts

- [ ] 路由只允许 execution 查询与审计 action。
- [ ] Web 不呈现下单、成交、撤单操作。
- [ ] 生产 runner 对遗留写 action 返回 `automatic_execution_disabled`，但内部账本读取和历史对账函数保留。
- [ ] 验证不存在自动订单生产者。

### Task 7: 清理旧测试和契约

**Files:**
- Delete: Agent 专用 Python/Node 契约测试
- Modify: shared workbench/execution/research tests

- [ ] 删除只验证已退役功能的测试。
- [ ] 保留并改写共享模块安全、账本、数据、因子、策略和风险测试。
- [ ] 确保测试发现不引用冻结备份或删除模块。

### Task 8: 文档、图与验收

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/XUANJI_SYSTEM_WORKFLOW_MAP.md`
- Create: 无 Agent 的交互式工作流图（若本轮可验证）

- [ ] 当前架构只描述数据、因子、策略、风控和只读模拟账本。
- [ ] Agent 历史只留退役说明，不作为当前状态。
- [ ] 运行全量 Python、全部 Node 契约、TypeScript、Vite、Web/UI 和浏览器控制台检查。
- [ ] 只读执行 SQLite `quick_check` 和历史数据保留核对。
- [ ] 明确在线服务未启动导致的任何验证阻断。
