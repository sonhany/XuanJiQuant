# 巨潮公告市场资讯接入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有市场资讯工作区增加与金十数据同级的巨潮公告查询页面。

**Architecture:** 新增独立 `cninfo_runner.py` 负责上游公告查询、规范化、缓存和限频；Node 新增只读 `/api/cninfo` 路由；React 新增市场资讯容器和巨潮公告面板。所有外部内容只读展示并保留公告时点。

**Tech Stack:** Python 3、requests、Node ESM、React 19、TypeScript、Vite、Node/Pytest 合同测试。

---

### Task 1: 巨潮查询核心

**Files:**
- Create: `scripts/cninfo_runner.py`
- Create: `tests/test_cninfo_runner.py`

- [ ] 编写失败测试，覆盖查询参数校验、标题 HTML 清洗、官方 PDF URL、缓存命中和上游错误。
- [ ] 运行 `python -m pytest tests/test_cninfo_runner.py -q`，确认因模块缺失而失败。
- [ ] 实现持久 JSON-lines runner、5 分钟缓存、请求间隔、分页上限和公告规范化。
- [ ] 重跑测试并确认通过。

### Task 2: 只读 API 路由

**Files:**
- Create: `server/routes/cninfo.mjs`
- Modify: `server/router.mjs`
- Create: `scripts/cninfo_api_contract_tests.mjs`

- [ ] 编写失败合同测试，要求 `/api/cninfo` 注册为只读 `query/status` 路由并使用独立 runner。
- [ ] 运行 `node scripts/cninfo_api_contract_tests.mjs`，确认失败。
- [ ] 实现路由和安全注册，设置 30 秒查询超时。
- [ ] 重跑合同测试并确认通过。

### Task 3: 市场资讯双页签与巨潮面板

**Files:**
- Create: `components/MarketInformationPanel.tsx`
- Create: `components/CninfoDisclosurePanel.tsx`
- Modify: `App.tsx`
- Create: `scripts/cninfo_frontend_contract_tests.mjs`

- [ ] 编写失败合同测试，要求金十/巨潮同级页签、公告三视图、查询条件、原文链接、加载和空状态。
- [ ] 运行 `node scripts/cninfo_frontend_contract_tests.mjs`，确认失败。
- [ ] 实现容器和巨潮面板，沿用现有工作台颜色、间距、字体和 8px 圆角。
- [ ] 重跑前端合同测试并确认通过。

### Task 4: 文档与全量验证

**Files:**
- Modify: `README.md`

- [ ] 更新市场资讯数据源、使用方式、缓存限频和研究边界。
- [ ] 运行巨潮测试、既有金十测试、`npx tsc --noEmit` 和 `npm run build`。
- [ ] 启动或复用本地服务，通过浏览器验证桌面和移动端页签切换、查询、原文链接、空状态及控制台健康。
- [ ] 记录未覆盖的上游限流和商业授权风险。
