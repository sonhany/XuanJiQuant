# System-wide Chinese Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让驾驶舱目标组合稳定显示中文股票名称、让 AI 与系统诊断默认展开，并将全系统已知用户可见状态和提醒统一为中文，同时保持内部协议与审计事实不变。

**Architecture:** `server/routes/workbench.mjs` 复用现有 `data-realtime` 常驻进程，仅为最多 10 个目标代码补充名称，并在纯聚合函数中复制合并。`lib/workbench-state.mjs` 作为集中中文展示层，组件继续使用原英文枚举进行判断，只在最终渲染时调用语义化映射函数；静态英文按明确清单定向替换。

**Tech Stack:** React 19、TypeScript、Node.js ES Modules、Python/Pytest、现有 Node 契约测试、Vite。

**Execution note:** 当前目录没有 `.git` 元数据，因此每个任务的“提交”检查点只记录完成状态，不执行 `git commit`，也不初始化新仓库。

---

## File responsibility map

**Create**

- `scripts/system_chinese_display_contract_tests.mjs`：集中映射、典型页面静态中文和内部枚举不直出的契约。

**Modify**

- `tests/test_workbench_status_contract.py`：Workbench 目标名称合并、不可变性和失败降级测试。
- `server/routes/workbench.mjs`：复用 `data-realtime`、收集目标代码、规范化名称并传入状态聚合。
- `lib/workbench-state.mjs`：状态、模式、策略、所有者、优先级、布尔值和数据分段中文映射。
- `scripts/investor_workbench_upgrade_contract_tests.mjs`：共享展示函数契约。
- `scripts/professional_cockpit_contract_tests.mjs`：目标名称和诊断默认展开契约。
- `components/DashboardPanel.tsx`：显示“名称 代码”、默认展开诊断、诊断枚举中文化。
- `components/AgentRuntimeStatus.tsx`：运行策略区用户可见字段与枚举中文化。
- `components/DbPanel.tsx`：市场列表和 K 线区域静态英文中文化。
- `components/FactorPanel.tsx`：训练/验证/测试分段表头和提示中文化。
- `components/LocalProfileScreen.tsx`：本地身份页英文口号中文化。
- `components/AlertPanel.tsx`：规则级别等已知状态通过共享映射显示。
- `components/QlibResearchPanel.tsx`、`components/qlib/QlibOverview.tsx` 及实际直接渲染任务状态的 Qlib 子组件：任务状态和类型中文化，品牌与模型名称保留。
- `README.md`：记录名称数据流、中文展示层和维护边界。

不修改 Python 交易、风控、AI 决策协议、SQLite schema、缓存键和历史数据。

---

### Task 1: 建立集中中文展示函数

**Files:**

- Modify: `lib/workbench-state.mjs:78-151`
- Modify: `scripts/investor_workbench_upgrade_contract_tests.mjs:1-35`
- Create: `scripts/system_chinese_display_contract_tests.mjs`

- [ ] **Step 1: 为语义化映射写失败测试**

在 `scripts/investor_workbench_upgrade_contract_tests.mjs` 的导入中增加：

```js
import {
  booleanLabel,
  modeLabel,
  ownerLabel,
  policyLabel,
  priorityLabel,
  segmentLabel,
} from '../lib/workbench-state.mjs';
```

并增加明确断言：

```js
assert.equal(statusLabel('unknown'), '未知');
assert.equal(statusLabel('stale'), '已过期');
assert.equal(statusLabel('queued'), '排队中');
assert.equal(modeLabel('research_idle'), '研究待机');
assert.equal(modeLabel('paper_guarded'), '模拟盘受控');
assert.equal(modeLabel('target_portfolio'), '目标组合');
assert.equal(policyLabel('no_new_position'), '暂不新增仓位');
assert.equal(policyLabel('reduce_only'), '仅允许减仓');
assert.equal(ownerLabel('agent_runtime'), '智能体运行时');
assert.equal(priorityLabel('high'), '高');
assert.equal(booleanLabel(true), '是');
assert.equal(booleanLabel(false, '已启用', '已禁用'), '已禁用');
assert.equal(segmentLabel('train'), '训练集');
assert.equal(segmentLabel('valid'), '验证集');
assert.equal(segmentLabel('test'), '测试集');
```

