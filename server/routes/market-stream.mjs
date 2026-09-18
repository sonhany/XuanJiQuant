import crypto from 'node:crypto';

import { ALLOWED_ORIGINS } from '../config.mjs';
import { marketStreamService } from '../market-stream-service.mjs';
import { syncPolicy } from '../sync-policy.mjs';

const CHANNELS = new Set(['hot_quotes', 'market_top100', 'cockpit_mark']);

export function parseStreamRequest(rawUrl) {
  const url = new URL(rawUrl, 'http://localhost');
  const codes = [...new Set(
    String(url.searchParams.get('codes') || '').split(',')
      .map(value => value.trim().replace(/^(sh|sz|bj)/i, '').replace(/\.(SH|SZ|BJ)$/i, ''))
      .filter(value => /^\d{6}$/.test(value)),
  )].slice(0, 200);
  const channels = [...new Set(
    String(url.searchParams.get('channels') || 'hot_quotes').split(',')
      .map(value => value.trim()).filter(value => CHANNELS.has(value)),
  )];
  return { codes, channels: channels.length ? channels : ['hot_quotes'] };
}

export function isAllowedStreamRequest(req) {
  const address = String(req?.socket?.remoteAddress || '');
  const local = ['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(address);
  const origin = req?.headers?.origin;
  return local && (!origin || ALLOWED_ORIGINS.includes(origin));
}

export function formatSseEvent(event) {
  return `id: ${event.id}\nevent: ${event.type}\ndata: ${JSON.stringify(event.data)}\n\n`;
}

export function handleMarketStream(req, res, service = marketStreamService) {
  if (!isAllowedStreamRequest(req)) {
    res.statusCode = 403;
    res.end('Forbidden');
    return;
  }
  const { codes, channels } = parseStreamRequest(req.url);
  res.statusCode = 200;
  res.setHeader('Content-Type', 'text/event-stream; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');
  res.flushHeaders?.();
  const clientId = crypto.randomUUID();
  const unsubscribe = service.subscribe(clientId, codes, channels, event => res.write(formatSseEvent(event)));
  let heartbeatId = 0;
  const heartbeat = setInterval(() => {
    heartbeatId += 1;
    res.write(formatSseEvent({ id: `heartbeat-${heartbeatId}`, type: 'heartbeat', data: { at: new Date().toISOString() } }));
  }, syncPolicy('system_health').background_interval_ms / 2);
  heartbeat.unref?.();
  const close = () => {
    clearInterval(heartbeat);
    unsubscribe();
  };
  req.once('close', close);
  req.once('aborted', close);
}
