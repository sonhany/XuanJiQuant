import assert from 'node:assert/strict';
import fs from 'node:fs';

const index = fs.readFileSync('index.html', 'utf8');
const valuation = fs.readFileSync('components/ValuationPanel.tsx', 'utf8');

assert(!index.includes('AI 自主决策'), 'retired Agent identity must not remain in page metadata');
assert(!valuation.includes('AI 自主调度'), 'independent LLM valuation must not be described as Agent scheduling');

console.log('retired Agent copy contracts passed');
