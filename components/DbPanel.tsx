import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Search, RefreshCw, TrendingUp, TrendingDown, Database, Clock, BarChart3, Activity, Settings, Play, Square, Power, X, Plus, RotateCcw } from 'lucide-react';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_ALPHACOUNCIL_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-AlphaCouncil-Token': API_TOKEN } : {}) });

interface Stock { code: string; name: string; change_pct: number; volume: number; amount: number; }
interface Kline { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number; }
interface RTQuote { name: string; open: number; close: number; price: number; high: number; low: number; volume: number; amount: number; }

const QUICK_CODES = ['000001','600036','601318','000858','600519','600276','600309','000725'];
const DEFAULT_RT_WATCH = ['000001','600519','600036','000858','300750','601318','600276','000333','601398','600030','601166','002594','000651','600887','601012','002475'];
const RT_WATCH_KEY = 'rt_watch_codes'; // 自选股代码 localStorage fallback key
const ACCENT = '#F59E0B';

function normalizeWatchCode(input: string): string {
  let c = String(input || '').trim().toUpperCase();
  c = c.replace(/\.SH$|\.SZ$/i, '');
  if (c.startsWith('SH') || c.startsWith('SZ')) c = c.slice(2);
  return /^\d{6}$/.test(c) ? c : '';
}

