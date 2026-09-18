import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scriptsDir = path.join(root, 'scripts');
const files = fs.readdirSync(scriptsDir)
  .filter(name => name.endsWith('_contract_tests.mjs'))
  .sort();

let passed = 0;
const failed = [];
for (const name of files) {
  console.log(`\n[contract] ${name}`);
  const result = spawnSync(process.execPath, [path.join(scriptsDir, name)], {
    cwd: root,
    stdio: 'inherit',
    windowsHide: true,
  });
  if (result.status === 0) passed += 1;
  else failed.push(name);
}

console.log(`\n[contract] summary: ${passed}/${files.length} files passed`);
if (failed.length) {
  console.error(`[contract] failed: ${failed.join(', ')}`);
  process.exitCode = 1;
}
