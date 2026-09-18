# Financial Statements UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the financial statements tab into a decision-first professional investor view with explicit units, semantic metric groups, strong stock identity, and complete raw-data access.

**Architecture:** Keep the existing read-only financial API unchanged. Refactor `FinancialStatementsPanel.tsx` around field metadata and pure formatting helpers, then render a latest-period summary and a segmented grouped table while retaining the raw datasets below. Extend the existing Node contract test to lock the visual and formatting requirements before implementation.

**Tech Stack:** React 19, TypeScript, Vite, Lucide React, Node assertion scripts, browser-based verification.

---

### Task 1: Lock the financial formatting and layout contract

**Files:**
- Modify: `scripts/financial_statements_contract_tests.mjs`

- [ ] **Step 1: Write failing contract assertions**

Add assertions requiring the selected design vocabulary and helper APIs:

```js
assert(panel.includes('FIELD_META'), 'financial fields must use semantic metadata');
assert(panel.includes('formatFinancialValue'), 'financial values must use one formatter');
assert(panel.includes('亿元') && panel.includes('万元'), 'money must use adaptive units');
assert(panel.includes('元/股') && panel.includes('倍'), 'per-share and ratio units must be explicit');
assert(panel.includes('利润与现金流'), 'the default metric group must exist');
assert(panel.includes('盈利能力') && panel.includes('成长能力'), 'semantic metric groups must exist');
assert(panel.includes('偿债与运营') && panel.includes('其他指标'), 'all fields need a visible group');
assert(panel.includes('最新一期核心指标'), 'the latest-period summary must exist');
assert(panel.includes('aria-pressed'), 'metric group controls must expose selected state');
assert(panel.includes('position: \\'sticky\\'') && panel.includes('left: 0'), 'the period column must be sticky');
assert(!panel.includes('<DataTable rows={historyRows} />'), 'the old ungrouped history table must be removed');
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```powershell
node scripts\financial_statements_contract_tests.mjs
```

Expected: FAIL on the first missing semantic metadata or grouped-layout assertion.

- [ ] **Step 3: Keep existing API and database assertions**

Retain checks for:

```js
panel.includes("action: 'financials'")
panel.includes('new URLSearchParams')
router.includes("'financials'")
```

This ensures the UI refactor does not alter the read-only data path.

### Task 2: Implement semantic financial formatting

**Files:**
- Modify: `components/FinancialStatementsPanel.tsx`

- [ ] **Step 1: Define typed field metadata**

Create:

```ts
type FinancialValueKind = 'money' | 'percent' | 'multiple' | 'perShare' | 'text' | 'number';
type FinancialGroupKey = 'cashflow' | 'profitability' | 'growth' | 'solvency' | 'other';

interface FinancialFieldMeta {
  label: string;
  kind: FinancialValueKind;
  group: FinancialGroupKey;
}

