import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Search, RefreshCw, TrendingUp, TrendingDown, Database, Clock, BarChart3, Activity, Settings, Play, Square, Power, X, Plus, RotateCcw, Users, LineChart, Star, Scale, Download, FileSpreadsheet } from 'lucide-react';
import ValuationPanel from './ValuationPanel';
import FinancialStatementsPanel from './FinancialStatementsPanel';
import { ResearchBoundary } from './ResearchBoundary';
import { useMarketStream } from '../hooks/useMarketStream';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';
const jsonHeaders = () => ({ 'Content-Type': 'application/json', ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}) });

interface Stock {
  code: string;
  name: string;
  change_pct: number;
  volume: number;
  amount: number;
  price?: number;
  latest_time?: string;
  source?: string;
  prev_close?: number;
  high?: number;
  low?: number;
  change?: number;
  amplitude?: number;
  turnover_rate?: number | null;
  main_net_inflow?: number | null;
  main_net_inflow_pct?: number | null;
  money_flow_source?: string | null;
  turnover_source?: string | null;
}
interface Kline { date: string; open: number; high: number; low: number; close: number; volume: number; amount: number; }
interface RTQuote { name: string; open: number; close: number; price: number; high: number; low: number; volume: number; amount: number; }
interface TickRow { code: string; date: string; time: string; price: number; volume: number; amount: number; direction?: string; source?: string; }
interface TickStats { count?: number; true_tick_count?: number; latest_price?: number; vwap?: number; total_volume?: number; total_amount?: number; buy_volume?: number; sell_volume?: number; neutral_volume?: number; imbalance?: number; source?: string; last_time?: string; }
interface BookLevel { level: number; price: number; volume: number; }
interface OrderBook { bids?: BookLevel[]; asks?: BookLevel[]; source?: string; note?: string; }

// 简易中文拼音首字母映射 (覆盖常用字, 用 Unicode 区间近似, 不追求完美)
// 用于市场浏览搜索框的拼音首字母匹配 (如 "maotai" → 茅台)
const PINYIN_FIRST: Record<number, string> = (() => {
  const map: Record<number, string> = {};
  const borders: Array<[number, string]> = [
    [0xB0A1, 'a'], [0xB0C5, 'b'], [0xB2C1, 'c'], [0xB4EE, 'd'], [0xB6EA, 'e'],
    [0xB7A2, 'f'], [0xB8C1, 'g'], [0xB9FE, 'h'], [0xBBF7, 'j'], [0xBFA6, 'k'],
    [0xC0AC, 'l'], [0xC2E8, 'm'], [0xC4C3, 'n'], [0xC5B6, 'o'], [0xC5BE, 'p'],
    [0xC6DA, 'q'], [0xC8BB, 'r'], [0xC8F6, 's'], [0xCBFA, 't'], [0xCDDA, 'w'],
    [0xCEF4, 'x'], [0xD1B9, 'y'], [0xD4D1, 'z'],
  ];
  for (let i = 0; i < borders.length; i++) {
    const [start, letter] = borders[i];
    const end = i + 1 < borders.length ? borders[i + 1][0] : 0xD7FA;
    for (let c = start; c < end; c++) map[c] = letter as string;
  }
  return map;
})();

function pinyinFirst(str: string): string {
  let result = '';
  for (const ch of str) {
    const code = ch.charCodeAt(0);
    if (code >= 0xB0A1 && code <= 0xD7FA) {
      result += PINYIN_FIRST[code] || '?';
    } else if (/[a-zA-Z0-9]/.test(ch)) {
      result += ch.toLowerCase();
    }
  }
  return result;
}

