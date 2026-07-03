const fs = require('node:fs');
const path = require('node:path');

const COUNTER_FILE = path.join(__dirname, '..', 'logs', 'loop_test', 'run_counter.txt');
const MAX_RUNS = 24;

try {
  let count = parseInt(fs.readFileSync(COUNTER_FILE, 'utf-8').trim(), 10) || 0;
  count += 1;
  fs.writeFileSync(COUNTER_FILE, String(count));
  process.stdout.write(`hourly_loop_test run #${count}/${MAX_RUNS}\n`);
} catch {
  fs.mkdirSync(path.dirname(COUNTER_FILE), { recursive: true });
  fs.writeFileSync(COUNTER_FILE, '1');
  process.stdout.write('hourly_loop_test run #1/24\n');
}