创建 `scripts/system_chinese_display_contract_tests.mjs`，先保护协议边界：

```js
import fs from 'node:fs';
import assert from 'node:assert/strict';

const state = fs.readFileSync('lib/workbench-state.mjs', 'utf8');
assert(state.includes("research_idle: '研究待机'"));
assert(state.includes("no_new_position: '暂不新增仓位'"));
assert(state.includes("agent_runtime: '智能体运行时'"));
assert(!state.includes("return value = '研究待机'"), 'display labels must not overwrite protocol values');

console.log('system Chinese display contract tests passed');
```

- [ ] **Step 2: 运行测试并确认 RED**

Run:

```powershell
node scripts/investor_workbench_upgrade_contract_tests.mjs
node scripts/system_chinese_display_contract_tests.mjs
```

Expected: FAIL，原因是新函数尚未导出、映射尚不存在。

- [ ] **Step 3: 实现最小集中映射**

在 `lib/workbench-state.mjs` 扩展 `STATUS_LABELS`，至少加入：

```js
const STATUS_LABELS = {
  // 保留已有项目
  fresh: '数据新鲜',
  stale: '已过期',
  live: '实时',
  current: '当前',
  queued: '排队中',
  cancelling: '取消中',
  completed: '已完成',
  failed: '失败',
  success: '成功',
  enabled: '已启用',
  disabled: '已禁用',
  idle: '空闲',
};
```

增加纯展示映射和统一未知值策略：

```js
const MODE_LABELS = {
  research_idle: '研究待机',
  intraday: '盘中运行',
  postclose: '盘后运行',
  target_portfolio: '目标组合',
  paper_guarded: '模拟盘受控',
  analysis_only: '仅分析',
};

const POLICY_LABELS = {
  normal: '正常交易',
  reduce_only: '仅允许减仓',
  no_new_position: '暂不新增仓位',
  advisory_only: '仅供建议',
};

const OWNER_LABELS = {
  agent_runtime: '智能体运行时',
  legacy_ai_loop: '传统 AI 循环',
};

const SEGMENT_LABELS = {
  train: '训练集',
  valid: '验证集',
  validation: '验证集',
  test: '测试集',
};

export function modeLabel(value) {
  return MODE_LABELS[String(value || '').toLowerCase()] || '未识别模式';
}

export function policyLabel(value) {
  return POLICY_LABELS[String(value || '').toLowerCase()] || '未识别策略';
}

export function ownerLabel(value) {
  return OWNER_LABELS[String(value || '').toLowerCase()] || '未识别执行方';
}

export function priorityLabel(value) {
  return statusLabel(value);
}

export function booleanLabel(value, trueLabel = '是', falseLabel = '否') {
  return value === true ? trueLabel : value === false ? falseLabel : '未知';
}

export function segmentLabel(value) {
  return SEGMENT_LABELS[String(value || '').toLowerCase()] || '未识别分段';
}
```

映射函数不得修改传入对象，不得参与请求参数和条件判断。

- [ ] **Step 4: 运行映射契约并确认 GREEN**

Run:

```powershell
node scripts/investor_workbench_upgrade_contract_tests.mjs
node scripts/system_chinese_display_contract_tests.mjs
```

Expected: 两个脚本退出码均为 0。

- [ ] **Step 5: 记录任务检查点**

Run:

```powershell
git rev-parse --is-inside-work-tree
```

Expected: 当前环境返回“not a git repository”；不初始化仓库，记录 Task 1 完成。

---

### Task 2: 在 Workbench 只读聚合层补充目标股票名称

**Files:**

