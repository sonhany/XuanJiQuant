export function normalizePerformanceSeries(points = [], initialEquity = null) {
  const valid = (Array.isArray(points) ? points : []).map((point) => {
    if (!point?.date || point?.equity === null || point?.equity === undefined) return null;
    const equity = Number(point.equity);
    if (!Number.isFinite(equity) || equity <= 0) return null;
    const suppliedDrawdown = Number(point.drawdown_pct ?? point.drawdownPct);
    return { date: String(point.date), equity, suppliedDrawdown: Number.isFinite(suppliedDrawdown) ? suppliedDrawdown : null };
  }).filter(Boolean);
  if (!valid.length) return [];
  const requested = Number(initialEquity);
  const baseline = Number.isFinite(requested) && requested > 0 ? requested : valid[0].equity;
  let peak = 0;
  return valid.map((point) => {
    peak = Math.max(peak, point.equity);
    const computed = peak > 0 ? ((point.equity - peak) / peak) * 100 : 0;
    return { date: point.date, equity: point.equity, nav: Number((point.equity / baseline).toFixed(6)), drawdownPct: Number((point.suppliedDrawdown ?? computed).toFixed(4)) };
  });
}

export function formatOptionalPercent(value, digits = 2) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '--';
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(digits)}%`;
}

export function takeVisibleRows(rows = [], visibleCount = 0) {
  if (!Array.isArray(rows)) return [];
  return rows.slice(0, Math.max(0, Math.floor(Number(visibleCount) || 0)));
}

export function nextVisibleCount(current, total, step = 40) {
  const safeCurrent = Math.max(0, Math.floor(Number(current) || 0));
  const safeTotal = Math.max(0, Math.floor(Number(total) || 0));
  const safeStep = Math.max(1, Math.floor(Number(step) || 1));
  return Math.min(safeTotal, safeCurrent + safeStep);
}

export function heartbeatAgeSeconds(heartbeat, now = Date.now()) {
  const heartbeatMs = Date.parse(String(heartbeat || ''));
  const nowMs = typeof now === 'number' ? now : Date.parse(String(now || ''));
  if (!Number.isFinite(heartbeatMs) || !Number.isFinite(nowMs)) return null;
  return Math.max(0, Math.min(86_400, Math.floor((nowMs - heartbeatMs) / 1000)));
}
