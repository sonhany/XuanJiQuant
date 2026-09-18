# Simplified Risk Control Plane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将风险展示和交易控制收敛为综合风险、系统安全门、Agent 策略、最终交易模式与逐单网关五个单一职责域。

**Architecture:** `server/routes/workbench.mjs` 负责一次性生成权威状态，兼容旧字段但禁止前端二次推导。React 页面只翻译 `effective_mode` 和其他权威域；`quant/risk/gateway.py` 保持唯一逐单批准权。

**Tech Stack:** Node.js ES modules、React/TypeScript、Python pytest、Node 合同测试、Vite。

---

### Task 1: 锁定权威风险状态合同

**Files:**
- Modify: `tests/test_workbench_status_contract.py`
- Modify: `server/routes/workbench.mjs`

- [ ] 编写失败测试，覆盖五个权威域及 `medium` 只读语义。
- [ ] 运行专项测试并确认因缺少新字段失败。
- [ ] 用纯函数生成 `safety_gate` 和 `effective_mode`，兼容投影旧字段。
- [ ] 重跑专项测试确认通过。

### Task 2: 收敛前端展示

**Files:**
- Modify: `scripts/investor_workbench_upgrade_contract_tests.mjs`
- Modify: `components/DashboardPanel.tsx`
- Modify: `components/ExecutionPanel.tsx`

- [ ] 编写失败合同，要求页面消费权威域并禁止读取旧许可字段。
- [ ] 运行合同并确认失败。
- [ ] 驾驶舱主区显示四项状态；模拟执行页只显示最终模式和 Agent 状态。
- [ ] 重跑合同、TypeScript 与构建。

### Task 3: 交接与完整验证

**Files:**
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`

- [ ] 记录单向状态流、兼容期限及风险网关所有权。
- [ ] 运行风险专项、Node 合同、全量 Python、TypeScript、Vite 构建。
- [ ] 重载本项目 API 后验证真实接口和页面控制台。

