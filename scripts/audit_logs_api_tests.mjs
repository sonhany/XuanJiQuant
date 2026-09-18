import { spawn } from 'node:child_process';
import { log } from '../server/http-utils.mjs';
import { closeDbLogWriter } from '../server/db_log_writer.mjs';

const marker = `audit-logs-api-${Date.now()}`;

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function requestRiskRunner(payload) {
  const child = spawn('python', ['scripts/risk_runner.py'], {
    cwd: process.cwd(),
    stdio: ['pipe', 'pipe', 'pipe'],
  });

  let stdout = '';
  let stderr = '';
  child.stdout.on('data', (chunk) => {
    stdout += chunk.toString('utf8');
  });
  child.stderr.on('data', (chunk) => {
    stderr += chunk.toString('utf8');
  });

  child.stdin.write(`${JSON.stringify(payload)}\n`);
  const deadline = Date.now() + 5000;
  while (!stdout.includes('\n') && Date.now() < deadline) {
    await wait(50);
  }
  child.kill();

  const line = stdout.trim().split(/\r?\n/).filter(Boolean).at(-1);
  if (!line) {
    throw new Error(`risk_runner produced no JSON output. stderr=${stderr}`);
  }
  return JSON.parse(line);
}

try {
  log('TEST', marker);
  await wait(1500);

  const response = await requestRiskRunner({ action: 'audit_logs', limit: 20 });
  if (!response.success) {
    throw new Error(`audit_logs action failed: ${response.error || JSON.stringify(response)}`);
  }

  const rows = Array.isArray(response.data) ? response.data : [];
  const found = rows.some((row) => row.event_type === 'server_log'
    && JSON.stringify(row.payload || {}).includes(marker));
  if (!found) {
    throw new Error(`expected audit_logs to return server_log marker ${marker}; got ${JSON.stringify(rows).slice(0, 1000)}`);
  }

  console.log('audit logs api tests passed');
} finally {
  closeDbLogWriter();
}
