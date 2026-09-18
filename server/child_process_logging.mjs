import { log } from './http-utils.mjs';

export function classifyChildStderr(chunk) {
  const message = String(chunk || '').trim();
  if (/\b(?:ERROR|CRITICAL|FATAL|EXCEPTION)\b|Traceback/i.test(message)) return 'ERROR';
  if (/\bWARN(?:ING)?\b/i.test(message)) return 'WARN';
  return 'INFO';
}

export function logChildStderr(component, chunk, limit = 500) {
  const message = String(chunk || '').trim();
  if (!message) return;
  log(classifyChildStderr(message), `[${component}] stderr: ${message.slice(0, limit)}`);
}
