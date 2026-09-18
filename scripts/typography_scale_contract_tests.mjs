import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const componentDir = 'components';
const componentFiles = fs
  .readdirSync(componentDir)
  .filter((name) => name.endsWith('.tsx'))
  .map((name) => path.join(componentDir, name));

const sources = new Map(
  componentFiles.map((file) => [file, fs.readFileSync(file, 'utf8')]),
);

const shell = sources.get(path.join(componentDir, 'AppShell.tsx'));
const dashboard = sources.get(path.join(componentDir, 'DashboardPanel.tsx'));
const execution = sources.get(path.join(componentDir, 'ExecutionPanel.tsx'));
const risk = sources.get(path.join(componentDir, 'RiskPanel.tsx'));
const alerts = sources.get(path.join(componentDir, 'AlertPanel.tsx'));

for (const token of [
  '--font-page-title: 20px',
  '--font-page-title-mobile: 18px',
  '--font-kpi: 24px',
  '--font-kpi-mobile: 22px',
  '--font-section: 14px',
  '--font-body: 13px',
  '--font-meta: 12px',
]) {
  assert(shell.includes(token), `shared shell must define typography token ${token}`);
}

const undersized = [];
for (const [file, source] of sources) {
  for (const pattern of [
    /font-size:\s*(\d+)px/g,
    /fontSize:\s*(\d+)/g,
  ]) {
    for (const match of source.matchAll(pattern)) {
      const size = Number(match[1]);
      if (size < 11) undersized.push(`${file}:${size}px`);
    }
  }
}

assert.deepEqual(
  undersized,
  [],
  'business-facing component text must not render below 11px',
);

assert(
  dashboard.includes('var(--font-page-title)') &&
    dashboard.includes('var(--font-kpi)') &&
    dashboard.includes('var(--font-kpi-mobile)'),
  'dashboard must use the shared title and KPI typography scale',
);
assert(
  /\.cockpit-button\s*\{[^}]*min-width:\s*92px/.test(dashboard) &&
    /\.cockpit-button\s*\{[^}]*white-space:\s*nowrap/.test(dashboard),
  'dashboard actions must remain single-line after the typography increase',
);

for (const [name, source] of [
  ['execution', execution],
  ['risk', risk],
  ['alerts', alerts],
]) {
  assert(
    source.includes('var(--font-page-title)') &&
      source.includes('var(--font-section)') &&
      source.includes('var(--font-body)') &&
      source.includes('var(--font-meta)'),
    `${name} must use the shared typography scale`,
  );
}
for (const [name, source, selector] of [
  ['execution', execution, 'f5-refresh'],
  ['risk', risk, 'risk-refresh'],
  ['alerts', alerts, 'alert-refresh'],
]) {
  assert(
    new RegExp(`\\.${selector}\\s*\\{[^}]*white-space:\\s*nowrap`).test(source),
    `${name} refresh action must remain single-line on narrow screens`,
  );
}

console.log('typography scale contract tests passed');
