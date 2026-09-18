import fs from 'node:fs';
import assert from 'node:assert/strict';
import ts from 'typescript';
import { composeWorkbenchStatus } from '../server/routes/workbench.mjs';

const dashboardPath = 'components/DashboardPanel.tsx';
const dashboard = fs.readFileSync(dashboardPath, 'utf8');
const workbench = fs.readFileSync('server/routes/workbench.mjs', 'utf8');

for (const contract of [
  'const sentiment = data?.sentiment;',
  "typeof rawSentimentScore === 'number' && Number.isFinite(rawSentimentScore)",
  'Math.max(0, Math.min(100, rawSentimentScore))',
  "typeof rawSentimentConfidence === 'number' && Number.isFinite(rawSentimentConfidence)",
  'Math.max(0, Math.min(1, rawSentimentConfidence))',
  "source?.official === true",
  "source?.status === 'live'",
  "source?.status === 'stale'",
  'sentiment-block',
]) {
  assert(dashboard.includes(contract), `dashboard sentiment contract missing ${contract}`);
}

for (const label of [
  '市场情绪',
  '情绪置信度',
  '官方来源',
  '暂无可用数据',
  '极度谨慎',
  '谨慎',
  '中性',
  '积极',
  '过热',
  '部分官方数据已过期，当前展示包含缓存值',
]) {
  assert(dashboard.includes(label), `dashboard must display ${label}`);
}

assert(workbench.includes("{ action: 'global_context_status' }"), 'workbench must read cached global context');
assert(workbench.includes('sentiment: normalizedSentiment(input.globalContext)'), 'workbench must expose bounded sentiment');

const composed = composeWorkbenchStatus({
  globalContext: {
    sentiment: {
      sentiment_score: 140,
      sentiment_regime: 'invalid',
      confidence: 2,
      sources: [
        { source: 'cboe', status: 'live' },
        { source: 'fred', status: 'stale' },
        { source: 'bad', status: 'unavailable' },
      ],
    },
  },
  errors: {},
});
assert.equal(composed.sentiment.sentiment_score, 100);
assert.equal(composed.sentiment.sentiment_regime, 'extreme_greed');
assert.equal(composed.sentiment.confidence, 1);
assert.equal(composed.sentiment.stale, true);
assert.deepEqual(composed.sentiment.sources, [
  { source: 'cboe', status: 'live', official: true },
  { source: 'fred', status: 'stale', official: true },
]);

const forbiddenFields = new Set([
  'trade_policy',
  'trade_allowed',
  'can_change_trade_policy',
  'can_trigger_order',
]);
const sourceFile = ts.createSourceFile(
  dashboardPath,
  dashboard,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);
const forbiddenAccesses = [];
const visit = (node) => {
  if (
    ts.isPropertyAccessExpression(node)
    && ts.isIdentifier(node.expression)
    && node.expression.text === 'sentiment'
    && forbiddenFields.has(node.name.text)
  ) {
    forbiddenAccesses.push(node.getText(sourceFile));
  }
  if (
    ts.isElementAccessExpression(node)
    && ts.isIdentifier(node.expression)
    && node.expression.text === 'sentiment'
    && ts.isStringLiteral(node.argumentExpression)
    && forbiddenFields.has(node.argumentExpression.text)
  ) {
    forbiddenAccesses.push(node.getText(sourceFile));
  }
  ts.forEachChild(node, visit);
};
visit(sourceFile);
assert.deepEqual(forbiddenAccesses, [], 'sentiment must never control execution permission');

console.log('market sentiment frontend contract tests passed');