// 导出 CSV (纯前端 Blob, 零依赖)
function exportCSV(filename: string, headers: string[], rows: (string | number)[][]) {
  const escape = (v: string | number) => {
    const s = String(v ?? '');
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const csv = '\uFEFF' + [headers.map(escape), ...rows.map(r => r.map(escape))].map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
interface TickBackfillStatus { code?: string; trade_date?: string; fetched?: number; written?: number; stored_count?: number; first_time?: string; last_time?: string; complete?: boolean; pages?: number; source?: string; source_error?: string; from_cache?: boolean; error?: string; }

const DEFAULT_RT_WATCH = ['000001','600519','600036','000858','300750','601318','600276','000333','601398','600030','601166','002594','000651','600887','601012','002475'];
const RT_WATCH_KEY = 'rt_watch_codes'; // 自选股代码 localStorage fallback key
const WATCHLIST_EVENT = 'xuanji:watchlist-changed';
const ACCENT = '#F59E0B';

function normalizeWatchCode(input: string): string {
  let c = String(input || '').trim().toUpperCase();
  c = c.replace(/\.SH$|\.SZ$/i, '');
  if (c.startsWith('SH') || c.startsWith('SZ')) c = c.slice(2);
  return /^\d{6}$/.test(c) ? c : '';
}

function normalizeWatchCodes(input: unknown): string[] {
  if (!Array.isArray(input)) return [];
  return Array.from(new Set(input.map(x => normalizeWatchCode(String(x))).filter(Boolean)));
}

function readLocalWatchCodes(): string[] {
  try {
    const saved = localStorage.getItem(RT_WATCH_KEY);
    return saved ? normalizeWatchCodes(JSON.parse(saved)) : [];
  } catch {
    return [];
  }
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

function optionalNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function compareNullableNumber(a: number | null | undefined, b: number | null | undefined, direction: 'asc' | 'desc'): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return direction === 'desc' ? b - a : a - b;
}

function fmtSignedAmount(value: number): string {
  const absolute = Math.abs(value);
  const body = absolute >= 1e8
    ? `${(absolute / 1e8).toFixed(2)}亿`
    : absolute >= 1e4
      ? `${(absolute / 1e4).toFixed(2)}万`
      : absolute.toFixed(2);
  return `${value > 0 ? '+' : value < 0 ? '-' : ''}${body}`;
}

function signedColor(value: number | null | undefined): string {
  if (value == null || value === 0) return '#64748B';
  return value > 0 ? '#F87171' : '#4ADE80';
}

function todayTradeDate(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}${m}${day}`;
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
  const [tab, setTab] = useState<'browse'|'valuation'|'kline'|'realtime'|'financials'|'manage'>('browse');
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [stocksMeta, setStocksMeta] = useState<{ source?: string; latest_time?: string; latest_date?: string; generation_id?: string; quote_timestamp?: string; market_metrics?: { source?: string; fetched_at?: string; available?: boolean } }>({});
  // 市场浏览: 前端列排序 + 搜索过滤 (后端仍按成交额返回Top100, 前端二次排序/筛选)
  const [sortKey, setSortKey] = useState<'amount'|'change_pct'|'amplitude'|'volume'|'change'|'price'|'turnover_rate'|'main_net_inflow'|'main_net_inflow_pct'>('amount');
  const [sortDir, setSortDir] = useState<'desc'|'asc'>('desc');
  const [searchText, setSearchText] = useState('');
  const [selectedStock, setSelectedStock] = useState<Stock | null>(null);
  const [ticks, setTicks] = useState<TickRow[]>([]);
  const [tickStats, setTickStats] = useState<TickStats>({});
  const [orderBook, setOrderBook] = useState<OrderBook>({});
  const [tickBackfill, setTickBackfill] = useState<TickBackfillStatus | null>(null);
  const [tickFullDayMode, setTickFullDayMode] = useState(false);
  const [tickLoading, setTickLoading] = useState(false);
  const [tickBackfillLoading, setTickBackfillLoading] = useState(false);
  const [tickPage, setTickPage] = useState(1);
  const tickPageSize = 200;
  const [loading, setLoading] = useState(false);
  const [code, setCode] = useState('000001');
  const [klineCode, setKlineCode] = useState('000001');
  const [klineName, setKlineName] = useState('');
  const [klines, setKlines] = useState<Kline[]>([]);
  const [kLoading, setKLoading] = useState(false);
  // K线周期/复权切换 (后端 action_klines 支持 period/fq)
  const [klinePeriod, setKlinePeriod] = useState<string>('1d');
  const [klineFq, setKlineFq] = useState<string>('none');
  const [error, setError] = useState('');
  // 右键菜单
  const [ctxMenu, setCtxMenu] = useState<{ x: number; y: number; stock: Stock } | null>(null);
  const [aiAnalysis, setAiAnalysis] = useState<{ code: string; name: string; loading: boolean; result: any } | null>(null);
  const [ctxNotice, setCtxNotice] = useState('');
  const [valuationStock, setValuationStock] = useState({ code: '300442', name: '' });
  const [valuationRequestKey, setValuationRequestKey] = useState(0);
  const [financialStock, setFinancialStock] = useState({ code: '600519', name: '' });
  const [financialRequestKey, setFinancialRequestKey] = useState(0);
  const [quickCodes, setQuickCodes] = useState<string[]>(() => {
    const local = readLocalWatchCodes();
    return local.length ? local : DEFAULT_RT_WATCH;
  });
  const abortRef = useRef<AbortController | null>(null);
  const stocksLoadingRef = useRef(false);
  const tickFullDayModeRef = useRef(false);
  const ctxMenuRef = useRef<HTMLDivElement | null>(null);
  const ctxMenuTriggerRef = useRef<HTMLElement | null>(null);
  const tickTotalPages = useMemo(() => Math.max(1, Math.ceil(ticks.length / tickPageSize)), [ticks.length, tickPageSize]);
  const safeTickPage = Math.min(tickPage, tickTotalPages);
  const pagedTicks = useMemo(() => {
    const start = (safeTickPage - 1) * tickPageSize;
    return ticks.slice(start, start + tickPageSize);
  }, [ticks, safeTickPage, tickPageSize]);

  useEffect(() => {
    tickFullDayModeRef.current = tickFullDayMode;
  }, [tickFullDayMode]);

  // ── 右键菜单操作 ──
  const handleStockContextMenu = (e: React.MouseEvent, stock: Stock) => {
    e.preventDefault();
    ctxMenuTriggerRef.current = e.currentTarget as HTMLElement;
    window.dispatchEvent(new CustomEvent('xuanji-stock-context', {
      detail: {
        stock,
        x: e.clientX || window.innerWidth * 0.5,
        y: e.clientY || window.innerHeight * 0.45,
      },
    }));
  };

  useEffect(() => {
    const close = () => setCtxMenu(null);
    const closeWithKeyboard = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setCtxMenu(null);
      requestAnimationFrame(() => ctxMenuTriggerRef.current?.focus());
    };
    window.addEventListener('click', close);
    window.addEventListener('scroll', close, true);
    window.addEventListener('keydown', closeWithKeyboard);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('keydown', closeWithKeyboard);
    };
  }, []);

  useEffect(() => {
    if (!ctxMenu) return;
    requestAnimationFrame(() => ctxMenuRef.current?.querySelector<HTMLButtonElement>('button')?.focus());
  }, [ctxMenu]);

  useEffect(() => {
    const open = (event: Event) => {
      const detail = (event as CustomEvent).detail || {};
      if (!detail.stock) return;
      const rawX = Number(detail.x || window.innerWidth * 0.5);
      const rawY = Number(detail.y || window.innerHeight * 0.45);
      const x = Math.min(rawX, Math.max(12, window.innerWidth - 260));
      const y = Math.min(rawY, Math.max(12, window.innerHeight - 300));
      setCtxMenu({ x, y, stock: detail.stock });
    };
    window.addEventListener('xuanji-stock-context', open as EventListener);
    return () => window.removeEventListener('xuanji-stock-context', open as EventListener);
  }, []);

  const ctxMenuGoKline = (stock: Stock) => {
    setKlineCode(stock.code);
    setKlineName(stock.name || stock.code);
    setTab('kline');
    setCtxMenu(null);
  };

  const ctxMenuAddWatch = async (stock: Stock) => {
    try {
      const d = await dataApi({ action: 'watchlist_add', code: stock.code });
      window.dispatchEvent(new CustomEvent(WATCHLIST_EVENT, { detail: { codes: d?.codes || [] } }));
      setCtxNotice(`${stock.code} ${stock.name || ''} 已加入自选股`);
      setTimeout(() => setCtxNotice(''), 2200);
    } catch (e: any) {
      setCtxNotice(e?.message || '加入自选股失败');
      setTimeout(() => setCtxNotice(''), 2600);
    }
    setCtxMenu(null);
  };

  const ctxMenuGoValuation = (stock: Stock) => {
    setValuationStock({ code: stock.code, name: stock.name || stock.code });
    setValuationRequestKey(value => value + 1);
    setTab('valuation');
    setCtxMenu(null);
  };

  const ctxMenuGoFinancials = (stock: Stock) => {
    setFinancialStock({ code: stock.code, name: stock.name || stock.code });
    setFinancialRequestKey(value => value + 1);
    setTab('financials');
    setCtxMenu(null);
  };

  const ctxMenuAiAnalysis = async (stock: Stock) => {
    setAiAnalysis({ code: stock.code, name: stock.name || stock.code, loading: true, result: null });
    setCtxMenu(null);
    try {
      const r = await fetch(`${API_BASE}/api/paper`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'ai_stock_evidence', code: stock.code, name: stock.name || stock.code }),
      }).then(r => r.json());
      if (!r?.success) throw new Error(r?.error || 'AI 分析失败');
      setAiAnalysis({ code: stock.code, name: stock.name || stock.code, loading: false, result: r.data });
    } catch (e: any) {
      setAiAnalysis({ code: stock.code, name: stock.name || stock.code, loading: false, result: { error: e.message } });
    }
  };

  const loadQuickCodes = useCallback(async () => {
    try {
      const d = await dataApi({ action: 'watchlist_get' });
      const remote = normalizeWatchCodes(d?.codes);
      const local = readLocalWatchCodes();
      const codes = remote.length ? remote : (local.length ? local : DEFAULT_RT_WATCH);
      const merged = Array.from(new Set(codes));
      setQuickCodes(merged);
    } catch {
      const local = readLocalWatchCodes();
      setQuickCodes(local.length ? local : DEFAULT_RT_WATCH);
    }
  }, []);

  useEffect(() => {
    loadQuickCodes();
    const onWatchlistChanged = (event: Event) => {
      const detail = (event as CustomEvent<{ codes?: string[] }>).detail;
      const codes = normalizeWatchCodes(detail?.codes);
      setQuickCodes(codes.length ? codes : DEFAULT_RT_WATCH);
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === RT_WATCH_KEY) {
        const local = readLocalWatchCodes();
        setQuickCodes(local.length ? local : DEFAULT_RT_WATCH);
      }
    };
    window.addEventListener(WATCHLIST_EVENT, onWatchlistChanged as EventListener);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(WATCHLIST_EVENT, onWatchlistChanged as EventListener);
      window.removeEventListener('storage', onStorage);
    };
  }, [loadQuickCodes]);

  const applyStocksSnapshot = useCallback((payload: any) => {
    const rawList = Array.isArray(payload)
      ? payload
      : (Array.isArray(payload?.stocks) ? payload.stocks : null);
    if (!rawList) return false;
    const normalized: Stock[] = rawList.map((s: any) => ({
      code: s.code ?? '', name: s.name ?? s.code ?? '',
      change_pct: Number(s.change_pct ?? s.pct_change ?? 0),
      volume: Number(s.volume ?? 0), amount: Number(s.amount ?? 0),
      price: Number(s.price ?? 0), change: Number(s.change ?? 0),
      amplitude: Number(s.amplitude ?? 0),
      turnover_rate: optionalNumber(s.turnover_rate),
      main_net_inflow: optionalNumber(s.main_net_inflow),
      main_net_inflow_pct: optionalNumber(s.main_net_inflow_pct),
      money_flow_source: s.money_flow_source ?? null,
      turnover_source: s.turnover_source ?? null,
      latest_time: s.latest_time ?? '',
      source: s.source ?? payload?.source ?? '',
    }));
    setStocks(normalized);
    setStocksMeta({
      source: payload?.source, latest_time: payload?.latest_time,
      latest_date: payload?.latest_date, market_metrics: payload?.market_metrics,
      generation_id: payload?.generation_id, quote_timestamp: payload?.latest_time,
    });
    return true;
  }, []);

  const loadStocks = useCallback(async () => {
    if (stocksLoadingRef.current) return;
    stocksLoadingRef.current = true;
    setLoading(true); setError('');
    try {
      const d = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'stocks', limit: 100, sort_by: 'amount', refresh_if_stale: true }),
      }).then(r => r.json());
      if (d.success && applyStocksSnapshot(d?.data)) {
      } else {
        setError(d.error || '获取失败');
      }
    } catch { setError('网络错误'); }
    finally {
      stocksLoadingRef.current = false;
      setLoading(false);
    }
  }, [applyStocksSnapshot]);

  useEffect(() => { loadStocks(); }, [loadStocks]);
  const onTop100Event = useCallback((event: any) => {
    if (event.type === 'market_top100') applyStocksSnapshot(event.data);
  }, [applyStocksSnapshot]);
  useMarketStream({
    channels: ['market_top100'],
    codes: [],
    enabled: tab === 'browse',
    onEvent: onTop100Event,
    fallback: loadStocks,
    fallbackIntervalMs: 5000,
  });

  const selectQuickStock = useCallback((rawCode: string) => {
    const c = normalizeWatchCode(rawCode);
    if (!c) return;
    const stock = stocks.find(s => s.code === c);
    setCode(c);
    tickFullDayModeRef.current = false;
    setTickFullDayMode(false);
    setTickBackfill(null);
    setTickPage(1);
    setSelectedStock(stock || { code: c, name: '', change_pct: 0, volume: 0, amount: 0, source: 'watchlist' });
    setTab('browse');
  }, [stocks]);

  const selectBrowseStock = useCallback((stock: Stock) => {
    setCode(stock.code);
    tickFullDayModeRef.current = false;
    setTickFullDayMode(false);
    setTickBackfill(null);
    setTickPage(1);
    setSelectedStock(stock);
  }, []);

  const loadTicks = useCallback(async (stock: Stock | null, force = true) => {
    if (!stock?.code) return;
    setTickLoading(true);
    try {
      const d = await dataApi({ action: 'ticks', code: stock.code, limit: 300, trade_date: todayTradeDate(), force_refresh: force });
      if (tickFullDayModeRef.current) return;
      const collectTicks = d?.collect?.items?.[stock.code]?.latest;
      const rawTicks = Array.isArray(d?.ticks) ? d.ticks : (Array.isArray(collectTicks) ? collectTicks : []);
      setTicks(rawTicks.map((t: any) => ({
        code: t.code ?? stock.code,
        date: t.date ?? '',
        time: t.time ?? '',
        price: Number(t.price ?? 0),
        volume: Number(t.volume ?? 0),
        amount: Number(t.amount ?? 0),
        direction: t.direction ?? '',
        source: t.source ?? '',
      })));
      setTickPage(1);
      setTickStats(d?.stats || {});
      setOrderBook(d?.order_book || {});
    } catch {
      setTicks([]);
      setTickPage(1);
      setTickStats({});
      setOrderBook({});
    } finally {
      setTickLoading(false);
    }
  }, []);

  const collectFullDayTicks = useCallback(async (stock: Stock | null) => {
    if (!stock?.code) return;
    setTickBackfillLoading(true);
    setTickBackfill(null);
    try {
      const d = await dataApi({ action: 'tick_collect_full_day', code: stock.code, page_size: 500, max_pages: 80, display_limit: 20000 });
      const rawTicks = Array.isArray(d?.ticks) ? d.ticks : [];
      setTicks(rawTicks.map((t: any) => ({
        code: t.code ?? stock.code,
        date: t.date ?? '',
        time: t.time ?? '',
        price: Number(t.price ?? 0),
        volume: Number(t.volume ?? 0),
        amount: Number(t.amount ?? 0),
        direction: t.direction ?? '',
        source: t.source ?? '',
      })));
      setTickPage(1);
      setTickStats(d?.stats || {});
      setOrderBook(d?.order_book || {});
      tickFullDayModeRef.current = true;
      setTickFullDayMode(true);
      setTickBackfill({
        code: d?.code ?? stock.code,
        trade_date: d?.trade_date ?? '',
        fetched: Number(d?.fetched ?? 0),
        written: Number(d?.written ?? 0),
        stored_count: Number(d?.stored_count ?? 0),
        first_time: d?.first_time ?? '',
        last_time: d?.last_time ?? '',
        complete: Boolean(d?.complete),
        pages: Number(d?.pages ?? 0),
        source: d?.source ?? '',
        source_error: d?.source_error ?? '',
        from_cache: Boolean(d?.from_cache),
      });
    } catch (exc: any) {
      tickFullDayModeRef.current = false;
      setTickFullDayMode(false);
      setTickBackfill({ code: stock.code, error: exc?.message || 'tick full-day backfill failed' });
    } finally {
      setTickBackfillLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab !== 'browse' || !selectedStock || tickFullDayMode) return;
    loadTicks(selectedStock, true);
    const t = setInterval(() => loadTicks(selectedStock, true), 5000);
    return () => clearInterval(t);
  }, [tab, selectedStock, tickFullDayMode, loadTicks]);

  const loadKlines = useCallback(async (c: string) => {
    setKLoading(true); setError('');
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController(); abortRef.current = ctrl;
    try {
      const d = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', signal: ctrl.signal,
        headers: jsonHeaders(),
        body: JSON.stringify({ action: 'klines', code: c, limit: 120, period: klinePeriod, fq: klineFq }),
      }).then(r => r.json());
      // API 返回 { success, data: { code, klines: [{d,o,h,l,c,v,amount}], count, dateRange } }
      const rawList = Array.isArray(d?.data) ? d.data : (Array.isArray(d?.data?.klines) ? d.data.klines : null);
      if (d.success && rawList) {
        setKlineCode(d?.data?.code || c);
        setKlineName(d?.data?.name || '');
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
  }, [klinePeriod, klineFq]);

  useEffect(() => {
    if (tab !== 'kline') return;
    loadKlines(klineCode);
  }, [tab, loadKlines, klineCode]);

  const tabs = [
    { key: 'browse',   label: '市场浏览', icon: BarChart3 },
    { key: 'valuation', label: '股票估值', icon: Scale },
    { key: 'realtime', label: '实时行情', icon: Activity },
    { key: 'financials', label: '财务报表', icon: FileSpreadsheet },
    { key: 'kline',    label: 'K线走势', icon: Clock },
    { key: 'manage',   label: '数据管理', icon: Settings },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <style>{`.data-browser-tabs::-webkit-scrollbar { display: none; }`}</style>
      <ResearchBoundary kind={tab === 'manage' ? 'operations' : 'research'} source="本地 SQLite 行情库、实时行情适配器与同步服务" asOf={stocksMeta.latest_time || stocksMeta.latest_date} error={error} />
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 10, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Database style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 'var(--font-page-title)', fontWeight: 700, color: '#F1F5F9' }}>数据浏览</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>市场行情 · 历史K线 · 实时数据</div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div
        className="data-browser-tabs"
        data-testid="data-browser-tabs"
        style={{ maxWidth: '100%', overflowX: 'auto', scrollbarWidth: 'none' }}
      >
        <div style={{ display: 'flex', gap: 4, background: '#111827', padding: 4, borderRadius: 8, border: '1px solid #1E293B', width: 'max-content', minWidth: 'min(100%, max-content)' }}>
          {tabs.map(t => {
            const Icon = t.icon;
            const is = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key as typeof tab)}
                aria-pressed={is}
                style={{
                  minHeight: 38,
                  flex: '0 0 auto',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '0 14px',
                  borderRadius: 6,
                  border: 'none',
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: is ? 650 : 500,
                  whiteSpace: 'nowrap',
                  background: is ? `${ACCENT}18` : 'transparent',
                  color: is ? ACCENT : '#718199',
                  transition: 'background-color 150ms ease, color 150ms ease',
                }}
              >
                <Icon aria-hidden="true" style={{ width: 14, height: 14 }} />
                {t.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Error */}
      {error && <div style={{ padding: '10px 14px', background: '#EF444414', border: '1px solid #EF444433', borderRadius: 8, fontSize: 12, color: '#F87171' }}>{error}</div>}

      {/* ── Market Browse ── */}
      {tab === 'browse' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Quick chips */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span style={{ fontSize: 11, color: '#475569', marginRight: 4 }}>快速访问（自选股）</span>
            {quickCodes.map(c => (
              <button key={c} onClick={() => selectQuickStock(c)} title="查看逐笔交易"
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
            <button onClick={() => exportCSV(`top100_${new Date().toISOString().slice(0,10)}.csv`,
                ['代码','名称','最新价','涨跌额','涨跌幅','振幅','换手率','主力净流入','主力净占比','成交量','成交额'],
                stocks.map(s => [s.code, s.name, s.price, s.change ?? '', s.change_pct, s.amplitude ?? '', s.turnover_rate ?? '', s.main_net_inflow ?? '', s.main_net_inflow_pct ?? '', s.volume, s.amount]))}
              disabled={stocks.length === 0}
              title="导出当前 Top100 为 CSV (Excel 可直接打开)"
              style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px', borderRadius: 20, border: '1px solid #1E293B', background: 'transparent', color: '#64748B', fontSize: 12, cursor: 'pointer' }}>
              <Download style={{ width: 11, height: 11 }} />导出CSV
            </button>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 12, color: '#94A3B8' }}>
              成交额前 100 · {stocksMeta.source === 'realtime'
                ? `实时快照 ${stocksMeta.latest_time || '--'}`
                : stocksMeta.source === 'realtime_stale'
                  ? `${stocksMeta.latest_date === todayTradeDate() ? '最近完整快照' : '上一交易日快照'} ${stocksMeta.latest_date || '--'}，后台刷新中`
                  : `日线快照 ${stocksMeta.latest_date || '--'}`} · 服务端完整快照推送
              <span style={{ color: '#64748B' }}> · 行情：TdxQuant优先/新浪腾讯降级 · 资金流：东方财富 · 换手率：东方财富/腾讯降级</span>
            </div>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 20, border: '1px solid #1E293B', background: '#0B0F1A' }}>
              <Search style={{ width: 12, height: 12, color: '#64748B' }} />
              <input
                value={searchText}
                onChange={e => setSearchText(e.target.value)}
                placeholder="代码 / 名称 / 拼音首字母"
                style={{ background: 'transparent', border: 'none', outline: 'none', color: '#E2E8F0', fontSize: 12, width: 180, fontFamily: 'inherit' }}
              />
              {searchText && (
                <button onClick={() => setSearchText('')} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: '#64748B' }}>
                  <X style={{ width: 12, height: 12 }} />
                </button>
              )}
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: selectedStock ? 'minmax(460px, 0.9fr) minmax(520px, 1.1fr)' : '1fr', gap: 16, alignItems: 'start' }}>
            {/* Table */}
            <div style={{ minWidth: 0, background: '#111827', borderRadius: 12, border: '1px solid #1E293B', overflowX: 'auto', overflowY: 'hidden' }}>
              <table style={{ width: '100%', minWidth: 1240, borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: '#0B0F1A', borderBottom: '1px solid #1E293B' }}>
                    {([
                      { label: '代码', key: null, align: 'left' },
                      { label: '名称', key: null, align: 'left' },
                      { label: '最新价', key: 'price', align: 'right' },
                      { label: '涨跌额', key: 'change', align: 'right' },
                      { label: '涨跌幅', key: 'change_pct', align: 'right' },
                      { label: '振幅', key: 'amplitude', align: 'right' },
                      { label: '换手率', key: 'turnover_rate', align: 'right' },
                      { label: '主力净流入', key: 'main_net_inflow', align: 'right' },
                      { label: '主力净占比', key: 'main_net_inflow_pct', align: 'right' },
                      { label: '成交量', key: 'volume', align: 'right' },
                      { label: '成交额', key: 'amount', align: 'right' },
                    ] as const).map((col) => {
                      const sortable = col.key !== null;
                      const activeCol = sortable && sortKey === col.key;
                      return (
                        <th
                          key={col.label}
                          onClick={() => { if (!sortable) return; if (activeCol) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortKey(col.key as typeof sortKey); setSortDir('desc'); } }}
                          style={{ padding: '10px 14px', textAlign: col.align, fontSize: 11, fontWeight: 600, color: activeCol ? ACCENT : '#475569', letterSpacing: 0.5, cursor: sortable ? 'pointer' : 'default', userSelect: 'none', whiteSpace: 'nowrap' }}
                        >
                          {col.label}{activeCol ? (sortDir === 'desc' ? ' ↓' : ' ↑') : (sortable ? ' ↕' : '')}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    // 前端排序 + 搜索过滤
                    const filtered = searchText.trim()
                      ? stocks.filter(s => {
                          const q = searchText.trim().toLowerCase();
                          return s.code.toLowerCase().includes(q)
                            || (s.name || '').toLowerCase().includes(q)
                            || (pinyinFirst(s.name || '')).includes(q);
                        })
                      : stocks;
                    const sorted = [...filtered].sort((a, b) => {
                      const av = optionalNumber((a as any)[sortKey]);
                      const bv = optionalNumber((b as any)[sortKey]);
                      return compareNullableNumber(av, bv, sortDir);
                    });
                    return sorted.slice(0, 100);
                  })().map((s) => {
                    const up = s.change_pct > 0;
                    const dn = s.change_pct < 0;
                    const cls = up ? '#F87171' : dn ? '#4ADE80' : '#64748B';
                     const chgVal = Number((s as any).change || 0);
                     const ampVal = Number((s as any).amplitude || 0);
                     const turnoverRate = s.turnover_rate;
                     const mainNetInflow = s.main_net_inflow;
                     const mainNetInflowPct = s.main_net_inflow_pct;
                    const active = selectedStock?.code === s.code;
                    return (
                      <tr key={s.code} onClick={() => selectBrowseStock(s)}
                        onContextMenu={(e) => handleStockContextMenu(e, s)}
                        onMouseDown={(e) => { if (e.button === 2) handleStockContextMenu(e, s); }}
                        onKeyDown={(e) => {
                          if ((e.shiftKey && e.key === 'F10') || e.key === 'ContextMenu') {
                            handleStockContextMenu(e as unknown as React.MouseEvent, s);
                          }
                        }}
                        tabIndex={0}
                        aria-label={`${s.code} ${s.name} Top100 股票操作菜单`}
                        style={{ borderBottom: '1px solid #1E293B44', transition: 'background 100ms', cursor: 'pointer', background: active ? `${ACCENT}10` : 'transparent' }}
                        onMouseEnter={e => (e.currentTarget.style.background = active ? `${ACCENT}16` : '#1E293B55')}
                        onMouseLeave={e => (e.currentTarget.style.background = active ? `${ACCENT}10` : 'transparent')}>
                        <td style={{ padding: '9px 14px', fontFamily: 'JetBrains Mono, monospace', color: '#60A5FA', fontSize: 12 }}>{s.code}</td>
                        <td style={{ padding: '9px 14px', color: '#E2E8F0', fontSize: 12 }}>{s.name}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0', fontSize: 12 }}>{Number(s.price || 0) > 0 ? Number(s.price).toFixed(2) : '--'}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: cls, fontSize: 11 }}>{chgVal !== 0 ? `${chgVal > 0 ? '+' : ''}${chgVal.toFixed(2)}` : '--'}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: cls, fontWeight: 600 }}>
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                            {up ? <TrendingUp style={{ width: 10, height: 10 }} /> : dn ? <TrendingDown style={{ width: 10, height: 10 }} /> : null}
                            {up?'+':''}{s.change_pct.toFixed(2)}%
                          </span>
                        </td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{ampVal > 0 ? `${ampVal.toFixed(2)}%` : '--'}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: '#94A3B8', fontSize: 11 }}>{turnoverRate == null ? '--' : `${turnoverRate.toFixed(2)}%`}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: signedColor(mainNetInflow), fontSize: 11, fontWeight: 600 }}>{mainNetInflow == null ? '--' : fmtSignedAmount(mainNetInflow)}</td>
                        <td style={{ padding: '9px 14px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', color: signedColor(mainNetInflowPct), fontSize: 11 }}>{mainNetInflowPct == null ? '--' : `${mainNetInflowPct > 0 ? '+' : ''}${mainNetInflowPct.toFixed(2)}%`}</td>
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

            {selectedStock && (
              <div style={{ background: '#111827', borderRadius: 12, border: '1px solid #1E293B', overflow: 'hidden' }}>
                <div style={{ padding: '12px 14px', background: '#0B0F1A', borderBottom: '1px solid #1E293B', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <div>
                    <div style={{ color: '#E2E8F0', fontWeight: 700, fontSize: 13 }}>{selectedStock.code} {selectedStock.name}</div>
                    <div style={{ color: '#64748B', fontSize: 11 }}>逐笔交易 · 成交统计 · {tickStats.source === 'tdxrs_transaction' ? 'tdxrs 真逐笔' : 'snapshot fallback'}</div>
                  </div>
                  <button onClick={() => collectFullDayTicks(selectedStock)} disabled={tickBackfillLoading}
                    style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 5, padding: '6px 10px', background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, borderRadius: 7, color: ACCENT, fontSize: 12, cursor: 'pointer' }}>
                    <RefreshCw style={{ width: 12, height: 12, animation: tickBackfillLoading ? 'spin 1s linear infinite' : 'none' }} />补齐今日逐笔
                  </button>
                  <button onClick={() => { tickFullDayModeRef.current = false; setTickFullDayMode(false); loadTicks(selectedStock, true); }} disabled={tickLoading}
                    style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '6px 10px', background: `${ACCENT}18`, border: `1px solid ${ACCENT}44`, borderRadius: 7, color: ACCENT, fontSize: 12, cursor: 'pointer' }}>
                    <RefreshCw style={{ width: 12, height: 12, animation: tickLoading ? 'spin 1s linear infinite' : 'none' }} />刷新
                  </button>
                </div>

                <div style={{ padding: '9px 14px', borderBottom: '1px solid #1E293B', background: tickBackfill?.error ? '#7F1D1D22' : '#0B1220', color: tickBackfill?.error ? '#FCA5A5' : '#94A3B8', fontSize: 11, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                  <span>今日逐笔状态</span>
                  {tickBackfill?.error ? (
                    <span>补齐失败：{tickBackfill.error}</span>
                  ) : tickBackfill ? (
                    <>
                      <span>已入库：{tickBackfill.stored_count ?? 0} 笔</span>
                      <span>新增：{tickBackfill.written ?? 0} 笔</span>
                      {tickBackfill.from_cache ? (
                        <span style={{ color: '#FBBF24' }}>本次拉取：失败，使用已入库数据</span>
                      ) : (
                        <span>拉取笔数/页数：{tickBackfill.fetched ?? 0} / {tickBackfill.pages ?? 0}</span>
                      )}
                      <span>时间范围：{tickBackfill.first_time || '--'} - {tickBackfill.last_time || '--'}</span>
                      <span>完整性：{tickBackfill.complete ? '完整' : '可能未完整'}</span>
                      <span>数据源：{tickBackfill.source || '--'}</span>
                    </>
                  ) : (
                    <span>未补齐，点击“补齐今日逐笔”后显示全日入库和拉取状态</span>
                  )}
                  <span>当前显示：{tickFullDayMode ? `全日 ${ticks.length} 笔` : `最近 ${ticks.length} 笔`}</span>
                </div>

                <div style={{ padding: '7px 14px', borderBottom: '1px solid #1E293B', background: '#0B1220', color: '#CBD5E1', fontSize: 11, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                  <span>分页显示：第 {safeTickPage}/{tickTotalPages} 页</span>
                  <span>本页：{pagedTicks.length} 笔</span>
                  <span>总加载：{ticks.length} 笔</span>
                  <span>模式：{tickFullDayMode ? '全日逐笔' : '最近逐笔'}</span>
                  {tickBackfill?.source_error && <span style={{ color: '#FBBF24' }}>数据源错误：{tickBackfill.source_error}</span>}
                </div>

                {false && tickBackfill && (
                  <div style={{ padding: '9px 14px', borderBottom: '1px solid #1E293B', background: tickBackfill.error ? '#7F1D1D22' : '#0B1220', color: tickBackfill.error ? '#FCA5A5' : '#94A3B8', fontSize: 11, display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                    {tickBackfill.error ? (
                      <span>今日逐笔补齐失败：{tickBackfill.error}</span>
                    ) : (
                      <>
                        <span>今日逐笔已入库：{tickBackfill.stored_count ?? 0} 笔</span>
                        <span>新增：{tickBackfill.written ?? 0} 笔</span>
                        <span>拉取：{tickBackfill.fetched ?? 0} 笔 / {tickBackfill.pages ?? 0} 页</span>
                        <span>时间：{tickBackfill.first_time || '--'} - {tickBackfill.last_time || '--'}</span>
                        <span>完整性：{tickBackfill.complete ? '完整' : '可能未完整'}</span>
                        <span>来源：{tickBackfill.source || '--'}</span>
                      </>
                    )}
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 1, background: '#1E293B', borderBottom: '1px solid #1E293B' }}>
                  {[
                    ['最新价', tickStats.latest_price ? tickStats.latest_price.toFixed(2) : '--'],
                    ['VWAP', tickStats.vwap ? tickStats.vwap.toFixed(2) : '--'],
                    ['成交量', fmtNum(Number(tickStats.total_volume || 0))],
                    ['成交额', fmtNum(Number(tickStats.total_amount || 0))],
                    ['主动买量', fmtNum(Number(tickStats.buy_volume || 0))],
                    ['主动卖量', fmtNum(Number(tickStats.sell_volume || 0))],
                    ['失衡度', `${((Number(tickStats.imbalance || 0)) * 100).toFixed(1)}%`],
                    ['真逐笔数', String(tickStats.true_tick_count ?? tickStats.count ?? 0)],
                  ].map(([k, v]) => (
                    <div key={k} style={{ background: '#111827', padding: '10px 12px' }}>
                      <div style={{ color: '#475569', fontSize: 12 }}>{k}</div>
                      <div style={{ color: '#E2E8F0', fontSize: 13, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', marginTop: 3 }}>{v}</div>
                    </div>
                  ))}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 1, background: '#1E293B', borderBottom: '1px solid #1E293B' }}>
                  <div style={{ background: '#111827', padding: 12 }}>
                    <div style={{ color: '#F87171', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>盘口买卖盘 · 卖盘</div>
                    {(orderBook.asks || []).slice().reverse().map(l => (
                      <div key={`ask-${l.level}`} style={{ display: 'grid', gridTemplateColumns: '42px 1fr 1fr', gap: 8, padding: '4px 0', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
                        <span style={{ color: '#64748B' }}>卖{l.level}</span>
                        <span style={{ color: '#F87171', textAlign: 'right' }}>{l.price > 0 ? l.price.toFixed(2) : '--'}</span>
                        <span style={{ color: '#94A3B8', textAlign: 'right' }}>{l.volume > 0 ? fmtNum(l.volume) : '--'}</span>
                      </div>
                    ))}
                    {!(orderBook.asks || []).length && <div style={{ color: '#475569', fontSize: 11 }}>暂无卖盘快照</div>}
                  </div>
                  <div style={{ background: '#111827', padding: 12 }}>
                    <div style={{ color: '#4ADE80', fontSize: 12, fontWeight: 700, marginBottom: 8 }}>盘口买卖盘 · 买盘</div>
                    {(orderBook.bids || []).map(l => (
                      <div key={`bid-${l.level}`} style={{ display: 'grid', gridTemplateColumns: '42px 1fr 1fr', gap: 8, padding: '4px 0', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
                        <span style={{ color: '#64748B' }}>买{l.level}</span>
                        <span style={{ color: '#4ADE80', textAlign: 'right' }}>{l.price > 0 ? l.price.toFixed(2) : '--'}</span>
                        <span style={{ color: '#94A3B8', textAlign: 'right' }}>{l.volume > 0 ? fmtNum(l.volume) : '--'}</span>
                      </div>
                    ))}
                    {!(orderBook.bids || []).length && <div style={{ color: '#475569', fontSize: 11 }}>暂无买盘快照</div>}
                  </div>
                </div>

                <div style={{ maxHeight: 'calc(100vh - 500px)', minHeight: 420, overflow: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                    <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                      <tr style={{ background: '#0B0F1A', borderBottom: '1px solid #1E293B' }}>
                        {['时间','价格','成交量','成交额','方向','来源'].map((h,i) => (
                          <th key={h} style={{ padding: '9px 10px', textAlign: i>=1 && i<=3 ? 'right' : 'left', color: '#475569', fontSize: 11 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {pagedTicks.map((t, i) => {
                        const isBuy = String(t.direction || '').toUpperCase() === 'B';
                        const isSell = String(t.direction || '').toUpperCase() === 'S';
                        return (
                          <tr key={`${t.date}-${t.time}-${i}`} style={{ borderBottom: '1px solid #1E293B44' }}>
                            <td style={{ padding: '8px 10px', color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace' }}>{t.time}</td>
                            <td style={{ padding: '8px 10px', textAlign: 'right', color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{t.price.toFixed(2)}</td>
                            <td style={{ padding: '8px 10px', textAlign: 'right', color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace' }}>{fmtNum(t.volume)}</td>
                            <td style={{ padding: '8px 10px', textAlign: 'right', color: '#94A3B8', fontFamily: 'JetBrains Mono, monospace' }}>{fmtNum(t.amount)}</td>
                            <td style={{ padding: '8px 10px', color: isBuy ? '#F87171' : isSell ? '#4ADE80' : '#64748B', fontWeight: 700 }}>{isBuy ? '买' : isSell ? '卖' : '中性'}</td>
                            <td style={{ padding: '8px 10px', color: t.source === 'tdxrs_transaction' ? '#60A5FA' : '#FBBF24', fontSize: 11 }}>{t.source || '--'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  <div style={{ position: 'sticky', bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, padding: '9px 12px', background: '#0B0F1A', borderTop: '1px solid #1E293B', color: '#94A3B8', fontSize: 11 }}>
                    <span>逐笔分页：第 {safeTickPage}/{tickTotalPages} 页 · 每页 {tickPageSize} 笔 · 共 {ticks.length} 笔</span>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <button onClick={() => setTickPage(p => Math.max(1, p - 1))} disabled={safeTickPage <= 1}
                        style={{ padding: '5px 10px', borderRadius: 7, border: '1px solid #1E293B', background: safeTickPage <= 1 ? '#0B0F1A' : '#111827', color: safeTickPage <= 1 ? '#475569' : '#CBD5E1', cursor: safeTickPage <= 1 ? 'not-allowed' : 'pointer', fontSize: 11 }}>
                        上一页
                      </button>
                      <button onClick={() => setTickPage(p => Math.min(tickTotalPages, p + 1))} disabled={safeTickPage >= tickTotalPages}
                        style={{ padding: '5px 10px', borderRadius: 7, border: '1px solid #1E293B', background: safeTickPage >= tickTotalPages ? '#0B0F1A' : '#111827', color: safeTickPage >= tickTotalPages ? '#475569' : '#CBD5E1', cursor: safeTickPage >= tickTotalPages ? 'not-allowed' : 'pointer', fontSize: 11 }}>
                        下一页
                      </button>
                    </div>
                  </div>
                  {tickLoading && <div style={{ padding: 18, textAlign: 'center', color: '#64748B', fontSize: 12 }}>逐笔加载中...</div>}
                  {!tickLoading && ticks.length === 0 && <div style={{ padding: 24, textAlign: 'center', color: '#475569', fontSize: 12 }}>暂无逐笔交易</div>}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Stock Valuation ── */}
      {tab === 'valuation' && (
        <ValuationPanel
          initialCode={valuationStock.code}
          initialName={valuationStock.name}
          requestKey={valuationRequestKey}
        />
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
            {/* 周期切换 */}
            <div style={{ display: 'flex', gap: 2, padding: 2, background: '#111827', borderRadius: 8, border: '1px solid #1E293B' }}>
              {[
                { label: '5分', value: '5m' }, { label: '15分', value: '15m' },
                { label: '30分', value: '30m' }, { label: '60分', value: '60min' },
                { label: '日K', value: '1d' }, { label: '周K', value: '1w' }, { label: '月K', value: '1M' },
              ].map(p => {
                const active = klinePeriod === p.value;
                return (
                  <button key={p.value} onClick={() => setKlinePeriod(p.value)}
                    style={{ padding: '6px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                      background: active ? `${ACCENT}22` : 'transparent', color: active ? ACCENT : '#64748B',
                      fontSize: 11, fontWeight: active ? 600 : 400, transition: 'all 100ms' }}>
                    {p.label}
                  </button>
                );
              })}
            </div>
            {/* 复权切换 */}
            <div style={{ display: 'flex', gap: 2, padding: 2, background: '#111827', borderRadius: 8, border: '1px solid #1E293B' }}>
              {[
                { label: '不复权', value: 'none' }, { label: '前复权', value: 'qfq' }, { label: '后复权', value: 'hfq' },
              ].map(f => {
                const active = klineFq === f.value;
                return (
                  <button key={f.value} onClick={() => setKlineFq(f.value)}
                    style={{ padding: '6px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
                      background: active ? `${ACCENT}22` : 'transparent', color: active ? ACCENT : '#64748B',
                      fontSize: 11, fontWeight: active ? 600 : 400, transition: 'all 100ms' }}>
                    {f.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* K线图 */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: '#E2E8F0' }}>K 线走势</div>
            <div style={{ fontSize: 13, color: '#60A5FA', fontFamily: 'JetBrains Mono, monospace' }}>{klineCode}</div>
            {klineName && <div style={{ fontSize: 13, color: '#CBD5E1' }}>{klineName}</div>}
          </div>
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

      {tab === 'financials' && (
        <FinancialStatementsPanel
          initialCode={financialStock.code}
          requestKey={financialRequestKey}
        />
      )}

      {/* ── Data Management (手动/自动更新) ── */}
      {tab === 'manage' && (
        <DataManagePanel />
      )}

      {/* 右键菜单 */}
      {ctxMenu && (
        <div
          ref={ctxMenuRef}
          data-stock-context-menu="true"
          role="menu"
          aria-label={`${ctxMenu.stock.code} ${ctxMenu.stock.name} 股票操作`}
          onClick={(e) => e.stopPropagation()}
          style={{ position: 'fixed', top: ctxMenu.y, left: ctxMenu.x, zIndex: 9999, background: '#1E293B', border: '1px solid #334155', borderRadius: 8, boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: 4, minWidth: 220 }}
        >
          <div style={{ padding: '6px 10px', fontSize: 12, color: '#475569', borderBottom: '1px solid #334155', marginBottom: 4 }}>{ctxMenu.stock.code} {ctxMenu.stock.name}</div>
          <button role="menuitem" onClick={() => ctxMenuAiAnalysis(ctxMenu.stock)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: 6, color: '#CBD5E1', fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            onMouseEnter={e => (e.currentTarget.style.background = '#334155')} onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <Users style={{ width: 14, height: 14, color: '#38BDF8' }} />AI 分析证据
          </button>
          <button role="menuitem" onClick={() => ctxMenuGoValuation(ctxMenu.stock)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: 6, color: '#CBD5E1', fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            onMouseEnter={e => (e.currentTarget.style.background = '#334155')} onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <Scale style={{ width: 14, height: 14, color: '#A78BFA' }} />股票估值
          </button>
          <button role="menuitem" onClick={() => ctxMenuGoFinancials(ctxMenu.stock)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: 6, color: '#CBD5E1', fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            onMouseEnter={e => (e.currentTarget.style.background = '#334155')} onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <FileSpreadsheet style={{ width: 14, height: 14, color: '#38BDF8' }} />财务报表
          </button>
          <button role="menuitem" onClick={() => ctxMenuGoKline(ctxMenu.stock)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: 6, color: '#CBD5E1', fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            onMouseEnter={e => (e.currentTarget.style.background = '#334155')} onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <LineChart style={{ width: 14, height: 14, color: '#F59E0B' }} />K线走势
          </button>
          <button role="menuitem" onClick={() => ctxMenuAddWatch(ctxMenu.stock)} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 10px', background: 'transparent', border: 'none', borderRadius: 6, color: '#CBD5E1', fontSize: 12, cursor: 'pointer', textAlign: 'left' }}
            onMouseEnter={e => (e.currentTarget.style.background = '#334155')} onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
            <Star style={{ width: 14, height: 14, color: '#FBBF24' }} />加入自选股
          </button>
        </div>
      )}

      {ctxNotice && (
        <div style={{ position: 'fixed', right: 20, bottom: 20, zIndex: 10001, background: '#0B0F1A', border: '1px solid #334155', borderRadius: 8, padding: '10px 14px', color: '#CBD5E1', fontSize: 12, boxShadow: '0 8px 24px rgba(0,0,0,0.35)' }}>
          {ctxNotice}
        </div>
      )}

      {/* AI 委员会分析弹窗 */}
      {aiAnalysis && (
        <div onClick={() => setAiAnalysis(null)} style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.6)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} style={{ background: '#111827', border: '1px solid #334155', borderRadius: 12, maxWidth: 600, width: '90%', maxHeight: '80vh', overflow: 'auto', padding: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 16, fontWeight: 700, color: '#E2E8F0' }}>
                  <Users style={{ width: 18, height: 18, color: '#38BDF8' }} />AI 分析证据
                </div>
                <div style={{ fontSize: 12, color: '#64748B', marginTop: 2 }}>{aiAnalysis.code} {aiAnalysis.name} · 只读分析，不构成自动下单指令</div>
              </div>
              <button onClick={() => setAiAnalysis(null)} style={{ background: 'transparent', border: 'none', color: '#64748B', fontSize: 18, cursor: 'pointer' }}>✕</button>
            </div>
            {aiAnalysis.loading ? (
              <div style={{ padding: 30, textAlign: 'center', color: '#64748B', fontSize: 13 }}>分析中...</div>
            ) : aiAnalysis.result?.error ? (
              <div style={{ padding: 16, color: '#F87171', fontSize: 12 }}>获取失败: {aiAnalysis.result.error}</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {aiAnalysis.result?.model && (
                  <div style={{ color: '#64748B', fontSize: 11 }}>
                    实际模型：{aiAnalysis.result.provider || '--'} / {aiAnalysis.result.model} · 来源 {aiAnalysis.result.model_source || '--'}
                  </div>
                )}
                {aiAnalysis.result?.evidenceViews?.map((role: any, i: number) => (
                  <div key={i} style={{ background: '#0B0F1A', borderRadius: 8, padding: 12, borderLeft: '3px solid #38BDF8' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#38BDF8' }}>{i + 1}. {role.title}</div>
                      <div style={{ fontSize: 12, color: '#64748B' }}>{role.focus}</div>
                    </div>
                    <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 6, lineHeight: 1.6 }}>{role.view || '--'}</div>
                  </div>
                ))}
                {aiAnalysis.result?.overall && (
                  <div style={{ background: '#052E2B', borderRadius: 8, padding: 12, borderLeft: '3px solid #10B981' }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: '#10B981' }}>综合研究结论</div>
                    <div style={{ fontSize: 11, color: '#A7F3D0', marginTop: 4 }}>{aiAnalysis.result.overall}</div>
                  </div>
                )}
                {Array.isArray(aiAnalysis.result?.risks) && aiAnalysis.result.risks.length > 0 && (
                  <div style={{ background: '#0B0F1A', borderRadius: 8, padding: 12 }}>
                    <div style={{ fontSize: 11, color: '#64748B' }}>需人工复核的风险</div>
                    <div style={{ fontSize: 11, color: '#94A3B8', marginTop: 4 }}>{aiAnalysis.result.risks.join('；')}</div>
                  </div>
                )}
                {!aiAnalysis.result?.evidenceViews?.length && (
                  <div style={{ padding: 20, textAlign: 'center', color: '#475569', fontSize: 12 }}>当前股票没有可展示的 AI 证据</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }
        @keyframes flash-up { 0%{background:#22C55E33;} 100%{background:transparent;} }
        @keyframes flash-dn { 0%{background:#EF444433;} 100%{background:transparent;} }
        .rt-remove-btn { pointer-events: auto; }
        div:hover > .rt-remove-btn { opacity: 1 !important; }`}</style>
    </div>
  );
};