const FIELD_META: Record<string, FinancialFieldMeta> = {
  revenue: { label: '营业收入', kind: 'money', group: 'cashflow' },
  net_profit: { label: '净利润', kind: 'money', group: 'cashflow' },
  operating_cash_flow: { label: '经营现金流', kind: 'money', group: 'cashflow' },
  roe: { label: '净资产收益率', kind: 'percent', group: 'profitability' },
  // Continue with every known field from the approved specification.
};
```

- [ ] **Step 2: Implement adaptive money formatting**

Create a pure formatter:

```ts
function formatMoney(value: number) {
  const absolute = Math.abs(value);
  const divisor = absolute >= 100_000_000 ? 100_000_000 : absolute >= 10_000 ? 10_000 : 1;
  const unit = divisor === 100_000_000 ? '亿元' : divisor === 10_000 ? '万元' : '元';
  return {
    display: `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value / divisor)} ${unit}`,
    exact: `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(value)}`,
  };
}
```

- [ ] **Step 3: Implement the unified formatter**

Create:

```ts
function formatFinancialValue(field: string, value: unknown) {
  if (value === null || value === undefined || value === '') return { display: '--', title: '暂无数据' };
  const meta = FIELD_META[field];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return { display: displayValue(value), title: displayValue(value) };
  }
  if (meta?.kind === 'money') return formatMoney(value);
  if (meta?.kind === 'percent') return { display: `${formatNumber(value, 2)}%`, title: `${value}%` };
  if (meta?.kind === 'multiple') return { display: `${formatNumber(value, 2)} 倍`, title: String(value) };
  if (meta?.kind === 'perShare') return { display: `${formatNumber(value, 2)} 元/股`, title: String(value) };
  return { display: formatNumber(value, 6), title: String(value) };
}
```

- [ ] **Step 4: Run TypeScript and contract tests**

Run:

```powershell
npx tsc --noEmit
node scripts\financial_statements_contract_tests.mjs
```

Expected: TypeScript may pass while the contract remains RED until the grouped UI is implemented.

### Task 3: Build the decision-first grouped financial view

**Files:**
- Modify: `components/FinancialStatementsPanel.tsx`

- [ ] **Step 1: Add group configuration and state**

Create a stable group list:

```ts
const FINANCIAL_GROUPS = [
  { key: 'cashflow', label: '利润与现金流' },
  { key: 'profitability', label: '盈利能力' },
  { key: 'growth', label: '成长能力' },
  { key: 'solvency', label: '偿债与运营' },
  { key: 'other', label: '其他指标' },
] as const;
```

Initialize:

```ts
const [activeGroup, setActiveGroup] = useState<FinancialGroupKey>('cashflow');
```

- [ ] **Step 2: Derive latest row and grouped columns**

Use memoized derivations:

```ts
const latestRow = historyRows[0] || null;
const knownIdentityFields = new Set(['report_date', 'period', 'code', 'name']);
const groupedColumns = useMemo(
  () => collectColumns(historyRows).filter(field => {
    if (knownIdentityFields.has(field)) return false;
    return (FIELD_META[field]?.group || 'other') === activeGroup;
  }),
  [activeGroup, historyRows],
);
```

- [ ] **Step 3: Render stock identity and latest summary**

Render the stock name as the primary heading, followed by code, inferred exchange, latest period, dataset count, and history count. Render six summary metrics from `latestRow` with explicit units and no invented industry value.

- [ ] **Step 4: Render accessible segmented controls**

Use buttons:

```tsx
<button
  type="button"
  aria-pressed={activeGroup === group.key}
  onClick={() => setActiveGroup(group.key)}
>
  {group.label}
</button>
```

Keep target height at least 38px, visible focus styling, yellow selected state, and neutral inactive state.

- [ ] **Step 5: Replace the ungrouped history table**

Render a group-specific table with:

- sticky report-period column on the left;
- sticky header row;
- no repeated code or name columns;
- semantic formatted values and exact-value tooltips;
- growth colors only for `revenue_growth` and `profit_growth`;
- horizontal scrolling inside the table container;
- empty message when a selected group has no fields.

- [ ] **Step 6: Simplify raw datasets**

Change each `RawDataset` to default closed:

```tsx
<details style={...}>
```

Keep all non-abstract database keys and nested paths available.

- [ ] **Step 7: Verify GREEN**

Run:

```powershell
node scripts\financial_statements_contract_tests.mjs
npx tsc --noEmit
```

Expected: both commands exit `0`.

### Task 4: Regression and rendered verification

**Files:**
- Test: `tests/test_data_financials.py`
- Test: `scripts/financial_statements_contract_tests.mjs`
- Verify: `components/FinancialStatementsPanel.tsx`

- [ ] **Step 1: Run backend and frontend regression tests**

```powershell
python -m pytest tests\test_data_financials.py tests\test_source_health.py tests\test_jin10_mcp.py -q
node scripts\financial_statements_contract_tests.mjs
npx tsc --noEmit
npm run build
```

Expected: all tests pass; TypeScript and Vite exit `0`. Record any existing bundle-size warning separately.

- [ ] **Step 2: Verify live data in the browser**

Open the existing local app, navigate to:

```text
市场数据 -> 财务报表
```

Query `SH600519` and verify:

- input normalizes to `600519`;
- name is `贵州茅台`;
- latest period and dataset counts match the API;
- money values display adaptive units;
- percentage, multiple, and per-share values display correct suffixes;
- all five metric groups switch correctly;
- raw datasets remain available and default closed;
- no console errors or warnings.

- [ ] **Step 3: Verify responsive layouts**

Check widths `1440`, `1280`, `768`, and `375`:

- the page body has no unintended horizontal overflow;
- summary metrics resolve to six, three, or two columns;
- the table scrolls inside its own container;
- the period column remains visible;
- controls wrap without overlapping.

- [ ] **Step 4: Update documentation status**

Confirm the approved design document remains:

```markdown
状态：已确认
```

No README update is required because the query behavior and API contract are unchanged.
