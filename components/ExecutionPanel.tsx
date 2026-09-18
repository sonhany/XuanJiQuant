import React, { useCallback, useEffect, useState } from 'react';
import { ClipboardCheck, RefreshCw, ShieldCheck, Zap } from 'lucide-react';
import { apiHeaders, executionStatusLabel, f5ReasonLabel, f5RunStatusLabel } from '../lib/workbench-state.mjs';
import { AsyncState, StatusBadge } from './WorkbenchStatus';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';

async function f5Api(action: string, extra: Record<string, unknown> = {}) {
  const response = await fetch(`${API_BASE}/api/paper-execution`, {
    method: 'POST', headers: apiHeaders(), body: JSON.stringify({ action, ...extra }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data ?? payload;
}

const text = (value: unknown) => value === null || value === undefined || value === '' ? '--' : String(value);
const number = (value: unknown, digits = 2) => Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: digits });
const money = (value: unknown) => `¥${number(value, 2)}`;
const signedMoney = (value: unknown) => {
  const amount = Number(value || 0);
  return `${amount > 0 ? '+' : amount < 0 ? '-' : ''}${money(Math.abs(amount))}`;
};
const percent = (value: unknown) => {
  const amount = Number(value || 0);
  return `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%`;
};
const pnlColor = (value: unknown) => Number(value || 0) > 0 ? '#f87171' : Number(value || 0) < 0 ? '#4ade80' : '#cbd5e1';
const formatTime = (value: unknown) => {
  const parsed = new Date(String(value || ''));
  return Number.isNaN(parsed.getTime()) ? '--' : parsed.toLocaleString('zh-CN', { hour12: false });
};

const ExecutionPanel: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [status, runs, orders, fills, reconciliations, accountProjection] = await Promise.all([
        f5Api('status'), f5Api('runs'), f5Api('orders'), f5Api('fills'), f5Api('reconciliations'), f5Api('account'),
      ]);
      setData({ status, runs, orders, fills, reconciliations, accountProjection });
      setError('');
    } catch (reason: any) {
      setError(reason?.message || 'F5 模拟执行账本读取失败');
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  const latest = data?.status?.latest_run || data?.runs?.[0] || {};
  const accountProjection = data?.accountProjection || {};
  const orders = Array.isArray(accountProjection.orders) ? accountProjection.orders : Array.isArray(data?.orders) ? data.orders : [];
  const fills = Array.isArray(accountProjection.trades) ? accountProjection.trades : Array.isArray(data?.fills) ? data.fills : [];
  const checks = Array.isArray(data?.reconciliations) ? data.reconciliations : [];
  const latestRunId = String(latest.run_id || '');
  const latestRunOrders = orders
    .filter((row: any) => String(row.run_id || '') === latestRunId)
    .sort((left: any, right: any) => String(right.updated_at || right.created_at || '').localeCompare(String(left.updated_at || left.created_at || '')));
  const latestRunFills = fills
    .filter((row: any) => String(row.run_id || '') === latestRunId)
    .sort((left: any, right: any) => String(right.created_at || '').localeCompare(String(left.created_at || '')));
  const latestRunChecks = checks
    .filter((row: any) => String(row.run_id || '') === latestRunId)
    .sort((left: any, right: any) => String(left.check_name || '').localeCompare(String(right.check_name || '')));
  const account = accountProjection.account || {};
  const positions = Array.isArray(accountProjection.positions) ? accountProjection.positions : [];
  const reason = latest.reason_code || data?.status?.reason_code;
  const isBlocked = latest.status === 'blocked' || latest.status === 'halted_unknown';
  const lane = latest.execution_lane || data?.status?.execution_lane;
  const quality = latest.strategy_quality_status || data?.status?.strategy_quality_status;
  const laneLabel = lane === 'experimental_paper' ? '实验模拟自动交易' : lane === 'validated_paper' ? '验证通过模拟' : '未获得模拟许可';
  const qualityLabel = quality === 'unqualified' ? '策略质量：未通过F4' : quality === 'validated' ? '策略质量：已通过F4研究门禁' : '策略质量：未知';
  const modeLabel = data?.status?.execution_mode === 'paper_intraday' ? '盘中实验模拟' : '日频次日模拟';

  return <div className="f5-execution">
    <style>{`
      .f5-execution{display:flex;flex-direction:column;gap:14px;font-size:var(--font-body)}.f5-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.f5-title{display:flex;gap:10px;min-width:0}.f5-title svg{width:18px;color:#38bdf8;flex:none}.f5-title h1{margin:0;color:#f8fafc;font-size:var(--font-page-title)}.f5-title p{margin:5px 0 0;color:#64748b;line-height:1.6;font-size:var(--font-body)}.f5-refresh{height:36px;display:flex;align-items:center;gap:6px;padding:0 12px;border:1px solid #334155;border-radius:6px;color:#cbd5e1;background:#111827;cursor:pointer;white-space:nowrap}.f5-banner{padding:12px 14px;border:1px solid #334155;border-inline-start:3px solid #38bdf8;border-radius:6px;color:#bae6fd;background:#0d1422;line-height:1.65;overflow-wrap:anywhere}.f5-banner.blocked{border-inline-start-color:#f59e0b;color:#fde68a}.f5-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;border:1px solid #1e293b;background:#1e293b}.f5-metric{min-width:0;padding:12px;background:#101827}.f5-metric span,.f5-metric strong{display:block;overflow-wrap:anywhere}.f5-metric span{color:#64748b;font-size:var(--font-meta)}.f5-metric strong{margin-top:7px;color:#e2e8f0;font:700 var(--font-meta) "JetBrains Mono",monospace}.f5-card{border:1px solid #1e293b;border-radius:8px;background:#111827;overflow:hidden}.f5-card-head{min-height:43px;display:flex;align-items:center;gap:8px;padding:0 13px;border-bottom:1px solid #1e293b;background:#0d1422}.f5-card-head strong{color:#cbd5e1;font-size:var(--font-section)}.f5-card-head span{margin-inline-start:auto;color:#64748b;font-size:var(--font-meta)}.f5-table-wrap{overflow:auto}.f5-table{width:100%;min-width:860px;border-collapse:collapse}.f5-position-table{min-width:1420px}.f5-table th,.f5-table td{padding:10px 11px;border-bottom:1px solid #1e293b;text-align:left;color:#94a3b8;font-size:var(--font-body);font-variant-numeric:tabular-nums;white-space:nowrap}.f5-position-table th:first-child,.f5-position-table td:first-child{position:sticky;left:0;background:#111827;z-index:1}.f5-security-name{display:block;color:#e2e8f0;font-weight:650}.f5-security-code{display:block;margin-top:3px;color:#64748b;font-family:Consolas,monospace}.f5-table th{color:#64748b}.f5-empty{padding:24px;text-align:center;color:#64748b}@media(max-width:760px){.f5-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.f5-head{align-items:flex-start}}
    `}</style>
    <header className="f5-head"><div className="f5-title"><Zap/><div><h1>F5 确定性模拟执行</h1><p>{data?.status?.execution_mode === 'paper_intraday' ? '盘中实时行情模拟' : '日频次日开盘模拟'} · 独立账本 · 全量对账 · 永无实盘权限</p></div></div><button className="f5-refresh" type="button" onClick={refresh} disabled={loading}><RefreshCw size={14}/>刷新</button></header>
    {error ? <AsyncState state="error" message={error} compact/> : null}
    {loading && !data ? <AsyncState state="loading"/> : null}
    {data ? <>
      <div className={`f5-banner ${isBlocked ? 'blocked' : ''}`}><strong>{laneLabel}</strong> · {qualityLabel} · 准入原因：{f5ReasonLabel(reason)}。F5 仅消费受治理的验证组合或实验组合，不允许页面提交证券、方向、数量或价格。</div>
      <div className="f5-grid">
        <div className="f5-metric"><span>本轮运行状态</span><strong>{f5RunStatusLabel(latest.status)}</strong></div>
        <div className="f5-metric"><span>本轮订单</span><strong>{latestRunOrders.length}</strong></div>
        <div className="f5-metric"><span>本轮成交</span><strong>{latestRunFills.length}</strong></div>
        <div className="f5-metric"><span>当前持仓</span><strong>{positions.length}</strong></div>
        <div className="f5-metric"><span>当前权益</span><strong>{money(account.total_equity)}</strong></div>
        <div className="f5-metric"><span>可用现金</span><strong>{money(account.cash)}</strong></div>
        <div className="f5-metric"><span>持仓市值</span><strong>{money(account.market_value)}</strong></div>
        <div className="f5-metric"><span>当日盈亏</span><strong style={{color:pnlColor(account.daily_pnl)}}>{signedMoney(account.daily_pnl)}</strong></div>
        <div className="f5-metric"><span>累计盈亏</span><strong style={{color:pnlColor(account.total_pnl)}}>{signedMoney(account.total_pnl)}</strong></div>
        <div className="f5-metric"><span>累计收益率</span><strong style={{color:pnlColor(account.total_pnl_pct)}}>{percent(account.total_pnl_pct)}</strong></div>
        <div className="f5-metric"><span>持仓浮动盈亏</span><strong style={{color:pnlColor(account.unrealized_pnl)}}>{signedMoney(account.unrealized_pnl)}</strong></div>
        <div className="f5-metric"><span>已实现盈亏</span><strong style={{color:pnlColor(account.realized_pnl)}}>{signedMoney(account.realized_pnl)}</strong></div>
        <div className="f5-metric"><span>组合 ID</span><strong title={text(latest.portfolio_id)}>{text(latest.portfolio_id).slice(0, 16)}</strong></div>
        <div className="f5-metric"><span>验证 ID</span><strong title={text(latest.validation_id)}>{text(latest.validation_id).slice(0, 16)}</strong></div>
        <div className="f5-metric"><span>目标交易日</span><strong>{text(latest.intended_session)}</strong></div>
        <div className="f5-metric"><span>熔断开关</span><strong>{data.status.kill_switch ? '已打开' : '未打开'}</strong></div>
        <div className="f5-metric"><span>执行通道</span><strong>{laneLabel}</strong></div>
        <div className="f5-metric"><span>策略质量</span><strong>{qualityLabel.replace('策略质量：','')}</strong></div>
        <div className="f5-metric"><span>模拟执行许可</span><strong>{data.status.paper_execution_authority ? '已授权' : '未授权'}</strong></div>
        <div className="f5-metric"><span>实盘权限</span><strong>实盘权限：未启用</strong></div>
        <div className="f5-metric"><span>执行模式</span><strong>{modeLabel}</strong></div>
        <div className="f5-metric"><span>实时行情时间</span><strong>{text(data.status.market_fact_timestamp)}</strong></div>
      </div>
      <section className="f5-card"><div className="f5-card-head"><ShieldCheck size={14} color="#fbbf24"/><strong>当前持仓管理（只读）</strong><span>{positions.length} 只 · 权益 {money(account.total_equity)} · 可用现金 {money(account.cash)}</span></div><div className="f5-table-wrap"><table className="f5-table f5-position-table"><thead><tr><th>股票名称 / 代码</th><th>数量</th><th>可卖</th><th>当日买入</th><th>成本价</th><th>现价</th><th>成本金额</th><th>市值</th><th>浮动盈亏</th><th>盈亏率</th><th>已实现盈亏</th><th>仓位占比</th><th>更新时间</th></tr></thead><tbody>{positions.map((row:any)=><tr key={row.code}><td><span className="f5-security-name">{row.name||'名称待补'}</span><span className="f5-security-code">{row.code}</span></td><td>{number(row.quantity,0)}</td><td>{number(row.available_qty,0)}</td><td>{number(row.today_buy_qty,0)}</td><td>{number(row.avg_price,4)}</td><td>{number(row.current_price,4)}</td><td>{money(row.cost_value)}</td><td>{money(row.market_value)}</td><td style={{color:pnlColor(row.unrealized_pnl)}}>{signedMoney(row.unrealized_pnl)}</td><td style={{color:pnlColor(row.unrealized_pnl_pct)}}>{percent(row.unrealized_pnl_pct)}</td><td style={{color:pnlColor(row.realized_pnl)}}>{signedMoney(row.realized_pnl)}</td><td>{percent(row.position_weight_pct)}</td><td>{formatTime(row.updated_at)}</td></tr>)}</tbody></table>{positions.length===0?<div className="f5-empty">当前没有模拟持仓。</div>:null}</div></section>
      <section className="f5-card"><div className="f5-card-head"><ShieldCheck size={14} color="#38bdf8"/><strong>本轮模拟订单</strong><span>{latestRunOrders.length} 条 · 历史共 {orders.length} 条</span></div><div className="f5-table-wrap"><table className="f5-table"><thead><tr><th>股票名称 / 代码</th><th>方向</th><th>委托</th><th>成交</th><th>取消</th><th>成交价</th><th>状态</th><th>拒绝原因</th><th>记录时间</th></tr></thead><tbody>{latestRunOrders.map((row:any)=><tr key={row.order_id}><td><span className="f5-security-name">{row.name||'名称待补'}</span><span className="f5-security-code">{row.code}</span></td><td>{row.direction==='buy'?'买入':'卖出'}</td><td>{row.quantity}</td><td>{row.filled_qty}</td><td>{row.cancelled_qty}</td><td>{row.filled_price ? number(row.filled_price,4) : '--'}</td><td><StatusBadge label={executionStatusLabel(row.status)} tone={row.status==='filled'?'ok':row.status==='rejected'?'error':'neutral'}/></td><td>{f5ReasonLabel(row.reject_reason)}</td><td>{formatTime(row.updated_at || row.created_at)}</td></tr>)}</tbody></table>{latestRunOrders.length===0?<div className="f5-empty">本轮没有模拟订单；请查看准入原因和目标交易日。</div>:null}</div></section>
      <section className="f5-card"><div className="f5-card-head"><ClipboardCheck size={14} color="#34d399"/><strong>本轮模拟成交与对账结果</strong><span>{latestRunFills.length} 笔成交 · {latestRunChecks.filter((row:any)=>Number(row.passed)===1).length}/{latestRunChecks.length} 项通过</span></div><div className="f5-table-wrap"><table className="f5-table"><thead><tr><th>股票名称 / 代码 / 检查项</th><th>成交 ID</th><th>方向</th><th>数量</th><th>价格</th><th>手续费</th><th>结果</th></tr></thead><tbody>{latestRunFills.map((row:any)=><tr key={row.fill_id}><td><span className="f5-security-name">{row.name||'名称待补'}</span><span className="f5-security-code">{row.code}</span></td><td>{text(row.fill_id).slice(0,18)}</td><td>{row.direction==='buy'?'买入':'卖出'}</td><td>{row.quantity}</td><td>{number(row.price,4)}</td><td>{number(Number(row.commission||0)+Number(row.stamp_tax||0),2)}</td><td>已入账</td></tr>)}{latestRunChecks.map((row:any)=><tr key={row.check_id}><td>{row.check_name}</td><td colSpan={5}>运行 {text(row.run_id).slice(0,14)}</td><td>{Number(row.passed)===1?'通过':'失败'}</td></tr>)}</tbody></table>{latestRunFills.length===0&&latestRunChecks.length===0?<div className="f5-empty">本轮尚无成交或对账记录。</div>:null}</div></section>
    </> : null}
  </div>;
};

export default ExecutionPanel;
