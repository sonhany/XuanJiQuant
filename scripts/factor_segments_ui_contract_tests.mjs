import assert from 'node:assert/strict';
import fs from 'node:fs';

const src = fs.readFileSync('components/FactorPanel.tsx', 'utf8');

assert(src.includes("action: 'evaluate_segments'"), 'FactorPanel should call factor evaluate_segments API');
assert(src.includes('Qlib 分段稳定性'), 'FactorPanel should render qlib-style segmented stability section');
assert(src.includes('训练集') && src.includes('验证集') && src.includes('测试集'), 'Segment labels should be displayed in Chinese');
assert(src.includes('segmentResult'), 'FactorPanel should keep segmented factor metrics in state');

console.log('factor segments UI contract tests passed');
