import { execFileSync } from 'node:child_process';
import { log } from '../server/http-utils.mjs';
import { closeDbLogWriter } from '../server/db_log_writer.mjs';

const marker = `log-persistence-${Date.now()}`;

function countAuditRows() {
  const script = `
import sqlite3, json
conn = sqlite3.connect('data/quant.db')
row = conn.execute(
    "SELECT COUNT(*) FROM audit_events WHERE event_type='server_log' AND payload LIKE ?",
    ('%${marker}%',),
).fetchone()
conn.close()
print(row[0])
`;
  return Number(execFileSync('python', ['-c', script], { encoding: 'utf-8' }).trim());
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

log('TEST', marker);

let count = 0;
const deadline = Date.now() + 6000;
while (Date.now() < deadline) {
  count = countAuditRows();
  if (count >= 1) break;
  await wait(250);
}

closeDbLogWriter();
if (count < 1) {
  throw new Error(`expected server_log audit row for ${marker}`);
}

console.log('log persistence tests passed');