- Modify: `tests/test_workbench_status_contract.py:24-101`
- Modify: `server/routes/workbench.mjs:1-12,88-228,245-306`

- [ ] **Step 1: 写目标名称失败测试**

扩展 `test_composed_status_uses_execution_account_and_fails_closed` 中的 Node 脚本：

```js
const portfolioSource = {
  target_weights: [
    { code: '600519', target_weight: 0.1, confidence: 0.8 },
    { code: '000001', name: '平安银行', target_weight: 0.08, confidence: 0.7 },
  ],
};
const named = composeWorkbenchStatus({
  now: new Date('2026-08-01T10:00:00.000Z'),
  autonomous: { portfolio: portfolioSource },
  targetQuoteNames: { '600519': '贵州茅台', '000001': '错误覆盖名' },
  execution: { status: { total_equity: 1000000 }, positions: [] },
  risk: {},
  health: { overall: 'ok' },
  alerts: {},
  errors: {},
});
console.log(JSON.stringify({ named, portfolioSource }));
```

Python 断言：

```python
assert payload["named"]["portfolio"]["target_weights"][0]["name"] == "贵州茅台"
assert payload["named"]["portfolio"]["target_weights"][1]["name"] == "平安银行"
assert "name" not in payload["portfolioSource"]["target_weights"][0]
```

另增加源码契约，要求 Workbench 复用 `data-realtime` 单例并限制查询代码：

```python
assert "new PersistentRunner('data_runner.py', 'data-realtime')" in source
assert "action: 'realtime_prices'" in source
assert ".slice(0, 10)" in source
assert "target_names" in source
```

- [ ] **Step 2: 运行 Workbench 测试并确认 RED**

Run:

```powershell
python -m pytest tests/test_workbench_status_contract.py -q
```

Expected: FAIL，目标行没有 `name`，源码中也没有名称数据进程。

- [ ] **Step 3: 实现纯名称规范化和不可变合并**

在 `server/routes/workbench.mjs` 增加：

```js
const dataRealtimeRunner = new PersistentRunner('data_runner.py', 'data-realtime');

function normalizedStockCode(value) {
  const match = String(value || '').toUpperCase().match(/(\d{6})/);
  return match ? match[1] : '';
}

function targetCodes(portfolio) {
  return [...new Set((portfolio?.target_weights || [])
    .map((row) => normalizedStockCode(row?.code))
    .filter(Boolean))].slice(0, 10);
}

function quoteNameMap(quotes) {
  const names = {};
  for (const [key, quote] of Object.entries(quotes || {})) {
    const code = normalizedStockCode(key || quote?.code);
    const name = String(quote?.name || '').trim();
    if (code && name && name !== code) names[code] = name;
  }
  return names;
}

function portfolioWithNames(portfolio, targetQuoteNames, positions) {
  if (!portfolio || typeof portfolio !== 'object') return null;
  const positionNames = new Map((positions || []).map((row) => [
    normalizedStockCode(row?.code),
    String(row?.name || row?.stock_name || '').trim(),
  ]));
  return {
    ...portfolio,
    target_weights: (portfolio.target_weights || []).map((row) => {
      const code = normalizedStockCode(row?.code);
      const existing = String(row?.name || row?.stock_name || '').trim();
      const name = existing && existing !== code
        ? existing
        : targetQuoteNames?.[code] || positionNames.get(code) || '';
      return { ...row, ...(name ? { name } : {}) };
    }),
  };
}
```

在 `composeWorkbenchStatus` 中先构造 `portfolio`，再返回它：

```js
const positions = Array.isArray(input.execution?.positions) ? input.execution.positions : [];
const portfolio = portfolioWithNames(
  input.autonomous?.portfolio,
  input.targetQuoteNames || {},
  positions,
);
```

返回对象使用 `positions` 和 `portfolio`，不直接透传缓存对象。

- [ ] **Step 4: 在处理器中做有界名称查询和失败降级**

