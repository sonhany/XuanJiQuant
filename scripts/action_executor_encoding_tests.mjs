import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const source = fs.readFileSync('scripts/ai_action_executor.py', 'utf-8');

assert(
  source.includes('encoding="utf-8"') && source.includes('errors="replace"'),
  'action executor subprocess output must decode as utf-8 with replacement on Windows',
);

console.log('action executor encoding tests passed');