// ── 实时行情面板 (服务端单飞推送，TdxQuant 优先，新浪/腾讯兜底) ───────────────────
const RealtimePanel: React.FC = () => {
  const [quotes, setQuotes] = useState<Record<string, RTQuote>>({});
  const [flash, setFlash] = useState<Record<string, 'up'|'dn'>>({});
  const [running, setRunning] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>('');
  const [tick, setTick] = useState(0);
  const [quoteStatus, setQuoteStatus] = useState<'connecting' | 'refreshing' | 'live'>('connecting');
  const realtimeLoadingRef = useRef(false);

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
        let localCodes: string[] = [];
        try {
          const saved = localStorage.getItem(RT_WATCH_KEY);
          const arr = saved ? JSON.parse(saved) : [];
          if (Array.isArray(arr)) localCodes = arr.map(normalizeWatchCode).filter(Boolean);
        } catch { /* ignore damaged local cache */ }
        const merged = Array.from(new Set(codes.length ? codes : (localCodes.length ? localCodes : DEFAULT_RT_WATCH)));
        if (merged.length) {
          setWatch(merged);
          dataApi({ action: 'watchlist_set', codes: merged }).catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  // watch 变化时写回 localStorage 作为离线兜底
  useEffect(() => {
    try { localStorage.setItem(RT_WATCH_KEY, JSON.stringify(watch)); } catch { /* 容量满等忽略 */ }
    window.dispatchEvent(new CustomEvent(WATCHLIST_EVENT, { detail: { codes: watch } }));
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

  const applyQuoteSnapshot = useCallback((raw: Record<string, any>, meta: any = {}) => {
    const norm: Record<string, RTQuote> = {};
    for (const [key, value] of Object.entries(raw || {})) {
      const pureCode = key.replace(/^(sh|sz|bj)/, '');
      norm[pureCode] = value as RTQuote;
    }
    setQuotes(prev => {
      const newFlash: Record<string, 'up'|'dn'> = {};
      for (const [code, quote] of Object.entries(norm)) {
        const previousPrice = prev[code]?.price;
        if (previousPrice !== undefined && quote.price > previousPrice) newFlash[code] = 'up';
        else if (previousPrice !== undefined && quote.price < previousPrice) newFlash[code] = 'dn';
      }
      if (Object.keys(newFlash).length) {
        setFlash(newFlash);
        setTimeout(() => setFlash({}), 600);
      }
      return norm;
    });
    const quoteTime = String(meta.quote_timestamp || meta.updated_at || '');
    setLastUpdate(quoteTime || new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    setTick(value => value + 1);
  }, []);

  const poll = useCallback(async () => {
    if (watch.length === 0) { setQuotes({}); return; }
    if (realtimeLoadingRef.current) return;
    realtimeLoadingRef.current = true;
    // 统一走 /api/data → data_runner → market_data.fetch_realtime
    // 市场数据已统一到 Python 数据层, 不再走 /api/market (Node Sina)
    try {
      const r = await fetch(`${API_BASE}/api/data`, {
        method: 'POST', headers: jsonHeaders(),
        body: JSON.stringify({ action: 'realtime_prices', codes: watch, refresh_if_stale: true }),
      }).then(r => r.json());
      if (r.success && r.data) {
        setQuoteStatus(r.stale ? 'refreshing' : 'live');
        applyQuoteSnapshot(r.data, { updated_at: r.updated_at });
      }
    } catch { /* 静默重试 */ }
    finally { realtimeLoadingRef.current = false; }
  }, [applyQuoteSnapshot, watch]);

  const onHotQuoteEvent = useCallback((event: any) => {
    if (event.type !== 'hot_quotes') return;
    const snapshot = event.data || {};
    applyQuoteSnapshot(snapshot.quotes || {}, snapshot);
    setQuoteStatus(snapshot.stale ? 'refreshing' : 'live');
  }, [applyQuoteSnapshot]);
  const quoteStream = useMarketStream({
    channels: ['hot_quotes'],
    codes: watch,
    enabled: running && watch.length > 0,
    onEvent: onHotQuoteEvent,
    fallback: poll,
    fallbackIntervalMs: 2000,
  });

  useEffect(() => { if (running) void poll(); }, [running, poll]);

  const quoteRows = Object.values(quotes) as any[];
  const totalUp = quoteRows.filter(q => q.price > q.close).length;
  const totalDn = quoteRows.filter(q => q.price < q.close).length;
  const totalAmt = quoteRows.reduce((s: number, q: any) => s + Number(q.amount || 0), 0);

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
              {lastUpdate ? `行情时间 ${lastUpdate} · ${tick}次快照` : '连接中...'}
              {quoteStatus === 'refreshing' ? ' · 本地快照，后台刷新中' : quoteStatus === 'live' ? ' · 实时数据' : ''}
              {quoteStream.status === 'degraded' ? ' · 推送中断，降级轮询' : quoteStream.status === 'paused' ? ' · 页面后台暂停' : ''}
              {' · TdxQuant优先 / 新浪腾讯兜底'}
            </div>
          </div>
        </div>
        {/* 汇总统计 */}
        <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#F87171', fontFamily: 'JetBrains Mono, monospace' }}>{totalUp}</div>
            <div style={{ fontSize: 12, color: '#475569' }}>上涨</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 20, fontWeight: 800, color: '#4ADE80', fontFamily: 'JetBrains Mono, monospace' }}>{totalDn}</div>
            <div style={{ fontSize: 12, color: '#475569' }}>下跌</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 16, fontWeight: 700, color: '#E2E8F0', fontFamily: 'JetBrains Mono, monospace' }}>{fmtNum(totalAmt)}</div>
            <div style={{ fontSize: 12, color: '#475569' }}>总成交额</div>
          </div>
          {/* 暂停/继续 */}
          <button onClick={() => setRunning(r => !r)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRadius: 8, border: `1px solid ${running ? '#22C55E44' : '#F59E0B44'}`, background: running ? '#22C55E15' : '#F59E0B15', color: running ? '#22C55E' : '#F59E0B', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>
            <RefreshCw style={{ width: 12, height: 12, animation: running ? 'spin 2s linear infinite' : 'none' }} />
            {running ? '推送中(1s)' : '已暂停'}
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
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: '#475569', fontFamily: 'JetBrains Mono, monospace' }}>
                <span>开{q.open.toFixed(2)}</span>
                <span>高<span style={{color:'#F87171'}}>{q.high.toFixed(2)}</span></span>
                <span>低<span style={{color:'#4ADE80'}}>{q.low.toFixed(2)}</span></span>
              </div>
              <div style={{ fontSize: 12, color: '#475569', fontFamily: 'JetBrains Mono, monospace', marginTop: 4 }}>
                量 {fmtNum(q.volume)} · 额 {fmtNum(q.amount)}
              </div>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: '#475569', textAlign: 'center' }}>
        数据源: Python数据层 / 实时: TdxQuant优先 + 新浪/腾讯兜底 · K线: TdxQuant优先 + 腾讯校验 · 自选股已服务端保存 · 服务端单飞推送
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