在初始 runner 结果归一化后增加：

```js
let targetQuoteNames = {};
const codes = targetCodes(values.autonomous?.portfolio);
if (codes.length) {
  try {
    const quoteResult = await dataRealtimeRunner.call(
      { action: 'realtime_prices', codes },
      5_000,
    );
    const quotes = quoteResult?.data ?? quoteResult;
    targetQuoteNames = quoteNameMap(quotes);
  } catch (error) {
    errors.target_names = error?.message || String(error);
  }
}
```

最终调用改为：

```js
composeWorkbenchStatus({
  ...values,
  errors,
  schedulerRuntime,
  paperRuntime,
  targetQuoteNames,
})
```

名称失败不得加入交易许可的 `blockers`，只出现在服务诊断错误中。

- [ ] **Step 5: 运行 Workbench 与性能契约并确认 GREEN**

Run:

```powershell
python -m pytest tests/test_workbench_status_contract.py -q
node scripts/workbench_performance_contract_tests.mjs
node scripts/cockpit_latency_contract_tests.mjs
```

Expected: 全部退出码为 0；现有账户、风险和进程状态契约保持不变。

- [ ] **Step 6: 记录任务检查点**

确认没有写入 `ai:portfolio:latest`、SQLite 或历史报告；当前无 Git 仓库，不提交。

---

### Task 3: 修正驾驶舱名称显示、诊断默认展开和动态枚举

**Files:**

- Modify: `scripts/professional_cockpit_contract_tests.mjs:1-18`
- Modify: `components/DashboardPanel.tsx:1-345`

- [ ] **Step 1: 写驾驶舱失败契约**

将旧的“诊断必须折叠”断言替换为：

```js
assert(
  /<details\s+className="diagnostics"\s+open>/.test(dashboard),
  'AI operational diagnostics must be expanded by default',
);
assert(
  dashboard.includes("`${row.name} ${row.code}`"),
  'target portfolio must display the resolved stock name and code',
);
assert(dashboard.includes('modeLabel(data?.scheduler?.mode)'), 'scheduler mode must use Chinese display mapping');
assert(dashboard.includes('statusLabel(data?.services?.overall)'), 'system health must use Chinese display mapping');
```

- [ ] **Step 2: 运行契约并确认 RED**

Run:

```powershell
node scripts/professional_cockpit_contract_tests.mjs
```

Expected: FAIL，诊断未默认展开且动态模式仍直接显示英文。

- [ ] **Step 3: 实现最小驾驶舱改动**

从 `lib/workbench-state.mjs` 导入 `modeLabel`。目标组合首列改为明确的名称/代码表达式：

```tsx
<td title={row.reason || ''}>
  {row.name ? `${row.name} ${row.code}` : row.code}
</td>
```

诊断改为：

```tsx
<details className="diagnostics" open>
```

动态值改为：

```tsx
<div><span>调度模式</span><strong title={data?.scheduler?.mode || ''}>{modeLabel(data?.scheduler?.mode)}</strong></div>
<div><span>系统健康</span><strong title={data?.services?.overall || ''}>{statusLabel(data?.services?.overall)}</strong></div>
```

模型供应商品牌保持原值，时间保持 `zh-CN` 格式。

- [ ] **Step 4: 运行驾驶舱相关契约并确认 GREEN**

Run:

```powershell
node scripts/professional_cockpit_contract_tests.mjs
node scripts/control_surface_layout_contract_tests.mjs
node scripts/investor_workbench_upgrade_contract_tests.mjs
node scripts/market_sentiment_frontend_contract_tests.mjs
```

Expected: 全部退出码为 0。

- [ ] **Step 5: 记录任务检查点**

确认诊断仍是原生 `<details>`，用户可手动折叠；不增加 localStorage。

---

### Task 4: 清理核心页面的英文静态文案和运行枚举

**Files:**

