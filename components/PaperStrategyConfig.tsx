import React, { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw, ShieldCheck } from 'lucide-react';
import { apiHeaders, f5ReasonLabel, f5RunStatusLabel } from '../lib/workbench-state.mjs';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
async function f5(body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}/api/paper-execution`, { method: 'POST', headers: apiHeaders(), body: JSON.stringify(body) });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.success === false) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload.data ?? payload;
}

const PaperStrategyConfig: React.FC<{ onDirtyChange?: (dirty:boolean)=>void }> = ({ onDirtyChange }) => {
  const [status, setStatus] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setBusy(true);
    try { setStatus(await f5({ action: 'status' })); setError(''); }
    catch (reason:any) { setError(reason?.message || 'F5 政策读取失败'); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { onDirtyChange?.(false); load(); return () => onDirtyChange?.(false); }, [load, onDirtyChange]);
  const control = async (action:'set_enabled'|'set_kill_switch', enabled:boolean) => {
    setBusy(true);
    try { setStatus(await f5({ action, enabled })); setError(''); }
    catch (reason:any) { setError(reason?.message || 'F5 控制请求失败'); }
    finally { setBusy(false); }
  };
  const latest = status?.latest_run || {};
  const laneLabel = latest.execution_lane === 'experimental_paper' ? '实验模拟自动交易' : latest.execution_lane === 'validated_paper' ? '验证通过模拟' : '未获得模拟许可';
  const qualityLabel = latest.strategy_quality_status === 'unqualified' ? '策略质量：未通过F4' : latest.strategy_quality_status === 'validated' ? '策略质量：已通过F4研究门禁' : '策略质量：未知';
  return <div className="f5-policy">
    <style>{`
      .f5-policy{display:flex;flex-direction:column;gap:14px}.f5-policy-head{display:flex;justify-content:space-between;gap:12px}.f5-policy h2{margin:0;color:#f8fafc;font-size:18px}.f5-policy p{margin:5px 0 0;color:#64748b;line-height:1.6}.f5-policy button{min-height:36px;padding:0 12px;border:1px solid #334155;border-radius:6px;color:#cbd5e1;background:#111827;cursor:pointer}.f5-policy button:disabled{cursor:not-allowed;opacity:.55}.f5-policy-card{padding:16px;border:1px solid #1e293b;border-radius:8px;background:#111827}.f5-policy-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.f5-policy-item{min-width:0;padding:12px;border:1px solid #1e293b;border-radius:6px;background:#0d1422}.f5-policy-item span,.f5-policy-item strong{display:block;overflow-wrap:anywhere}.f5-policy-item span{color:#64748b;font-size:11px}.f5-policy-item strong{margin-top:7px;color:#e2e8f0}.f5-policy-controls{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}.f5-policy-controls .safe{border-color:#047857;color:#a7f3d0}.f5-policy-controls .danger{border-color:#b45309;color:#fde68a}.f5-policy-warning{display:flex;gap:8px;padding:12px;border:1px solid #78350f;border-radius:7px;color:#fde68a;background:#1c1510;line-height:1.6}.f5-policy-error{color:#fca5a5}@media(max-width:760px){.f5-policy-grid{grid-template-columns:1fr}}
    `}</style>
    <header className="f5-policy-head"><div><h2>F5 模拟政策</h2><p>只允许启停确定性日频模拟或打开熔断；硬风控、组合和成交参数不可从页面放宽。</p></div><button type="button" onClick={load} disabled={busy}><RefreshCw size={14}/> 刷新</button></header>
    <div className="f5-policy-warning"><AlertTriangle size={15}/><span>这不是交易策略编辑器，也没有模型、人工证券池或任意订单入口。实盘权限永久为否。</span></div>
    <section className="f5-policy-card">
      <div className="f5-policy-grid">
        <div className="f5-policy-item"><span>政策版本</span><strong>f5-paper-policy-v1</strong></div>
        <div className="f5-policy-item"><span>当前状态</span><strong>{f5RunStatusLabel(latest.status)}</strong></div>
        <div className="f5-policy-item"><span>准入原因</span><strong>{f5ReasonLabel(latest.reason_code || status?.reason_code)}</strong></div>
        <div className="f5-policy-item"><span>模拟周期</span><strong>交易日 16:40</strong></div>
        <div className="f5-policy-item"><span>F5 启用</span><strong>{status?.enabled ? '是' : '否'}</strong></div>
        <div className="f5-policy-item"><span>熔断开关</span><strong>{status?.kill_switch ? '已打开' : '未打开'}</strong></div>
        <div className="f5-policy-item"><span>执行通道</span><strong>{laneLabel}</strong></div>
        <div className="f5-policy-item"><span>策略质量</span><strong>{qualityLabel}</strong></div>
        <div className="f5-policy-item"><span>模拟执行许可</span><strong>{status?.paper_execution_authority?'已授权':'未授权'}</strong></div>
        <div className="f5-policy-item"><span>实盘权限</span><strong>实盘权限：未启用</strong></div>
      </div>
      <div className="f5-policy-controls"><button className="safe" type="button" disabled={busy} onClick={()=>control('set_enabled',!status?.enabled)}><ShieldCheck size={14}/> {status?.enabled?'暂停后续模拟周期':'启用后续模拟周期'}</button><button className="danger" type="button" disabled={busy} onClick={()=>control('set_kill_switch',!status?.kill_switch)}>{status?.kill_switch?'解除 F5 熔断':'立即打开 F5 熔断'}</button></div>
    </section>
    {error?<div className="f5-policy-error">{error}</div>:null}
  </div>;
};

export default PaperStrategyConfig;