// ── 数据管理面板 (统一控制面) ───────────────────────────────
interface UpdateState {
  running: boolean; percent: number; step: string;
  done: number; total: number; ok: number; skip: number; err: number; new_bars: number;
  started_at: string | null; finished_at: string | null; mode: string; pid?: number | null;
  stderr_tail?: string; last_error?: string; codes?: string[]; workers?: number;
}
interface DaemonState {
  enabled: boolean; running: boolean; process_alive: boolean; heartbeat_fresh: boolean;
  heartbeat_age_seconds: number | null; heartbeat_at?: string; last_success_at?: string;
  pid?: number | null; watch_count: number; quote_count?: number; cycle?: number;
  session?: string; source_counts?: Record<string, number>; last_error?: string;
}
interface SourceHealthItem {
  id: string; name: string; status: string; latency_ms?: number | null;
  checked_at?: string; error?: string;
}
interface SyncOverview {
  storage?: { backend: string; key_count: number; db_bytes: number };
  universe_size?: number; kline_count?: number; latest_date?: string;
  source_health?: { sources?: SourceHealthItem[]; summary?: Record<string, number> };
  health?: any; daemon?: DaemonState;
}

const parseSelectedCodes = (value: string) => value
  .split(/[\s,，;；]+/)
  .map(code => code.trim())
  .filter(Boolean);