- Modify: `scripts/system_chinese_display_contract_tests.mjs`
- Modify: `components/AgentRuntimeStatus.tsx`
- Modify: `components/DbPanel.tsx:790-815,1138-1150,1745-1760`
- Modify: `components/FactorPanel.tsx:60-85`
- Modify: `components/LocalProfileScreen.tsx:65-85`
- Modify: `components/AlertPanel.tsx:180-212`

- [ ] **Step 1: 写核心页面英文残留失败契约**

在 `scripts/system_chinese_display_contract_tests.mjs` 读取对应组件，加入：

```js
const files = {
  agent: fs.readFileSync('components/AgentRuntimeStatus.tsx', 'utf8'),
  db: fs.readFileSync('components/DbPanel.tsx', 'utf8'),
  factor: fs.readFileSync('components/FactorPanel.tsx', 'utf8'),
  profile: fs.readFileSync('components/LocalProfileScreen.tsx', 'utf8'),
  alerts: fs.readFileSync('components/AlertPanel.tsx', 'utf8'),
};

for (const fragment of [
  '>enabled<', '>mode<', '>execution_owner<', '>database<', '>hanging calls<',
  'TOP100 by amount', '15s polling', 'K-line Trend',
  '>Segment<', '>Date Range<', '>Positive<', '>Periods<',
  '>SIMULATION ONLY<', '>RISK FIRST<', '>AUDITABLE<',
]) {
  assert(!Object.values(files).some((source) => source.includes(fragment)), `unlocalized UI fragment: ${fragment}`);
}
assert(files.agent.includes('modeLabel(mode)'));
assert(files.agent.includes('ownerLabel(owner)'));
assert(files.alerts.includes('statusLabel(rule.level)'));
```

品牌和缩写不加入禁止清单。

- [ ] **Step 2: 运行契约并确认 RED**

Run:

```powershell
node scripts/system_chinese_display_contract_tests.mjs
```

Expected: FAIL，并列出当前仍存在的已知英文片段。

- [ ] **Step 3: 修改 Agent Runtime 展示**

导入共享函数并将策略摘要改为中文标签：

```tsx
<div><dt>是否启用</dt><dd>{booleanLabel(enabled, '已启用', '已禁用')}</dd></div>
<div><dt>运行模式</dt><dd className={modeTone(mode)} title={mode}>{modeLabel(mode)}</dd></div>
<div><dt>执行负责方</dt><dd title={owner}>{ownerLabel(owner)}</dd></div>
<div><dt><Database size={11} aria-hidden="true" />数据库</dt><dd className={statusTone(databaseStatus)}>{statusLabel(databaseStatus)}</dd></div>
<div><dt>悬挂调用</dt><dd className={hangingCount > 0 ? 'is-warn' : 'is-neutral'}>{hangingCount}</dd></div>
```

实时决策链中的 `Agent Runtime`、`Legacy AI Loop` 改为调用 `ownerLabel`，秒数显示为“每 N 秒”。

- [ ] **Step 4: 修改市场、因子、本地身份和告警文案**

使用下列确定替换：

```text
TOP100 by amount -> 成交额前 100
live -> 实时
daily -> 日线快照
15s polling -> 每 15 秒轮询
K-line Trend -> K 线走势
Train / Valid / Test -> 训练集 / 验证集 / 测试集
Segment -> 数据分段
Date Range -> 日期范围
IC Mean -> IC 均值
Positive -> 正值占比
Periods -> 样本期数
SIMULATION ONLY -> 仅限模拟交易
RISK FIRST -> 风控优先
AUDITABLE -> 全程可审计
```

`AlertPanel` 中 `rule.level` 使用 `statusLabel(rule.level)`，规则 ID、来源和历史告警正文保持原文。

- [ ] **Step 5: 运行核心中文契约并确认 GREEN**

Run:

```powershell
node scripts/system_chinese_display_contract_tests.mjs
node scripts/ui_audit_fixes_contract_tests.mjs
node scripts/data_browse_contract_tests.mjs
node scripts/authoritative_risk_alert_contract_tests.mjs
```

