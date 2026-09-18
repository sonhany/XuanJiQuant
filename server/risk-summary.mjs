export function riskLevel(risk, alerts) {
  if (!risk) return 'unknown';
  if (Number(alerts?.business_critical_active || 0) > 0
      || Number(risk.max_drawdown_pct || 0) <= -10
      || Number(risk.volatility_pct || 0) >= 40
      || Number(risk.concentration_pct || 0) >= 65) return 'high';
  if (Number(alerts?.business_active || 0) > 0
      || Number(risk.max_drawdown_pct || 0) <= -5
      || Number(risk.volatility_pct || 0) >= 25
      || Number(risk.concentration_pct || 0) >= 45) return 'medium';
  return 'low';
}

export function overallRisk(risk, alerts) {
  const level = riskLevel(risk, alerts);
  return {
    level,
    state: level === 'unknown' ? 'unknown' : 'ready',
    source: 'deterministic_risk_summary',
  };
}
