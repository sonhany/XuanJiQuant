import fs from 'node:fs';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

const config = fs.readFileSync('server/config.mjs', 'utf-8');
const httpUtils = fs.readFileSync('server/http-utils.mjs', 'utf-8');

assert(config.includes("export const LOG_DIR = path.join(ROOT_DIR, 'logs');"), 'server config must define logs directory');
assert(!config.includes("path.join(ROOT_DIR, 'server.log')"), 'server log must not write to root server.log');
assert(httpUtils.includes('function currentLogFile()'), 'http utils must compute current daily log file');
assert(httpUtils.includes("server-${day}.log"), 'daily server log file should include YYYYMMDD date');
assert(httpUtils.includes('XUANJI_LOG_RETENTION_DAYS'), 'server logs must have configurable retention');
assert(httpUtils.includes('pruneOldLogs();'), 'old server logs must be pruned at startup');
assert(
  httpUtils.includes("const STDERR_LEVELS = new Set(['WARN', 'ERROR', 'FATAL']);") &&
    httpUtils.includes('STDERR_LEVELS.has(String(level).toUpperCase())'),
  'routine request/info logs must use stdout while warnings and errors use stderr',
);

console.log('log rotation contract tests passed');