Expected: 全部退出码为 0。

- [ ] **Step 6: 记录任务检查点**

确认没有修改组件中的请求 action、条件比较枚举、缓存键和 API 字段。

---

### Task 5: 中文化 Qlib 和其余已知任务状态

**Files:**

- Modify: `scripts/system_chinese_display_contract_tests.mjs`
- Modify: `scripts/qlib_chinese_ui_contract_tests.mjs`
- Modify: `components/QlibResearchPanel.tsx`
- Modify: `components/qlib/QlibOverview.tsx`
- Modify: `components/qlib/QlibDataPanel.tsx`
- Modify: `components/qlib/QlibTrainingPanel.tsx`
- Modify: `components/qlib/QlibExperimentsPanel.tsx`
- Modify: `components/qlib/QlibModelsPanel.tsx`
- Modify: `components/qlib/QlibBacktestPanel.tsx`
- Modify: `components/qlib/QlibLogsPanel.tsx`

- [ ] **Step 1: 写 Qlib 动态状态失败契约**

在 `scripts/qlib_chinese_ui_contract_tests.mjs` 增加共享映射要求：

```js
assert(
  source.includes('statusLabel(') || source.includes('qlibStatusLabel('),
  'Qlib dynamic statuses must use a Chinese display mapping',
);
for (const fragment of ['status?.active_job?.kind ||', '>{item.status}<', '>{job.status}<']) {
  assert(!source.includes(fragment), `Qlib must not render a raw internal value: ${fragment}`);
}
```

在全局中文契约中要求 Qlib 页面仍保留 `Qlib`、`LightGBM`、`Alpha158` 等品牌/模型名，证明测试没有机械禁止英文。

- [ ] **Step 2: 运行 Qlib 契约并确认 RED**

Run:

```powershell
node scripts/qlib_chinese_ui_contract_tests.mjs
```

Expected: FAIL，至少活动任务类型或任务状态仍直接展示内部值。

- [ ] **Step 3: 增加 Qlib 展示映射并替换直接渲染**

优先复用 `statusLabel`。对 Qlib 专用任务类型在 `QlibResearchPanel.tsx` 定义只读展示映射：

```ts
const QLIB_JOB_LABELS: Record<string, string> = {
  setup: '目录检查',
  collect_one_year: '采集近一年行情',
  collect_six_years: '采集六年原始行情',
  quality_six_years: '六年数据质量门禁',
  train: '模型训练',
  backtest: '回测评估',
};

export function qlibJobLabel(value: unknown) {
  return QLIB_JOB_LABELS[String(value || '')] || '未识别任务';
}
```

子组件通过 props 接收 `statusLabel`/`qlibJobLabel` 或直接导入共享纯函数；内部 `item.status === 'running'` 等判断保持英文值不变。

- [ ] **Step 4: 运行 Qlib 与全局中文契约并确认 GREEN**

Run:

```powershell
node scripts/qlib_chinese_ui_contract_tests.mjs
node scripts/qlib_panel_contract_tests.mjs
node scripts/qlib_control_contract_tests.mjs
node scripts/system_chinese_display_contract_tests.mjs
```

Expected: 全部退出码为 0。

- [ ] **Step 5: 记录任务检查点**

确认 Qlib job kind/status 请求参数和响应结构保持不变，只改变 JSX 文本。

---

### Task 6: 更新 README 并完成最终验证

**Files:**

- Modify: `README.md`（在工作区/页面调用关系章节后增加“展示层中文化与目标组合名称”）
- Verify: `docs/superpowers/specs/2026-08-01-system-wide-chinese-display-design.md`
- Verify: all files changed in Tasks 1-5

- [ ] **Step 1: 写 README 失败契约**

在 `scripts/system_chinese_display_contract_tests.mjs` 增加：

