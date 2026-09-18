import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Wallet } from 'lucide-react';
import { apiHeaders, f5ReasonLabel } from '../lib/workbench-state.mjs';
import { AsyncState } from './WorkbenchStatus';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
async function f5(action: string) {
  const response = await fetch(`${API_BASE}/api/paper-execution`, { method: 'POST', headers: apiHeaders(), body: JSON.stringify({ action }) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data ?? payload;
}
const money = (value: unknown) => `¥${Number(value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
const signedMoney = (value: unknown) => {
  const amount = Number(value || 0);
  return `${amount > 0 ? '+' : ''}${money(amount)}`;
};
const percent = (value: unknown) => {
  const amount = Number(value || 0);
  return `${amount > 0 ? '+' : ''}${amount.toFixed(2)}%`;
};
const pnlColor = (value: unknown) => Number(value || 0) > 0 ? '#f87171' : Number(value || 0) < 0 ? '#4ade80' : '#cbd5e1';
const localTime = (value: unknown) => {
  if (!value) return '--';
  const parsed = new Date(String(value));
  return Number.isNaN(parsed.getTime()) ? String(value) : parsed.toLocaleString('zh-CN', { hour12: false });
};

const PaperPanel: React.FC = () => {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [status, accountProjection] = await Promise.all([f5('status'), f5('account')]);
      setData({ ...accountProjection, status }); setError('');
    } catch (reason:any) { setError(reason?.message || 'F5 模拟组合读取失败'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);
  const positions = Array.isArray(data?.positions) ? data.positions : [];
  const currentMarketValue = positions.reduce((sum:number,row:any)=>sum+Number(row.quantity||0)*Number(row.current_price||0),0);
  const account = data?.account || {};
  const cash = account.cash ?? 1_000_000;
  const totalEquity = account.total_equity ?? Number(cash)+currentMarketValue;
  const run = data?.status?.latest_run || {};
  const lane = run.execution_lane || data?.status?.execution_lane;
  const quality = run.strategy_quality_status || data?.status?.strategy_quality_status;
  const laneLabel = lane === 'experimental_paper' ? '实验模拟自动交易' : lane === 'validated_paper' ? '验证通过模拟' : '未获得模拟许可';
  const qualityLabel = quality === 'unqualified' ? '策略质量：未通过F4' : quality === 'validated' ? '策略质量：已通过F4研究门禁' : '策略质量：未知';
  const modeLabel = data?.status?.execution_mode === 'paper_intraday' ? '盘中实验模拟' : '日频次日模拟';
  return <div className="f5-account">
    <style>{`
      .f5-account{display:flex;flex-direction:column;gap:14px}.f5-account header{display:flex;justify-content:space-between;gap:12px}.f5-account h1{margin:0;color:#f8fafc;font-size:var(--font-page-title)}.f5-account p{margin:5px 0 0;color:#64748b}.f5-account button{height:36px;display:flex;align-items:center;gap:6px;padding:0 12px;border:1px solid #334155;border-radius:6px;color:#cbd5e1;background:#111827}.f5-account-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:1px;border:1px solid #1e293b;background:#1e293b}.f5-account-grid div{min-width:0;padding:13px;background:#101827}.f5-account-grid span,.f5-account-grid strong{display:block}.f5-account-grid span{color:#64748b;font-size:11px}.f5-account-grid strong{margin-top:8px;color:#e2e8f0}.f5-account-note{padding:12px 14px;border:1px solid #334155;border-radius:7px;color:#94a3b8;background:#0d1422;line-height:1.6;overflow-wrap:anywhere}.f5-account-table{overflow:auto;border:1px solid #1e293b;border-radius:8px;background:#111827}.f5-account-table table{width:100%;min-width:1420px;border-collapse:collapse}.f5-account-table th,.f5-account-table td{padding:10px 12px;border-bottom:1px solid #1e293b;text-align:right;color:#cbd5e1;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}.f5-account-table th:first-child,.f5-account-table td:first-child{text-align:left;position:sticky;left:0;background:#111827;z-index:1}.f5-account-table th{color:#64748b}.f5-security-name{display:block;color:#e2e8f0;font-weight:650}.f5-security-code{display:block;margin-top:3px;color:#64748b;font-family:Consolas,monospace}.f5-account-empty{padding:28px;color:#64748b;text-align:center}@media(max-width:700px){.f5-account-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
    `}</style>
    <header><div><h1>F5 模拟组合</h1><p>全系统唯一活动模拟账本 · 现金、持仓、权益与 T+1 可卖事实</p></div><button type="button" onClick={refresh} disabled={loading}><RefreshCw size={14}/>刷新</button></header>
    {error?<AsyncState state="error" message={error} compact/>:null}
    {loading&&!data?<AsyncState state="loading"/>:null}
    {data?<>
      <div className="f5-account-note"><Wallet size={14} style={{verticalAlign:'middle',marginRight:7}}/>{laneLabel} · {qualityLabel} · {modeLabel} · 实时行情时间：{data.status?.market_fact_timestamp||'--'} · 模拟执行许可：{data.status?.paper_execution_authority?'已授权':'未授权'} · 实盘权限：未启用。当前准入原因：{f5ReasonLabel(data.status?.reason_code)}。驾驶舱、风险、告警和本页统一读取此 F5 模拟账本。</div>
      <div className="f5-account-grid">
        <div><span>总权益</span><strong>{money(totalEquity)}</strong></div>
        <div><span>可用现金</span><strong>{money(cash)}</strong></div>
        <div><span>持仓市值</span><strong>{money(account.market_value ?? currentMarketValue)}</strong></div>
        <div><span>当日盈亏</span><strong style={{color:pnlColor(account.daily_pnl)}}>{signedMoney(account.daily_pnl)}</strong></div>
        <div><span>累计盈亏</span><strong style={{color:pnlColor(account.total_pnl)}}>{signedMoney(account.total_pnl)}</strong></div>
        <div><span>累计收益率</span><strong style={{color:pnlColor(account.total_pnl_pct)}}>{percent(account.total_pnl_pct)}</strong></div>
        <div><span>持仓浮动盈亏</span><strong style={{color:pnlColor(account.unrealized_pnl)}}>{signedMoney(account.unrealized_pnl)}</strong></div>
        <div><span>已实现盈亏</span><strong style={{color:pnlColor(account.realized_pnl)}}>{signedMoney(account.realized_pnl)}</strong></div>
      </div>
      <div className="f5-account-table"><table><thead><tr><th>股票名称 / 代码</th><th>数量</th><th>可卖</th><th>当日买入</th><th>成本价</th><th>现价</th><th>成本金额</th><th>市值</th><th>浮动盈亏</th><th>盈亏率</th><th>已实现盈亏</th><th>仓位占比</th><th>更新时间</th></tr></thead><tbody>{positions.map((row:any)=><tr key={row.code}><td><span className="f5-security-name">{row.name||'名称待补'}</span><span className="f5-security-code">{row.code}</span></td><td>{row.quantity}</td><td>{row.available_qty}</td><td>{row.today_buy_qty}</td><td>{Number(row.avg_price||0).toFixed(4)}</td><td>{Number(row.current_price||0).toFixed(4)}</td><td>{money(row.cost_value)}</td><td>{money(row.market_value)}</td><td style={{color:pnlColor(row.unrealized_pnl)}}>{signedMoney(row.unrealized_pnl)}</td><td style={{color:pnlColor(row.unrealized_pnl_pct)}}>{percent(row.unrealized_pnl_pct)}</td><td style={{color:pnlColor(row.realized_pnl)}}>{signedMoney(row.realized_pnl)}</td><td>{percent(row.position_weight_pct)}</td><td>{localTime(row.updated_at)}</td></tr>)}</tbody></table>{positions.length===0?<div className="f5-account-empty">尚无 F5 模拟持仓；请查看最新运行的准入原因、目标交易日和模拟订单。</div>:null}</div>
    </>:null}
  </div>;
};

export default PaperPanel;
