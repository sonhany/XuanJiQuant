import assert from 'assert';
import fs from 'fs';

const runner = fs.readFileSync('scripts/jin10_runner.py', 'utf-8');
const router = fs.readFileSync('server/router.mjs', 'utf-8');
const panel = fs.readFileSync('components/Jin10DataPanel.tsx', 'utf-8');

assert(runner.includes('"interpret_flash"'), 'jin10_runner must allow interpret_flash action');
assert(runner.includes('chat_json'), 'interpret_flash must use existing LLM client');
assert(runner.includes('paper:config'), 'interpret_flash must select provider from existing paper config');
assert(runner.includes('write_audit_event'), 'interpret_flash must write an audit event');
const readOnlyBlock = router.match(/const READ_ONLY_ACTIONS = \{([\s\S]*?)\n\};/)?.[1] || '';
assert(!readOnlyBlock.includes("'interpret_flash'"), 'interpret_flash must require control authorization');

assert(panel.includes('onContextMenu'), 'flash rows must support right-click context menu');
assert(panel.includes('data-jin10-context-menu'), 'context menu must have a stable marker');
assert(panel.includes('data-jin10-ai-modal'), 'AI interpretation modal must have a stable marker');
assert(panel.includes("action: 'interpret_flash'") || panel.includes('action: "interpret_flash"'), 'frontend must call interpret_flash');
assert(panel.includes('AI 解读'), 'UI must expose AI 解读 action');
assert(panel.includes('影子信号') || panel.includes('不直接触发交易'), 'UI must show safety boundary');

console.log('jin10 ai interpret contract tests passed');