const DataManagePanel: React.FC = () => {
  const [upd, setUpd] = useState<UpdateState | null>(null);
  const [daemon, setDaemon] = useState<DaemonState | null>(null);
  const [overview, setOverview] = useState<SyncOverview | null>(null);
  const [healthData, setHealthData] = useState<any>(null);
  const [selectedCodes, setSelectedCodes] = useState('');
  const [busy, setBusy] = useState(false);
  const [healthBusy, setHealthBusy] = useState(false);
  const [msg, setMsg] = useState('');

  const postSync = useCallback(async (body: Record<string, any>) => {
    const response = await fetch(`${API_BASE}/api/sync`, {
      method: 'POST', headers: jsonHeaders(), body: JSON.stringify(body),
    });
    return response.json();
  }, []);

  const pollControlPlane = useCallback(async () => {
    try {
      const status = await postSync({ action: 'status' });
      if (status.success) {
        setUpd(status.data?.update || null);
        setDaemon(status.data?.daemon || null);
        setOverview(status.data);
        localStorage.setItem('ac_auto_sync', status.data?.daemon?.enabled ? '1' : '0');
      }
    } catch {}
  }, [postSync]);

  const refreshHealth = useCallback(async (force = false) => {
    setHealthBusy(true);
    try {
      const result = await postSync({ action: 'health', force });
      if (result.success) {
        setHealthData(result);
        setMsg('全市场数据健康与数据源探测已刷新');
      } else {
        setMsg(result.error || '健康检查失败');
      }
    } catch (error: any) {
      setMsg(`健康检查失败: ${error.message}`);
    } finally {
      setHealthBusy(false);
    }
  }, [postSync]);

  useEffect(() => {
    pollControlPlane();
    refreshHealth(false);
    const statusTimer = setInterval(pollControlPlane, 3000);
    const healthTimer = setInterval(() => refreshHealth(false), 300000);
    return () => {
      clearInterval(statusTimer);
      clearInterval(healthTimer);
    };
  }, [pollControlPlane, refreshHealth]);

  const startUpdate = async (mode: 'kline' | 'financial') => {
    setBusy(true); setMsg('');
    try {
      const codes = parseSelectedCodes(selectedCodes);
      const result = await postSync({ action: 'start_update', mode, codes });
      setMsg(result.success
        ? `${mode === 'kline' ? 'K线' : '财务'}更新已启动${codes.length ? `，范围 ${codes.length} 只` : '，范围为全市场'}`
        : (result.error || '启动失败'));
      await pollControlPlane();
    } catch (error: any) {
      setMsg(`网络错误: ${error.message}`);
    } finally {
      setBusy(false);
    }
  };

  const stopUpdate = async () => {
    const result = await postSync({ action: 'stop_update' });
    setMsg(result.success ? '已停止更新' : (result.error || '停止失败'));
    await pollControlPlane();
  };

  const toggleAuto = async () => {
    setBusy(true);
    try {
      const next = !daemon?.enabled;
      const result = await postSync({ action: next ? 'start' : 'stop' });
      setMsg(result.success
        ? (next ? '实时同步守护进程已启动' : '实时同步守护进程已停止')
        : (result.error || '操作失败'));
      await pollControlPlane();
    } catch (error: any) {
      setMsg(`操作失败: ${error.message}`);
    } finally {
      setBusy(false);
    }
  };

  const isRunning = !!upd?.running;
  const pct = upd?.percent || 0;
  const daemonHealthy = !!(daemon?.process_alive && daemon?.heartbeat_fresh);
  const health = healthData?.health || overview?.health || {};
  const source_health = healthData?.source_health || overview?.source_health || {};
  const sourceItems: SourceHealthItem[] = source_health.sources || [];
  const elapsed = upd?.started_at && upd?.finished_at
    ? Math.round((new Date(upd.finished_at).getTime() - new Date(upd.started_at).getTime()) / 1000)
    : (upd?.started_at ? Math.round((Date.now() - new Date(upd.started_at).getTime()) / 1000) : 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: 8, background: `${ACCENT}22`, border: `1px solid ${ACCENT}44`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Settings style={{ width: 20, height: 20, color: ACCENT }} />
          </div>
          <div>
            <div style={{ fontSize: 'var(--font-page-title)', fontWeight: 700, color: '#F1F5F9' }}>数据管理</div>
            <div style={{ fontSize: 11, color: '#64748B' }}>进程控制 · 数据覆盖 · 数据源健康 · 更新审计</div>
          </div>
        </div>
        <button onClick={() => refreshHealth(true)} disabled={healthBusy}
          style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '8px 12px', borderRadius: 7,
            border: '1px solid #334155', background: '#111827', color: '#CBD5E1', cursor: healthBusy ? 'wait' : 'pointer' }}>
          <RefreshCw style={{ width: 14, height: 14, animation: healthBusy ? 'spin 1s linear infinite' : 'none' }} />
          刷新健康状态
        </button>
      </div>

      {msg ? (
        <div style={{ padding: '10px 14px', background: `${ACCENT}14`, border: `1px solid ${ACCENT}33`, borderRadius: 8, fontSize: 12, color: '#FCD34D' }}>{msg}</div>
      ) : null}

      <div style={{ background: '#111827', borderRadius: 8, border: `1px solid ${daemonHealthy ? '#22C55E44' : '#334155'}`, padding: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
            <Power style={{ width: 18, height: 18, color: daemonHealthy ? '#22C55E' : '#64748B' }} />
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>实时行情同步守护进程</div>
              <div style={{ fontSize: 11, color: daemonHealthy ? '#4ADE80' : '#94A3B8', marginTop: 3 }}>
                {daemon ? `${daemonHealthy ? `运行正常 · ${daemon.session || '未知会话'}` : (daemon.process_alive ? '进程存在但心跳异常' : '未运行')} · 监控 ${daemon.watch_count || 0} 只` : '查询中...'}
              </div>
            </div>
          </div>
          <button onClick={toggleAuto} disabled={busy} title={daemon?.enabled ? '停止实时同步' : '启动实时同步'}
            style={{ width: 52, height: 28, borderRadius: 14, border: 'none', cursor: busy ? 'wait' : 'pointer',
              background: daemon?.enabled ? '#22C55E' : '#374151', position: 'relative', transition: 'background 200ms' }}>
            <span style={{ position: 'absolute', top: 3, left: daemon?.enabled ? 27 : 3, width: 22, height: 22, borderRadius: '50%', background: '#fff', transition: 'left 200ms', boxShadow: '0 2px 4px rgba(0,0,0,0.3)' }} />
          </button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10, marginTop: 14 }}>
          <StatBox label="PID" value={daemon?.process_alive && daemon?.pid ? String(daemon.pid) : '—'} />
          <StatBox label="心跳年龄" value={daemon?.heartbeat_age_seconds != null ? `${daemon.heartbeat_age_seconds}s` : '—'} color={daemonHealthy ? '#4ADE80' : '#F87171'} />
          <StatBox label="本轮行情" value={daemon?.quote_count != null ? String(daemon.quote_count) : '—'} />
          <StatBox label="循环次数" value={daemon?.cycle != null ? String(daemon.cycle) : '—'} />
          <StatBox label="最近成功" value={daemon?.last_success_at?.replace('T', ' ').slice(5, 19) || '—'} />
          <StatBox label="数据源分布" value={Object.entries(daemon?.source_counts || {}).map(([k, v]) => `${k}:${v}`).join(' · ') || '—'} />
        </div>
        {daemon?.last_error ? <div style={{ marginTop: 10, color: '#F87171', fontSize: 11 }}>最近错误：{daemon.last_error}</div> : null}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10 }}>
        <StatBox label="存储后端" value={overview?.storage?.backend || '—'} />
        <StatBox label="数据库键数" value={overview?.storage?.key_count?.toLocaleString() || '—'} />
        <StatBox label="数据库容量" value={overview?.storage?.db_bytes ? `${(overview.storage.db_bytes / 1024 / 1024).toFixed(1)} MB` : '—'} />
        <StatBox label="全市场股票池" value={overview?.universe_size?.toLocaleString() || '—'} />
        <StatBox label="K线覆盖股票" value={overview?.kline_count?.toLocaleString() || '—'} color="#4ADE80" />
        <StatBox label="最新K线日期" value={overview?.latest_date || '—'} />
        <StatBox label="健康覆盖率" value={health?.summary?.coverage_pct != null ? `${health.summary.coverage_pct}%` : '—'} color={health?.summary?.issues ? '#FBBF24' : '#4ADE80'} />
        <StatBox label="数据问题数" value={health?.summary?.issues != null ? String(health.summary.issues) : '—'} color={health?.summary?.issues ? '#F87171' : '#4ADE80'} />
      </div>

      <div style={{ background: '#111827', borderRadius: 8, border: '1px solid #1E293B', padding: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0', marginBottom: 12 }}>数据源健康</div>
        {sourceItems.length ? (
          <div style={{ display: 'grid', gap: 7 }}>
            {sourceItems.map(source => (
              <div key={source.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(100px, 1.2fr) 90px 90px minmax(140px, 2fr)', gap: 10, alignItems: 'center', padding: '8px 10px', background: '#0B0F1A', borderRadius: 6, fontSize: 11 }}>
                <span style={{ color: '#CBD5E1' }}>{source.name}</span>
                <span style={{ color: source.status === 'online' ? '#4ADE80' : source.status === 'offline' ? '#F87171' : '#94A3B8' }}>{source.status}</span>
                <span style={{ color: '#94A3B8' }}>{source.latency_ms != null ? `${source.latency_ms}ms` : '—'}</span>
                <span title={source.error || ''} style={{ color: source.error ? '#F87171' : '#475569', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{source.error || source.checked_at || '尚未探测'}</span>
              </div>
            ))}
          </div>
        ) : <div style={{ color: '#64748B', fontSize: 11 }}>尚未执行数据源健康探测。</div>}
      </div>

      <div style={{ background: '#111827', borderRadius: 8, border: '1px solid #1E293B', padding: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0', marginBottom: 12 }}>手动数据更新</div>
        <label style={{ display: 'block', fontSize: 11, color: '#64748B', marginBottom: 6 }}>股票代码范围（留空为全市场，可用逗号或空格分隔）</label>
        <input value={selectedCodes} onChange={event => setSelectedCodes(event.target.value)}
          placeholder="例如：600519, 000001, 300442"
          style={{ width: '100%', height: 36, boxSizing: 'border-box', borderRadius: 7, border: '1px solid #334155', background: '#0B0F1A', color: '#E2E8F0', padding: '0 11px', marginBottom: 12, outline: 'none' }} />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button onClick={() => startUpdate('kline')} disabled={busy || isRunning}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 7, border: `1px solid ${ACCENT}44`, background: `${ACCENT}18`, color: ACCENT, cursor: busy || isRunning ? 'not-allowed' : 'pointer', opacity: busy || isRunning ? 0.5 : 1 }}>
            <Play style={{ width: 14, height: 14 }} />增量更新 K线
          </button>
          <button onClick={() => startUpdate('financial')} disabled={busy || isRunning}
            style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 7, border: '1px solid #818CF844', background: '#818CF818', color: '#818CF8', cursor: busy || isRunning ? 'not-allowed' : 'pointer', opacity: busy || isRunning ? 0.5 : 1 }}>
            <Play style={{ width: 14, height: 14 }} />刷新财务数据
          </button>
          {isRunning ? (
            <button onClick={stopUpdate}
              style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px', borderRadius: 7, border: '1px solid #EF444444', background: '#EF444418', color: '#F87171', cursor: 'pointer' }}>
              <Square style={{ width: 14, height: 14 }} />停止
            </button>
          ) : null}
        </div>
      </div>

      {upd ? (
        <div style={{ background: '#111827', borderRadius: 8, border: `1px solid ${isRunning ? ACCENT + '44' : '#1E293B'}`, padding: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
            <div style={{ fontSize: 14, fontWeight: 600, color: '#E2E8F0' }}>更新进度</div>
            <span style={{ fontSize: 12, fontWeight: 600, color: isRunning ? ACCENT : '#64748B' }}>{isRunning ? `${pct}%` : (upd.finished_at ? '已结束' : '空闲')}</span>
          </div>
          <div style={{ width: '100%', height: 8, background: '#1E293B', borderRadius: 4, overflow: 'hidden', marginBottom: 12 }}>
            <div style={{ width: `${pct}%`, height: '100%', background: isRunning ? ACCENT : (upd.err > 0 ? '#EF4444' : '#22C55E'), transition: 'width 300ms ease' }} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))', gap: 10 }}>
            <StatBox label="当前步骤" value={upd.step || '—'} wide />
            <StatBox label="PID" value={upd.pid ? String(upd.pid) : '—'} />
            <StatBox label="范围" value={upd.codes?.length ? `${upd.codes.length}只` : '全市场'} />
            <StatBox label="进度" value={upd.total > 0 ? `${upd.done}/${upd.total}` : '—'} />
            <StatBox label="成功" value={String(upd.ok)} color="#4ADE80" />
            <StatBox label="跳过" value={String(upd.skip)} />
            <StatBox label="失败" value={String(upd.err)} color={upd.err > 0 ? '#F87171' : '#94A3B8'} />
            <StatBox label="新增K线" value={String(upd.new_bars)} color={ACCENT} />
            <StatBox label="耗时" value={elapsed > 0 ? `${Math.floor(elapsed / 60)}分${elapsed % 60}秒` : '—'} />
          </div>
          {upd.stderr_tail || upd.last_error ? (
            <pre style={{ margin: '12px 0 0', maxHeight: 140, overflow: 'auto', padding: 10, borderRadius: 6, background: '#0B0F1A', color: '#FCA5A5', fontSize: 12, whiteSpace: 'pre-wrap' }}>{upd.stderr_tail || upd.last_error}</pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};

const StatBox: React.FC<{ label: string; value: string; color?: string; wide?: boolean }> = ({ label, value, color, wide }) => (
  <div style={{ background: '#0B0F1A', borderRadius: 8, padding: '10px 12px', gridColumn: wide ? '1 / -1' : 'auto' }}>
    <div style={{ fontSize: 12, color: '#475569', marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 13, fontWeight: 600, color: color || '#E2E8F0', fontFamily: wide ? 'inherit' : 'JetBrains Mono, monospace', whiteSpace: wide ? 'normal' : 'nowrap', overflow: wide ? 'visible' : 'hidden', textOverflow: wide ? 'clip' : 'ellipsis' }}>
      {value}
    </div>
  </div>
);

export default DbPanel;