```js
const readme = fs.readFileSync('README.md', 'utf8');
for (const text of [
  '展示层中文化与目标组合名称',
  '内部协议仍使用稳定英文枚举',
  'data-realtime',
  '不写回目标组合计划',
  '历史审计原文',
]) {
  assert(readme.includes(text), `README missing Chinese display handoff: ${text}`);
}
```

- [ ] **Step 2: 运行契约并确认 RED**

Run:

```powershell
node scripts/system_chinese_display_contract_tests.mjs
```

Expected: FAIL，README 交接章节尚不存在。

- [ ] **Step 3: 更新 README 调用关系和维护边界**

README 写明完整调用链：

```text
DashboardPanel
  -> /api/workbench
  -> paper_runner 读取目标组合
  -> data_runner(data-realtime) 按最多 10 个目标代码补充名称
  -> composeWorkbenchStatus 复制合并
  -> 页面显示“名称 代码”
```

同时写明：

1. 中文只在 `lib/workbench-state.mjs` 等展示函数生成。
2. 内部协议仍使用稳定英文枚举，条件判断和请求不得改为中文。
3. 名称只读补充，不写回目标组合计划、缓存审计或数据库。
4. 外部原文、模型原始输出和历史审计原文不机械翻译。
5. 新组件不得直接显示已知内部枚举，应优先扩展共享映射。

- [ ] **Step 4: 运行全部定向契约**

Run:

```powershell
node scripts/system_chinese_display_contract_tests.mjs
node scripts/investor_workbench_upgrade_contract_tests.mjs
node scripts/professional_cockpit_contract_tests.mjs
node scripts/control_surface_layout_contract_tests.mjs
node scripts/qlib_chinese_ui_contract_tests.mjs
python -m pytest tests/test_workbench_status_contract.py -q
```

Expected: 全部退出码为 0。

- [ ] **Step 5: 运行类型检查和生产构建**

Run:

```powershell
npx tsc --noEmit
npm run build
```

Expected: TypeScript 无错误；Vite 构建退出码为 0。

- [ ] **Step 6: 运行全量回归**

Run:

```powershell
python -m pytest -q
```

Expected: 无失败；跳过项只允许为项目已有的显式 skip。

- [ ] **Step 7: 重载只涉及新项目的常驻进程并验证真实 API**

先用只读命令核对进程命令行，只停止 `C:\Users\HYSHEN\XuanJiQuant` 下的 `paper_runner.py` 与 `data_runner.py` 子进程，让 Node 常驻管理器按请求重建；不得触碰冻结备份进程。

随后调用：

```powershell
$body = @{ action = 'status' } | ConvertTo-Json
$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8880/api/workbench' -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 45
$response.data.portfolio.target_weights | Select-Object code,name,target_weight
```

Expected: 请求成功；有效目标行显示 `name`；权重与原计划一致；服务诊断中的模式和状态仍保留原英文协议值供前端映射。

- [ ] **Step 8: 运行 Web/UI 验证**

Run:

```powershell
node scripts/web_verify.mjs
node scripts/ui_verify.mjs
```

Expected: Web 25 项与 UI 23 项均无失败；若项目验证项数量因现有代码变化而增加，以实际输出的 0 失败为准。

- [ ] **Step 9: 完成前审计**

核对：

```powershell
rg -n "research_idle|paper_guarded|no_new_position|unknown|TOP100 by amount|K-line Trend|SIMULATION ONLY|RISK FIRST|AUDITABLE" components lib README.md
rg -n "ai:portfolio:latest|target_weights|targetQuoteNames|data-realtime" server/routes/workbench.mjs README.md
```

Expected: 英文枚举只出现在映射键、条件判断、技术说明或允许保留的协议上下文；没有界面直接渲染已知内部值；名称补充链路没有写操作。

- [ ] **Step 10: 记录最终检查点**

当前无 Git 仓库，因此不提交、不建分支、不创建 PR。报告修改文件、实时 API 样例、测试计数和保留边界。
