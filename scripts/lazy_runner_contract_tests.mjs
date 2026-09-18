import fs from 'node:fs';
import assert from 'node:assert/strict';

const routeFiles = [
  'server/routes/alerts.mjs',
  'server/routes/data.mjs',
  'server/routes/execution.mjs',
  'server/routes/factor.mjs',
  'server/routes/jin10.mjs',
  'server/routes/market.mjs',
  'server/routes/paper.mjs',
  'server/routes/risk.mjs',
  'server/routes/strategy.mjs',
];

for (const file of routeFiles) {
  const src = fs.readFileSync(file, 'utf8');
  const firstExport = src.indexOf('export async function');
  assert(firstExport > 0, `${file} should expose an async route handler`);
  const topLevel = src.slice(0, firstExport);
  assert(
    !topLevel.includes('runner.ensure();'),
    `${file} should not eagerly start its Python runner at module import`,
  );
}

console.log('lazy runner contract tests passed');