async function dataApi(body: any) {
  const r = await fetch(`${API_BASE}/api/data`, {
    method: 'POST', headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const j = await r.json();
  if (!j.success) throw new Error(j.error || '数据接口请求失败');
  return j.data;
}

function fmtNum(n: number): string {
  if (n >= 1e8) return (n / 1e8).toFixed(2) + '亿';
  if (n >= 1e4) return (n / 1e4).toFixed(2) + '万';
  return n.toFixed(0);
}

// 计算移动平均线: 返回与 klines 等长的数组, 前置点位为 null
function calcMA(klines: Kline[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < klines.length; i++) {
    sum += klines[i].close;
    if (i >= period) sum -= klines[i - period].close;
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

// K线图: 纯SVG自绘 (蜡烛 + MA5/MA20 + 成交量副图 + hover Tooltip)
// 说明: 不依赖 recharts 内部 scale, 自己算坐标, 渲染确定可靠
const KlineChart: React.FC<{ klines: Kline[] }> = ({ klines }) => {
  const W = 900, H = 340;                 // SVG 视口
  const PAD = { top: 12, right: 52, bottom: 56, left: 8 };
  const VOL_H = 56;                       // 成交量副图高度
  const priceTop = PAD.top;
  const priceBot = H - PAD.bottom - VOL_H;
  const volTop = H - PAD.bottom - VOL_H + 10;
  const volBot = H - PAD.bottom;
  const plotW = W - PAD.left - PAD.right;

  const [hover, setHover] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  if (klines.length === 0) return null;
  const n = klines.length;

  // 价格范围 (留 4% padding)
  const pMin = Math.min(...klines.map(k => k.low));
  const pMax = Math.max(...klines.map(k => k.high));
  const pPad = (pMax - pMin) * 0.06 || 1;
  const lo = pMin - pPad, hi = pMax + pPad;
  const volMax = Math.max(...klines.map(k => k.volume), 1);

  // 预计算 MA
  const ma5 = calcMA(klines, 5);
  const ma20 = calcMA(klines, 20);

  // 坐标换算
  const slot = plotW / n;
  const cx = (i: number) => PAD.left + slot * (i + 0.5);
  const yPrice = (v: number) => priceTop + (1 - (v - lo) / (hi - lo)) * (priceBot - priceTop);
  const yVol = (v: number) => volBot - (v / volMax) * (volBot - volTop);

  // 价格 Y 轴刻度 (4 等分)
  const priceTicks = [0, 1, 2, 3, 4].map(i => lo + ((hi - lo) * i) / 4);

  // MA 折线路径 (跳过 null)
  const linePath = (arr: (number | null)[]) => {
    let d = ''; let started = false;
    arr.forEach((v, i) => {
      if (v == null) { started = false; return; }
      d += `${started ? 'L' : 'M'}${cx(i).toFixed(1)} ${yPrice(v).toFixed(1)} `;
      started = true;
    });
    return d.trim();
  };

  // X 轴日期刻度 (约每 10 根一个)
  const dateTicks: number[] = [];
  const step = Math.max(1, Math.round(n / 6));
  for (let i = 0; i < n; i += step) dateTicks.push(i);

  const hd = hover != null ? klines[hover] : null;

  return (
    <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', padding: 14 }}>
      {/* 图例 */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 6, fontSize: 11 }}>
        <span style={{ color: '#F87171' }}>▬ 上涨</span>
        <span style={{ color: '#4ADE80' }}>▬ 下跌</span>
        <span style={{ color: '#60A5FA' }}>▬ MA5</span>
        <span style={{ color: '#FBBF24' }}>▬ MA20</span>
        <span style={{ color: '#475569', marginLeft: 'auto', fontFamily: 'JetBrains Mono, monospace' }}>{n}根 · {klines[0].date}~{klines[n-1].date}</span>
      </div>
      <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} width="100%" height={H}
        onMouseLeave={() => setHover(null)}
        onMouseMove={e => {
          const r = svgRef.current!.getBoundingClientRect();
          const x = ((e.clientX - r.left) / r.width) * W - PAD.left;
          const idx = Math.floor(x / slot);
          setHover(idx >= 0 && idx < n ? idx : null);
        }}
        style={{ display: 'block', fontFamily: 'JetBrains Mono, monospace' }}>
        {/* 网格线 */}
        {priceTicks.map((t, i) => (
          <g key={'g' + i}>
            <line x1={PAD.left} x2={W - PAD.right} y1={yPrice(t)} y2={yPrice(t)} stroke="#1E293B" strokeDasharray="3 3" />
            <text x={W - PAD.right + 6} y={yPrice(t) + 3} fill="#475569" fontSize={10}>{t.toFixed(2)}</text>
          </g>
        ))}
        {/* 成交量分隔 */}
        <line x1={PAD.left} x2={W - PAD.right} y1={volTop} y2={volTop} stroke="#1E293B" />
        {/* 成交量柱 */}
        {klines.map((k, i) => {
          const up = k.close >= k.open;
          const h = yVol(k.volume) - volTop < 0 ? 1 : volBot - yVol(k.volume);
          return <rect key={'v' + i} x={cx(i) - slot * 0.3} y={yVol(k.volume)} width={slot * 0.6} height={Math.max(volBot - yVol(k.volume), 1)} fill={up ? '#F8717133' : '#4ADE8033'} />;
        })}
        {/* 蜡烛 */}
        {klines.map((k, i) => {
          const up = k.close >= k.open;
          const color = up ? '#F87171' : '#4ADE80';
          const bodyX = cx(i) - slot * 0.3, bodyW = slot * 0.6;
          const yO = yPrice(k.open), yC = yPrice(k.close);
          const bodyTop = Math.min(yO, yC), bodyH = Math.max(Math.abs(yC - yO), 1);
          return (
            <g key={'k' + i}>
              <line x1={cx(i)} x2={cx(i)} y1={yPrice(k.high)} y2={yPrice(k.low)} stroke={color} strokeWidth={1} />
              <rect x={bodyX} y={bodyTop} width={bodyW} height={bodyH} fill={color} />
            </g>
          );
        })}
        {/* MA 线 */}
        <path d={linePath(ma5)} stroke="#60A5FA" strokeWidth={1.4} fill="none" />
        <path d={linePath(ma20)} stroke="#FBBF24" strokeWidth={1.4} fill="none" />
        {/* X 轴日期 */}
        {dateTicks.map(i => (
          <text key={'d' + i} x={cx(i)} y={H - PAD.bottom + 16} fill="#475569" fontSize={10} textAnchor="middle">{klines[i].date.slice(5)}</text>
        ))}
        {/* hover 十字线 */}
        {hover != null && (
          <line x1={cx(hover)} x2={cx(hover)} y1={priceTop} y2={volBot} stroke="#334155" strokeDasharray="3 3" />
        )}
      </svg>

      {/* Tooltip 信息条 (hover 时显示) */}
      {hd && (() => {
        const change = hd.close - hd.open;
        const pct = hd.open > 0 ? (change / hd.open) * 100 : 0;
        const up = change >= 0;
        const c = up ? '#F87171' : '#4ADE80';
        const Item = ({ k, v, col }: { k: string; v: string; col?: string }) => (
          <span style={{ color: col || '#E2E8F0' }}><span style={{ color: '#475569' }}>{k} </span>{v}</span>
        );
        return (
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', padding: '8px 12px', background: '#0B0F1A', borderRadius: 8, marginTop: 8, fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>
            <span style={{ color: '#64748B' }}>{hd.date}</span>
            <Item k="收" v={hd.close.toFixed(2)} col={c} />
            <Item k="涨跌" v={`${up ? '+' : ''}${change.toFixed(2)} (${up ? '+' : ''}${pct.toFixed(2)}%)`} col={c} />
            <Item k="开" v={hd.open.toFixed(2)} />
            <Item k="高" v={hd.high.toFixed(2)} />
            <Item k="低" v={hd.low.toFixed(2)} />
            <Item k="量" v={fmtNum(hd.volume)} />
            <Item k="额" v={fmtNum(hd.amount)} />
          </div>
        );
      })()}
    </div>
  );
};



const DbPanel: React.FC = () => {
  const [tab, setTab] = useState<'browse'|'kline'|'realtime'|'manage'>('browse');
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState('000001');
  const [klines, setKlines] = useState<Kline[]>([]);
  const [kLoading, setKLoading] = useState(false);
  const [error, setError] = useState('');
  const abortRef = useRef<AbortController | null>(null);

  const loadStocks = useCallback(async () => {
    setLoading(true); setError('');
    try {
      const d = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'stocks', limit: 200 }),
      }).then(r => r.json());
      // API 返回 { success, data: { count, stocks: [{code, ...}] } } 或直接数组
      const rawList = Array.isArray(d?.data)
        ? d.data
        : (Array.isArray(d?.data?.stocks) ? d.data.stocks : null);
      if (d.success && rawList) {
        const normalized: Stock[] = rawList.map((s: any) => ({
          code:       s.code ?? '',
          name:       s.name ?? s.code ?? '',
          change_pct: Number(s.change_pct ?? s.pct_change ?? 0),
          volume:     Number(s.volume ?? 0),
          amount:     Number(s.amount ?? 0),
        }));
        setStocks(normalized);
      } else {
        setError(d.error || '获取失败');
      }
    } catch { setError('网络错误'); }
    setLoading(false);
  }, []);

  useEffect(() => { loadStocks(); }, []);

  const loadKlines = useCallback(async (c: string) => {
    setKLoading(true); setError('');
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController(); abortRef.current = ctrl;
    try {
      const d = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', signal: ctrl.signal,
        headers: jsonHeaders(),
        body: JSON.stringify({ action: 'klines', code: c, limit: 60 }),
      }).then(r => r.json());
      // API 返回 { success, data: { code, klines: [{d,o,h,l,c,v,amount}], count, dateRange } }
      const rawList = Array.isArray(d?.data) ? d.data : (Array.isArray(d?.data?.klines) ? d.data.klines : null);
      if (d.success && rawList) {
        // 归一化字段名: d/o/h/l/c/v -> date/open/high/low/close/volume
        const normalized: Kline[] = rawList.map((k: any) => ({
          date:   k.date   ?? k.d ?? '',
          open:   Number(k.open   ?? k.o ?? 0),
          high:   Number(k.high   ?? k.h ?? 0),
          low:    Number(k.low    ?? k.l ?? 0),
          close:  Number(k.close  ?? k.c ?? 0),
          volume: Number(k.volume ?? k.v ?? 0),
          amount: Number(k.amount ?? 0),
        }));
        setKlines(normalized);
      } else {
        setKlines([]);
        setError(d.error || 'K线加载失败');
      }
    } catch { setError(''); }
    setKLoading(false);
  }, []);

  useEffect(() => { loadKlines(code); }, [code]);

  const tabs = [
    { key: 'browse',   label: '市场浏览', icon: BarChart3 },
    { key: 'realtime', label: '实时行情', icon: Activity },
    { key: 'kline',    label: 'K线走势', icon: Clock },
    { key: 'manage',   label: '数据管理', icon: Settings },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Database style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>数据浏览</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>市场行情 · 历史K线 · 实时数据</div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 4, background: '#111827', padding: 4, borderRadius: 10, border: '1px solid #1E293B', width: 'fit-content' }}>
        {tabs.map(t => {
          const Icon = t.icon;
          const is = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key as typeof tab)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderRadius: 7, border: 'none', cursor: 'pointer', fontSize: 13, fontWeight: is ? 600 : 400,
                background: is ? `${ACCENT}18` : 'transparent', color: is ? ACCENT : '#64748B', transition: 'all 150ms' }}>
              <Icon style={{ width: 14, height: 14 }} />{t.label}
            </button>
          );
        })}
      </div>

      {/* Error */}
      {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>{error}</div>}

      {/* ── Market Browse ── */}
      {tab === 'browse' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Quick chips */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: '#475569', marginRight: 4 }}>快速访问</span>
            {QUICK_CODES.map(c => (
              <button key={c} onClick={() => { setCode(c); setTab('kline'); }}
                style={{ padding: '5px 12px', borderRadius: 20, border: '1px solid #1E293B', background: '#111827', color: '#94A3B8', fontSize: 12, cursor: 'pointer', fontFamily: 'JetBrains Mono, monospace', transition: 'all 150ms' }}
                onMouseEnter={e => { (e.target as HTMLElement).style.borderColor = ACCENT; (e.target as HTMLElement).style.color = ACCENT; }}
                onMouseLeave={e => { (e.target as HTMLElement).style.borderColor = '#1E293B'; (e.target as HTMLElement).style.color = '#94A3B8'; }}>
                {c}
              </button>
            ))}
            <button onClick={loadStocks} disabled={loading}
              style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px', borderRadius: 20, border: '1px solid #1E293B', background: 'transparent', color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
              <RefreshCw style={{ width: 11, height: 11, animation: loading ? 'spin 1s linear infinite' : 'none' }} />刷新
            </button>
          </div>

          {/* Table */}
          <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#0B0F1A', borderBottom: '1px solid #1E293B' }}>
                  {['代码','名称','涨跌幅','成交量','成交额'].map((h,i) => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: i>=2?'right':'left', fontSize: 11, fontWeight: 600, color: '#475569', letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {stocks.slice(0,80).map((s,i) => {
                  const up = s.change_pct > 0;
                  const dn = s.change_pct < 0;
                  const cls = up ? '#F87171' : dn ? '#4ADE80' : '#64748B';
                  return (
                    <tr key={s.code} style={{ borderBottom: '1px solid #1E293B44', transition: 'background 100ms' }}
                      onMouseEnter={e => (e.currentTarget.style.background = '#1E293B55')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                      <td style={{ padding: '9px 14px', fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontSize: 12 }}>{s.code}</td>
                      <td style={{ padding: '9px 14px', color: '#E2E8F0', fontSize: 12 }}>{s.name}</td>
                      <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: cls, fontWeight: 600 }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                          {up ? <TrendingUp style={{ width: 10, height: 10 }} /> : dn ? <TrendingDown style={{ width: 10, height: 10 }} /> : null}
                          {up?'+':''}{s.change_pct.toFixed(2)}%
                        </span>
                      </td>
                      <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{fmtNum(s.volume)}</td>
                      <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{fmtNum(s.amount)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {loading && <div style={{ padding: 20, textAlign: 'center', color: '#64748B', fontSize: 12 }}>加载中...</div>}
            {!loading && stocks.length === 0 && <div style={{ padding: 30, textAlign: 'center', color: '#475569', fontSize: 12 }}>暂无数据</div>}
          </div>
        </div>
      )}

      {/* ── K-line ── */}
      {tab === 'kline' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Search bar */}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <div style={{ position: 'relative' }}>
              <Search style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', width: 14, height: 14, color: '#475569' }} />
              <input value={code} onChange={e => setCode(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && loadKlines(code)}
                style={{ padding: '8px 12px 8px 32px', background: '#111827', border: '1px solid #1E293B', borderRadius: 8, color: '#E2E8F0', fontSize: 13, fontFamily: 'JetBrains Mono, monospace', width: 120, outline: 'none' }}
                onFocus={e => (e.target.style.borderColor = ACCENT)}
                onBlur={e => (e.target.style.borderColor = '#1E293B')} />
            </div>
            <button onClick={() => loadKlines(code)} disabled={kLoading}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, borderRadius: 8, color: ACCENT, fontSize: 13, cursor: 'pointer', fontWeight: 600 }}>
              <RefreshCw style={{ width: 13, height: 13, animation: kLoading ? 'spin 1s linear infinite' : 'none' }} />查询
            </button>
            <span style={{ fontSize: 11, color: '#475569' }}>输入代码按 Enter 或点击查询</span>
          </div>

          {/* K线图 */}
          {!kLoading && klines.length > 0 && <KlineChart klines={klines} />}

          {/* K-line table */}
          <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#0B0F1A', borderBottom: '1px solid #1E293B' }}>
                  {['日期','开盘','最高','最低','收盘','成交量','成交额'].map((h,i) => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: i>=1?'right':'left', fontSize: 11, fontWeight: 600, color: '#475569', letterSpacing: 0.5 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {klines.map((k,i) => {
                  const prev = klines[i-1];
                  const up = prev ? k.close >= prev.close : true;
                  const cls = up ? '#F87171' : '#4ADE80';
                  return (
                    <tr key={k.date} style={{ borderBottom: '1px solid #1E293B44', transition: 'background 100ms' }}
                      onMouseEnter={e => (e.currentTarget.style.background = '#1E293B55')}
                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                      <td style={{ padding: '8px 14px', color: '#94A3B8', fontSize: 11, fontFamily: 'JetBrains Mono, monospace' }}>{k.date}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0', fontSize: 11 }}>{k.open.toFixed(2)}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0', fontSize: 11 }}>{k.high.toFixed(2)}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0', fontSize: 11 }}>{k.low.toFixed(2)}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: cls, fontWeight: 600, fontSize: 11 }}>{k.close.toFixed(2)}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{fmtNum(k.volume)}</td>
                      <td style={{ padding: '8px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{fmtNum(k.amount)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {kLoading && <div style={{ padding: 20, textAlign: 'center', color: '#64748B', fontSize: 12 }}>加载中...</div>}
            {!kLoading && klines.length === 0 && <div style={{ padding: 30, textAlign: 'center', color: '#475569', fontSize: 12 }}>无K线数据</div>}
          </div>
        </div>
      )}

      {/* ── Realtime Quotes (盘中实时轮询) ── */}
      {tab === 'realtime' && (
        <RealtimePanel />
      )}

      {/* ── Data Management (手动/自动更新) ── */}
      {tab === 'manage' && (
        <DataManagePanel />
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }
        @keyframes flash-up { 0%{background:#22C55E33;} 100%{background:transparent;} }
        @keyframes flash-dn { 0%{background:#EF444433;} 100%{background:transparent;} }
        .rt-remove-btn { pointer-events: auto; }
        div:hover > .rt-remove-btn { opacity: 1 !important; }`}</style>
    </div>
  );
};

// ── 实时行情面板 (每5秒轮询新浪) ──────────────────────────
const RealtimePanel: React.FC = () => {
  const [quotes, setQuotes] = useState<Record<string, RTQuote>>({});
  const [flash, setFlash] = useState<Record<string, 'up'|'dn'>>({});
  const [running, setRunning] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [tick, setTick] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── 自选股列表 (后端持久化 + localStorage 兜底) ──
  const [watch, setWatch] = useState<string[]>(() => {
    try {
      const saved = localStorage.getItem(RT_WATCH_KEY);
      if (saved) {
        const arr = JSON.parse(saved);
        if (Array.isArray(arr)) {
          const codes = arr.map(normalizeWatchCode).filter(Boolean);
          if (codes.length) return Array.from(new Set(codes));
        }
      }
    } catch { /* 忽略损坏的本地数据 */ }
    return DEFAULT_RT_WATCH;
  });
  const [newCode, setNewCode] = useState('');
  const [addErr, setAddErr] = useState('');

  // 初始化时优先读取后端 watchlist, 失败则继续使用 localStorage/default。
  useEffect(() => {
    dataApi({ action: 'watchlist_get' })
      .then(d => {
        const codes = Array.isArray(d?.codes) ? d.codes.map(normalizeWatchCode).filter(Boolean) : [];
        if (codes.length) setWatch(Array.from(new Set(codes)));
      })
      .catch(() => {});
  }, []);

  // watch 变化时写回 localStorage 作为离线兜底
  useEffect(() => {
    try { localStorage.setItem(RT_WATCH_KEY, JSON.stringify(watch)); } catch { /* 容量满等忽略 */ }
  }, [watch]);

  const addCode = async () => {
    const c = normalizeWatchCode(newCode);
    setAddErr('');
    if (!c) { setAddErr('请输入合法的6位A股代码，支持 600519 / sh600519 / 600519.SH'); return; }
    if (watch.includes(c)) { setAddErr('该代码已在自选列表中'); return; }
    try {
      const d = await dataApi({ action: 'watchlist_add', code: c });
      const codes = Array.isArray(d?.codes) ? d.codes.map(normalizeWatchCode).filter(Boolean) : [...watch, c];
      setWatch(Array.from(new Set(codes)));
      setNewCode('');
    } catch (e: any) {
      setAddErr(e.message || '保存自选股失败');
    }
  };
  const removeCode = async (code: string) => {
    const c = normalizeWatchCode(code);
    setWatch(w => w.filter(x => x !== c));
    try {
      const d = await dataApi({ action: 'watchlist_remove', code: c });
      const codes = Array.isArray(d?.codes) ? d.codes.map(normalizeWatchCode).filter(Boolean) : [];
      setWatch(codes);
    } catch { /* 本地已删除, 下次刷新会以后端为准 */ }
  };
  const resetWatch = async () => {
    try {
      const d = await dataApi({ action: 'watchlist_reset' });
      const codes = Array.isArray(d?.codes) ? d.codes.map(normalizeWatchCode).filter(Boolean) : DEFAULT_RT_WATCH;
      setWatch(codes);
    } catch {
      setWatch(DEFAULT_RT_WATCH);
    }
  };

  const poll = useCallback(async () => {
    if (watch.length === 0) { setQuotes({}); return; }
    // 统一走 /api/data → data_runner → market_data.fetch_realtime
    // 市场数据已统一到 Python 数据层, 不再走 /api/market (Node Sina)
    try {
      const r = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'realtime_prices', codes: watch }),
      }).then(r => r.json());
      if (r.success && r.data) {
        // market_data 返回 key 为 sina 代码 (如 sh600519/sz000001), 归一化回纯代码
        const norm: Record<string, RTQuote> = {};
        for (const [k, v] of Object.entries(r.data)) {
          const pureCode = k.replace(/^(sh|sz)/, '');
          norm[pureCode] = v as RTQuote;
        }
        // 闪烁检测: 价格变化
        setQuotes(prev => {
          const newFlash: Record<string, 'up'|'dn'> = {};
          for (const [code, q] of Object.entries(norm)) {
            const pp = prev[code]?.price;
            if (pp !== undefined && q.price > pp) newFlash[code] = 'up';
            else if (pp !== undefined && q.price < pp) newFlash[code] = 'dn';
          }
          if (Object.keys(newFlash).length) {
            setFlash(newFlash);
            setTimeout(() => setFlash({}), 600);
          }
          return norm;
        });
        setLastUpdate(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
        setTick(t => t + 1);
      }
    } catch { /* 静默重试 */ }
  }, [watch]);

  useEffect(() => {
    poll();
    if (running) {
      timerRef.current = setInterval(poll, 5000);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [running, poll]);

  const totalUp = Object.values(quotes).filter(q => q.price > q.close).length;
  const totalDn = Object.values(quotes).filter(q => q.price < q.close).length;
  const totalAmt = Object.values(quotes).reduce((s, q) => s + (q.amount || 0), 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header bar */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: '#22C55E15', border: '1px solid #22C55E44', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Activity style={{ width: 18, height: 18, color: '#22C55E' }} />
          </div>
          <div>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#F1F5F9' }}>盘中实时行情</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>
              {lastUpdate ? `最后更新 ${lastUpdate} · ${tick}次轮询` : '连接中...'} · 新浪财经源
            </div>
          </div>
        </div>
        {/* 汇总统计 */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#F87171', fontFamily: 'JetBrains Mono, monospace' }}>{totalUp}</div>
            <div style={{ fontSize: 10, color: '#475569' }}>上涨</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#4ADE80', fontFamily: 'JetBrains Mono, monospace' }}>{totalDn}</div>
            <div style={{ fontSize: 10, color: '#475569' }}>下跌</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{fmtNum(totalAmt)}</div>
            <div style={{ fontSize: 10, color: '#475569' }}>总成交额</div>
          </div>
          {/* 暂停/继续 */}
          <button onClick={() => setRunning(r => !r)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: `1px solid ${running ? '#22C55E44' : '#F59E0B44'}`, background: running ? '#22C55E15' : '#F59E0B15', color: running ? '#22C55E' : '#F59E0B', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>
            <RefreshCw style={{ width: 12, height: 12, animation: running ? 'spin 2s linear infinite' : 'none' }} />
            {running ? '轮询中(5s)' : '已暂停'}
          </button>
        </div>
      </div>

      {/* 自选股管理条 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '10px 12px', background: '#0F172A', borderRadius: 10, border: '1px solid #1E293B' }}>
        <span style={{ fontSize: 12, color: '#94A3B8', fontWeight: 600 }}>自选股</span>
        <span style={{ fontSize: 11, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>共{watch.length}只</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          <input
            value={newCode}
            onChange={e => { setNewCode(e.target.value.toUpperCase().slice(0, 12)); setAddErr(''); }}
            onKeyDown={e => { if (e.key === 'Enter') addCode(); }}
            placeholder="600519 / SH600519"
            inputMode="text"
            style={{ width: 90, padding: '6px 10px', borderRadius: 8, border: '1px solid #334155', background: '#1E293B', color: '#F1F5F9', fontSize: 12, fontFamily: 'JetBrains Mono, monospace', outline: 'none' }}
          />
          <button onClick={addCode}
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 12px', borderRadius: 8, border: '1px solid #22C55E44', background: '#22C55E15', color: '#22C55E', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>
            <Plus style={{ width: 13, height: 13 }} />添加
          </button>
          <button onClick={resetWatch} title="恢复默认自选列表"
            style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '6px 10px', borderRadius: 8, border: '1px solid #334155', background: '#1E293B', color: '#94A3B8', fontSize: 12, cursor: 'pointer' }}>
            <RotateCcw style={{ width: 13, height: 13 }} />默认
          </button>
        </div>
        {addErr && <div style={{ flexBasis: '100%', fontSize: 11, color: '#F87171' }}>{addErr}</div>}
      </div>

      {/* Cards grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 10 }}>
        {watch.length === 0 && (
          <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: 32, color: '#475569', fontSize: 13 }}>
            自选列表为空，请在上方输入框添加股票代码
          </div>
        )}
        {watch.map(code => {
          const q = quotes[code];
          if (!q) {
            return (
              <div key={code} style={{ position: 'relative', background: '#111827', borderRadius: 10, border: '1px solid #1E293B', padding: 14 }}>
                <RtRemoveBtn code={code} onRemove={removeCode} />
                <div style={{ fontSize: 11, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>{code}</div>
                <div style={{ fontSize: 13, color: '#475569', marginTop: 8 }}>加载中...</div>
              </div>
            );
          }
          const change = q.price - q.close;
          const pct = q.close > 0 ? (change / q.close) * 100 : 0;
          const up = change > 0, dn = change < 0;
          const cls = up ? '#F87171' : dn ? '#4ADE80' : '#64748B';
          const fl = flash[code];
          const flashStyle = fl === 'up' ? { animation: 'flash-up 0.6s ease' } : fl === 'dn' ? { animation: 'flash-dn 0.6s ease' } : {};
          return (
            <div key={code} style={{ position: 'relative', background: '#111827', borderRadius: 10, border: `1px solid ${up?'#F8717133':dn?'#4ADE8033':'#1E293B'}`, padding: 14, transition: 'border-color 200ms', ...flashStyle }}>
              <RtRemoveBtn code={code} onRemove={removeCode} />
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
                <span style={{ fontSize: 11, color: '#60A5FA', fontFamily: 'JetBrains Mono, monospace' }}>{code}</span>
                <span style={{ fontSize: 11, color: '#94A3B8', maxWidth: 90, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{q.name}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 800, color: cls, fontFamily: 'JetBrains Mono, monospace' }}>{q.price.toFixed(2)}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: cls, fontFamily: 'JetBrains Mono, monospace' }}>
                  {up?'+':''}{change.toFixed(2)} ({up?'+':''}{pct.toFixed(2)}%)
                </span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 10, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>
                <span>开{q.open.toFixed(2)}</span>
                <span>高<span style={{color:'#F87171'}}>{q.high.toFixed(2)}</span></span>
                <span>低<span style={{color:'#4ADE80'}}>{q.low.toFixed(2)}</span></span>
              </div>
              <div style={{ fontSize: 10, color: '#475569', fontFamily: 'JetBrains Mono, monospace', marginTop: 4 }}>
                量 {fmtNum(q.volume)} · 额 {fmtNum(q.amount)}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: '#475569', textAlign: 'center' }}>
        数据源: Python数据层 / 新浪财经 hq.sinajs.cn · 自选股已服务端保存 · 5秒轮询
      </div>
    </div>
  );
};

// ── 自选股卡片删除按钮 ──
const RtRemoveBtn: React.FC<{ code: string; onRemove: (c: string) => void }> = ({ code, onRemove }) => (
  <button
    onClick={() => onRemove(code)}
    title="移出自选"
    style={{
      position: 'absolute', top: 6, right: 6, width: 20, height: 20, borderRadius: 6,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      border: '1px solid #334155', background: '#1E293BDD', color: '#94A3B8',
      cursor: 'pointer', opacity: 1, transition: 'opacity 150ms, color 150ms',
    }}
    className="rt-remove-btn"
  >
    <X style={{ width: 12, height: 12 }} />
  </button>
);

// ── 数据管理面板 (手动更新 + 自动同步开关 + 进度) ──────────
interface UpdateState {
  running: boolean; percent: number; step: string;
  done: number; total: number; ok: number; skip: number; err: number; new_bars: number;
  started_at: string | null; finished_at: string | null; mode: string;
}
interface DaemonState {
  trading: { is_trading: boolean; session: string };
  realtime_fresh: boolean;
  watch_count: number;
}

const DataManagePanel: React.FC = () => {
  const [upd, setUpd] = useState<UpdateState | null>(null);
  const [daemon, setDaemon] = useState<DaemonState | null>(null);
  const [autoOn, setAutoOn] = useState(() => localStorage.getItem('ac_auto_sync') === '1');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const pollProgress = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/sync`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'update_progress' }),
      }).then(r => r.json());
      if (r.success) setUpd(r.data);
    } catch {}
  }, []);

  const pollDaemon = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/sync`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'daemon_status' }),
      }).then(r => r.json());
      if (r.success && r.data && r.data.trading) setDaemon(r.data);
    } catch {}
  }, []);

  useEffect(() => {
    pollProgress(); pollDaemon();
    const t = setInterval(() => { pollProgress(); pollDaemon(); }, 3000);
    return () => clearInterval(t);
  }, [pollProgress, pollDaemon]);

  // 启动更新任务
  const startUpdate = async (mode: 'kline' | 'financial') => {
    setBusy(true); setMsg('');
    try {
      const r = await fetch(`${API_BASE}/api/sync`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'start_update', mode }),
      }).then(r => r.json());
      if (r.success) {
        setMsg(`${mode === 'kline' ? 'K线' : '财务'}更新已启动...`);
        pollProgress();
      } else {
        setMsg(r.error || '启动失败');
      }
    } catch (e: any) { setMsg('网络错误: ' + e.message); }
    setBusy(false);
  };

  const stopUpdate = async () => {
    try {
      await fetch(`${API_BASE}/api/sync`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'stop_update' }),
      }).then(r => r.json());
      setMsg('已停止更新');
      pollProgress();
    } catch {}
  };

  // 自动同步开关 (持久化到 localStorage, 开启时启动 daemon)
  const toggleAuto = async () => {
    const next = !autoOn;
    setAutoOn(next);
    localStorage.setItem('ac_auto_sync', next ? '1' : '0');
    if (next) {
      try {
        await fetch(`${API_BASE}/api/sync`, {
          method: 'POST', headers: jsonHeaders(),
          body: JSON.stringify({ action: 'start' }),
        });
      } catch { /* daemon 启动失败不阻塞 UI */ }
      pollDaemon();
      setMsg('自动同步已开启 — 盘中每10秒刷新实时行情，收盘后合并当日K线');
    } else {
      try {
        await fetch(`${API_BASE}/api/sync`, {
          method: 'POST', headers: jsonHeaders(),
          body: JSON.stringify({ action: 'stop' }),
        });
      } catch { /* 静默 */ }
      setMsg('自动同步已关闭 — 需手动点击更新');
    }
  };

  // 组件挂载时, 如果上次开过自动同步, 恢复 daemon 并启动轮询
  useEffect(() => {
    if (autoOn) {
      fetch(`${API_BASE}/api/sync`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'start' }),
      }).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isRunning = upd?.running;
  const pct = upd?.percent || 0;
  const elapsed = upd?.started_at && upd?.finished_at
    ? Math.round((new Date(upd.finished_at).getTime() - new Date(upd.started_at).getTime()) / 1000)
    : (upd?.started_at ? Math.round((Date.now() - new Date(upd.started_at).getTime()) / 1000) : 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Settings style={{ width: 20, height: 20, color: ACCENT }} />
        </div>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#F1F5F9' }}>数据管理</div>
          <div style={{ fontSize: 11, color: '#64748B' }}>手动更新 · 自动同步 · 进度监控</div>
        </div>
      </div>

      {msg && (
        <div style={{ padding: '10px 14px', background: `${ACCENT}14`, border: `1px solid ${ACCENT}33`, borderRadius: 8, fontSize: 12, color: '#FCD34D' }}>{msg}</div>
      )}

      {/* ── 自动同步开关 ── */}
      <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', padding: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Power style={{ width: 18, height: 18, color: autoOn ? '#22C55E' : '#64748B' }} />
            <div>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>行情自动刷新</div>
              <div style={{ fontSize: 11, color: '#64748B' }}>
                {daemon?.trading ? `交易时段 [${daemon.trading.session}] · ` : ''}
                {daemon ? `${daemon.realtime_fresh ? '守护进程运行中' : '守护进程未运行'} · 监控${daemon.watch_count}只` : '查询中...'}
              </div>
            </div>
          </div>
          {/* Toggle switch */}
          <button onClick={toggleAuto}
            style={{ width: 52, height: 28, borderRadius: 14, border: 'none', cursor: 'pointer',
              background: autoOn ? '#22C55E' : '#374151', position: 'relative', transition: 'background 200ms' }}>
            <span style={{ position: 'absolute', top: 3, left: autoOn ? 27 : 3, width: 22, height: 22, borderRadius: '50%', background: '#fff', transition: 'left 200ms', boxShadow: '0 2px 4px rgba(0,0,0,0.3)' }} />
          </button>
        </div>
        <div style={{ fontSize: 11, color: '#475569', lineHeight: 1.6 }}>
          开启后：盘中每 10 秒自动刷新热门股实时报价，收盘后自动合并当日完整 K 线。<b style={{ color: '#64748B' }}>仅刷新行情数据，不触发任何交易</b>。需在命令行运行 <code style={{ color: ACCENT }}>python -m quant.data.sync_service</code> 启动守护进程。
        </div>
      </div>

      {/* ── 手动更新按钮 ── */}
      <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', padding: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0', marginBottom: 14 }}>手动数据更新</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button onClick={() => startUpdate('kline')} disabled={busy || isRunning}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 8,
              border: `1px solid ${ACCENT}44`, background: `${ACCENT}18`, color: ACCENT, fontSize: 13, fontWeight: 600,
              cursor: busy || isRunning ? 'not-allowed' : 'pointer', opacity: busy || isRunning ? 0.5 : 1 }}>
            <Play style={{ width: 14, height: 14 }} />增量更新 K线
          </button>
          <button onClick={() => startUpdate('financial')} disabled={busy || isRunning}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 8,
              border: '1px solid #818CF844', background: '#818CF818', color: '#818CF8', fontSize: 13, fontWeight: 600,
              cursor: busy || isRunning ? 'not-allowed' : 'pointer', opacity: busy || isRunning ? 0.5 : 1 }}>
            <Play style={{ width: 14, height: 14 }} />刷新财务数据
          </button>
          {isRunning && (
            <button onClick={stopUpdate}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 18px', borderRadius: 8,
                border: '1px solid #EF444444', background: '#EF444418', color: '#F87171', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
              <Square style={{ width: 14, height: 14 }} />停止
            </button>
          )}
        </div>
        <div style={{ fontSize: 11, color: '#475569', marginTop: 10, lineHeight: 1.6 }}>
          K线增量：只拉每只股票最后日期之后的新数据，约 30 分钟（全 A 股 5207 只）。<br/>
          财务刷新：全量 80 项财务指标，季度任务，约 5 小时。
        </div>
      </div>

      {/* ── 进度监控 ── */}
      {upd && (
        <div style={{ background: '#111827', borderRadius: 12, border: `1px solid ${isRunning ? ACCENT + '44' : '#1E293B'}`, padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>更新进度</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              {isRunning && <RefreshCw style={{ width: 12, height: 12, color: ACCENT, animation: 'spin 1s linear infinite' }} />}
              <span style={{ fontSize: 12, fontWeight: 600, color: isRunning ? ACCENT : '#64748B' }}>
                {isRunning ? `${pct}%` : (upd.finished_at ? '已完成' : '空闲')}
              </span>
            </div>
          </div>

          {/* Progress bar */}
          <div style={{ width: '100%', height: 8, background: '#1E293B', borderRadius: 4, overflow: 'hidden', marginBottom: 12 }}>
            <div style={{
              width: `${pct}%`, height: '100%',
              background: isRunning ? `linear-gradient(90deg, ${ACCENT}, #FBBF24)` : (upd.finished_at ? '#22C55E' : '#374151'),
              borderRadius: 4, transition: 'width 300ms ease',
            }} />
          </div>

          {/* Stats grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
            <StatBox label="当前步骤" value={upd.step || '—'} wide />
            <StatBox label="进度" value={upd.total > 0 ? `${upd.done}/${upd.total}` : '—'} />
            <StatBox label="成功" value={String(upd.ok)} color="#4ADE80" />
            <StatBox label="跳过" value={String(upd.skip)} color="#64748B" />
            <StatBox label="失败" value={String(upd.err)} color={upd.err > 0 ? '#F87171' : '#94A3B8'} />
            <StatBox label="新增K线" value={String(upd.new_bars)} color={ACCENT} />
            <StatBox label="耗时" value={elapsed > 0 ? `${Math.floor(elapsed/60)}分${elapsed%60}秒` : '—'} />
            <StatBox label="模式" value={upd.mode || '—'} />
          </div>

          {upd.finished_at && !isRunning && (
            <div style={{ marginTop: 12, fontSize: 11, color: '#475569' }}>
              开始: {upd.started_at?.slice(11,19)} · 结束: {upd.finished_at?.slice(11,19)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const StatBox: React.FC<{ label: string; value: string; color?: string; wide?: boolean }> = ({ label, value, color, wide }) => (
  <div style={{ background: '#0B0F1A', borderRadius: 8, padding: '10px 12px', gridColumn: wide ? '1 / -1' : 'auto' }}>
    <div style={{ fontSize: 10, color: '#475569', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 13, fontWeight: 600, color: color || '#E2E8F0', fontFamily: wide ? 'inherit' : 'JetBrains Mono, monospace', whiteSpace: wide ? 'normal' : 'nowrap', overflow: wide ? 'visible' : 'hidden', textOverflow: wide ? 'clip' : 'ellipsis' }}>
      {value}
    </div>
  </div>
);

export default DbPanel;
