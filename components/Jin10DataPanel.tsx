import React, { useEffect, useMemo, useState } from 'react';
import {
  CalendarDays,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  Newspaper,
  Radio,
  RefreshCw,
  Search,
  TrendingUp,
  Wifi,
} from 'lucide-react';
import { syncIntervalMs } from '../lib/data-sync-policy';
import { nextVisibleCount, takeVisibleRows } from '../lib/ui-workbench.mjs';
import { ResearchBoundary } from './ResearchBoundary';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';

type TabKey = 'flash' | 'news' | 'quotes' | 'calendar';

type QuoteRow = {
  code: string;
  name: string;
  close?: string | number;
  high?: string | number;
  low?: string | number;
  open?: string | number;
  ups_percent?: string | number;
  ups_price?: string | number;
  time?: string;
};

type QuoteCodeRow = {
  code: string;
  name?: string;
};

type FeedRow = {
  id?: string | number;
  title?: string;
  content?: string;
  introduction?: string;
  time?: string;
  url?: string;
};

type FeedDetail = FeedRow & {
  image_url?: string;
  images?: string[];
};

type CalendarRow = {
  pub_time?: string;
  star?: number;
  title?: string;
  previous?: string | number | null;
  consensus?: string | number | null;
  actual?: string | number | null;
  revised?: string | number | null;
  affect_txt?: string;
};

type FlashInterpretation = {
  summary?: string;
  market_impact?: string;
  risk_level?: string;
  related_assets?: string[];
  related_sectors?: string[];
  action_hint?: string;
  reason_codes?: string[];
  rationale?: string;
  safety_boundary?: string;
};

const CORE_MACRO_CODES = ['XAUUSD', 'USOIL', 'USDCNH', 'USDJPY'];
const MAX_LIST_ITEMS = 200;
const FEED_BATCH_SIZE = 40;
const DEEP_FEED_PAGES = 10;
const QUOTE_BATCH_SIZE = 20;
const FLASH_REFRESH_MS = syncIntervalMs('jin10_flash');
const NEWS_REFRESH_MS = syncIntervalMs('news_feed');
const CALENDAR_REFRESH_MS = syncIntervalMs('finance_calendar');
const CORE_QUOTES_REFRESH_MS = syncIntervalMs('jin10_core_quotes');
const FULL_QUOTES_REFRESH_MS = syncIntervalMs('jin10_full_quotes');
const TABS: { key: TabKey; label: string; icon: React.ReactNode; accent: string; desc: string }[] = [
  { key: 'flash', label: '市场快讯', icon: <Radio style={{ width: 16, height: 16 }} />, accent: '#F59E0B', desc: '实时市场动态' },
  { key: 'news', label: '新闻资讯', icon: <Newspaper style={{ width: 16, height: 16 }} />, accent: '#A78BFA', desc: '资讯与深度文章' },
  { key: 'quotes', label: '宏观行情', icon: <TrendingUp style={{ width: 16, height: 16 }} />, accent: '#38BDF8', desc: '全部支持品种' },
  { key: 'calendar', label: '财经日历', icon: <CalendarDays style={{ width: 16, height: 16 }} />, accent: '#FB7185', desc: '高星事件与公布值' },
];

function readableJin10Error(value: unknown, fallback = '金十 MCP 请求失败') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text);
    return String(parsed?.message || parsed?.error || text);
  } catch {
    return text;
  }
}

async function callJin10(body: Record<string, unknown>) {
  const res = await fetch(`${API_BASE}/api/jin10`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
    },
    body: JSON.stringify(body),
  });
  const payload = await res.json().catch(() => ({ success: false, error: `HTTP ${res.status} 返回无效 JSON` }));
  if (!res.ok || !payload?.success) {
    throw new Error(readableJin10Error(payload?.error, `金十 MCP 请求失败 (${res.status})`));
  }
  return payload;
}

function itemsOf<T>(payload: any): T[] {
  const directItems = payload?.data?.items;
  if (Array.isArray(directItems)) return directItems;
  const items = payload?.data?.data?.items;
  if (Array.isArray(items)) return items;
  const data = payload?.data?.data;
  if (Array.isArray(data)) return data;
  return [];
}

function errorsOf(payload: any): Array<{ code?: string; error?: string }> {
  const directErrors = payload?.data?.errors;
  if (Array.isArray(directErrors)) return directErrors;
  const nestedErrors = payload?.data?.data?.errors;
  return Array.isArray(nestedErrors) ? nestedErrors : [];
}

function detailOf(payload: any): FeedDetail | null {
  const item = payload?.data?.item ?? payload?.data?.data?.item;
  return item && typeof item === 'object' ? item as FeedDetail : null;
}

function chunkRows<T>(rows: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let index = 0; index < rows.length; index += size) {
    chunks.push(rows.slice(index, index + size));
  }
  return chunks;
}

function feedIdentity(row: FeedRow) {
  return String(row.id || `${row.time || ''}|${row.title || row.content || row.introduction || ''}`);
}

function feedDetailKey(kind: 'flash' | 'news', row: FeedRow) {
  return `${kind}:${feedIdentity(row)}`;
}

function mergeLatestRows<T>(
  current: T[],
  incoming: T[],
  identity: (row: T) => string,
  limit = MAX_LIST_ITEMS,
) {
  const seen = new Set<string>();
  const merged: T[] = [];
  for (const row of [...incoming, ...current]) {
    const key = identity(row);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    merged.push(row);
    if (merged.length >= limit) break;
  }
  return merged;
}

function timeText(value?: string) {
  if (!value) return '--:--';
  const text = String(value);
  if (text.includes('T')) return text.slice(11, 16);
  if (text.length >= 16) return text.slice(5, 16);
  return text;
}

function pctText(value: unknown) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '0.00%';
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function clampText(value?: string, max = 180) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

const inputStyle: React.CSSProperties = {
  height: 38,
  borderRadius: 8,
  border: '1px solid #334155',
  background: '#0B1220',
  color: '#E2E8F0',
  outline: 'none',
  padding: '0 12px',
  fontSize: 13,
};

const Jin10DataPanel: React.FC = () => {
  const [active, setActive] = useState<TabKey>('flash');
  const [query, setQuery] = useState('');
  const [quotes, setQuotes] = useState<QuoteRow[]>([]);
  const [flash, setFlash] = useState<FeedRow[]>([]);
  const [news, setNews] = useState<FeedRow[]>([]);
  const [calendar, setCalendar] = useState<CalendarRow[]>([]);
  const [supportedQuoteCount, setSupportedQuoteCount] = useState(0);
  const [updatedAt, setUpdatedAt] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; row: FeedRow } | null>(null);
  const [aiModal, setAiModal] = useState<{ row: FeedRow; data?: FlashInterpretation; provider?: string; model?: string; modelSource?: string; error?: string } | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [expandedFeedKey, setExpandedFeedKey] = useState('');
  const [feedDetails, setFeedDetails] = useState<Record<string, FeedDetail>>({});
  const [detailLoadingKey, setDetailLoadingKey] = useState('');
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({});

  const activeMeta = TABS.find((tab) => tab.key === active)!;

  const loadSupportedQuoteCodes = async (forceRefresh = false): Promise<QuoteCodeRow[]> => {
    const result = await callJin10({ action: 'codes', force_refresh: forceRefresh });
    const discovered = itemsOf<QuoteCodeRow>(result);
    const unique = new Map<string, QuoteCodeRow>();
    for (const row of discovered) {
      const code = String(row?.code || '').trim().toUpperCase();
      if (code) unique.set(code, { code, name: row.name || code });
    }
    for (const code of CORE_MACRO_CODES) {
      if (!unique.has(code)) unique.set(code, { code, name: code });
    }
    const rows = Array.from(unique.values());
    setSupportedQuoteCount(rows.length);
    return rows;
  };

  const fetchQuoteRows = async (codeRows: QuoteCodeRow[], forceRefresh = false) => {
    const successful: QuoteRow[] = [];
    const quoteErrors: Array<{ code?: string; error?: string }> = [];
    for (const batch of chunkRows(codeRows, QUOTE_BATCH_SIZE)) {
      const result = await callJin10({
        action: 'quotes',
        codes: batch.map((row) => row.code),
        force_refresh: forceRefresh,
      });
      successful.push(...itemsOf<QuoteRow>(result));
      quoteErrors.push(...errorsOf(result));
    }
    const byCode = new Map(successful.map((row) => [String(row.code || '').toUpperCase(), row]));
    const rows = codeRows.map((meta) => ({
      ...meta,
      ...(byCode.get(meta.code) || {}),
      code: meta.code,
      name: byCode.get(meta.code)?.name || meta.name || meta.code,
    }));
    return { rows, successful, quoteErrors };
  };

  const refreshQuotes = async (
    codeQuery = query,
    forceRefresh = false,
    scope: 'all' | 'core' | 'query' = codeQuery.trim() ? 'query' : 'all',
  ) => {
    const codeRows = scope === 'query'
      ? [{ code: codeQuery.trim().toUpperCase(), name: codeQuery.trim().toUpperCase() }]
      : scope === 'core'
        ? CORE_MACRO_CODES.map((code) => ({ code, name: code }))
        : await loadSupportedQuoteCodes(forceRefresh);
    const { rows, successful, quoteErrors } = await fetchQuoteRows(codeRows, forceRefresh);
    if (!successful.length && quoteErrors.length) {
      throw new Error(readableJin10Error(
        quoteErrors[0]?.error,
        `报价品种不可用: ${codeRows.map((row) => row.code).join(', ')}`,
      ));
    }
    if (scope === 'core') {
      setQuotes((current) => {
        if (!current.length) return rows;
        const updates = new Map(rows.map((row) => [row.code, row]));
        return current.map((row) => updates.get(row.code) || row);
      });
    } else {
      setQuotes(rows);
    }
    if (quoteErrors.length) {
      setError(`部分报价失败：${quoteErrors.map((item) => item.code || '未知代码').join('、')}`);
    }
  };

  const refreshFlash = async (keyword = query, forceRefresh = false, deep = false, merge = false) => {
    const body = keyword.trim()
      ? { action: 'flash', keyword: keyword.trim(), pages: deep ? DEEP_FEED_PAGES : 1, force_refresh: forceRefresh }
      : { action: 'flash', pages: deep ? DEEP_FEED_PAGES : 1, force_refresh: forceRefresh };
    const result = await callJin10(body);
    const incoming = itemsOf<FeedRow>(result).slice(0, MAX_LIST_ITEMS);
    setFlash((current) => merge ? mergeLatestRows(current, incoming, feedIdentity) : incoming);
  };

  const refreshNews = async (keyword = query, forceRefresh = false, deep = false, merge = false) => {
    const body = keyword.trim()
      ? { action: 'news', keyword: keyword.trim(), pages: deep ? DEEP_FEED_PAGES : 1, force_refresh: forceRefresh }
      : { action: 'news', pages: deep ? DEEP_FEED_PAGES : 1, force_refresh: forceRefresh };
    const result = await callJin10(body);
    const incoming = itemsOf<FeedRow>(result).slice(0, MAX_LIST_ITEMS);
    setNews((current) => merge ? mergeLatestRows(current, incoming, feedIdentity) : incoming);
  };

  const refreshCalendar = async (forceRefresh = false) => {
    const result = await callJin10({ action: 'calendar', force_refresh: forceRefresh });
    setCalendar(itemsOf<CalendarRow>(result).slice(0, MAX_LIST_ITEMS));
  };

  const toggleFeedDetail = async (kind: 'flash' | 'news', row: FeedRow) => {
    const key = feedDetailKey(kind, row);
    if (expandedFeedKey === key) {
      setExpandedFeedKey('');
      return;
    }

    setExpandedFeedKey(key);
    if (feedDetails[key]) return;

    try {
      setDetailLoadingKey(key);
      setDetailErrors((current) => ({ ...current, [key]: '' }));
      const action = kind === 'news' ? 'news_detail' : 'flash_detail';
      const result = await callJin10({
        action,
        ...(kind === 'news' ? { id: row.id } : { url: row.url }),
      });
      const detail = detailOf(result);
      if (!detail) throw new Error('金十详情返回为空');
      setFeedDetails((current) => ({ ...current, [key]: detail }));
    } catch (e: any) {
      setDetailErrors((current) => ({
        ...current,
        [key]: e?.message || '金十详情加载失败',
      }));
    } finally {
      setDetailLoadingKey('');
    }
  };

  const refreshActive = async (manual = false) => {
    try {
      setLoading(true);
      setError('');
      if (active === 'flash') await refreshFlash(manual ? query : '', manual, manual);
      if (active === 'news') await refreshNews(manual ? query : '', manual, manual);
      if (active === 'quotes') await refreshQuotes(manual ? query : '', manual);
      if (active === 'calendar') await refreshCalendar(manual);
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e: any) {
      setError(e?.message || '金十 MCP 查询异常');
    } finally {
      setLoading(false);
    }
  };

  const refreshAll = async (forceRefresh = false) => {
    try {
      setLoading(true);
      setError('');
      await Promise.all([
        refreshFlash('', forceRefresh, true),
        refreshNews('', forceRefresh, true),
        refreshQuotes('', forceRefresh, 'all'),
        refreshCalendar(forceRefresh),
      ]);
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e: any) {
      setError(e?.message || '金十 MCP 刷新异常');
    } finally {
      setLoading(false);
    }
  };

  const resetActive = async () => {
    setQuery('');
    try {
      setLoading(true);
      setError('');
      if (active === 'flash') await refreshFlash('', false, true);
      if (active === 'news') await refreshNews('', false, true);
      if (active === 'quotes') await refreshQuotes('', false, 'all');
      if (active === 'calendar') await refreshCalendar();
      setUpdatedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (e: any) {
      setError(e?.message || '金十 MCP 重置异常');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    const catchBackgroundRefresh = (reason: unknown) => {
      const message = reason instanceof Error ? reason.message : String(reason || '金十 MCP 自动刷新异常');
      setError(message);
    };
    const coreQuoteTimer = setInterval(() => {
      refreshQuotes('', false, 'core').catch(catchBackgroundRefresh);
    }, CORE_QUOTES_REFRESH_MS);
    const fullQuoteTimer = setInterval(() => {
      refreshQuotes('', false, 'all').catch(catchBackgroundRefresh);
    }, FULL_QUOTES_REFRESH_MS);
    const flashTimer = setInterval(() => {
      refreshFlash('', false, false, true).catch(catchBackgroundRefresh);
    }, FLASH_REFRESH_MS);
    const newsTimer = setInterval(() => {
      refreshNews('', false, false, true).catch(catchBackgroundRefresh);
    }, NEWS_REFRESH_MS);
    const calendarTimer = setInterval(() => {
      refreshCalendar().catch(catchBackgroundRefresh);
    }, CALENDAR_REFRESH_MS);
    return () => {
      clearInterval(coreQuoteTimer);
      clearInterval(fullQuoteTimer);
      clearInterval(flashTimer);
      clearInterval(newsTimer);
      clearInterval(calendarTimer);
    };
  }, []);

  useEffect(() => {
    setQuery('');
    void refreshActive(false);
  }, [active]);

  useEffect(() => {
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    window.addEventListener('scroll', close, true);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('scroll', close, true);
    };
  }, []);

  useEffect(() => {
    const open = (event: Event) => {
      if (active !== 'flash') return;
      const detail = (event as CustomEvent).detail || {};
      if (!detail.row) return;
      setContextMenu({ x: detail.x || 0, y: detail.y || 0, row: detail.row });
    };
    window.addEventListener('jin10-feed-context', open as EventListener);
    return () => window.removeEventListener('jin10-feed-context', open as EventListener);
  }, [active]);

  const interpretFlash = async (row: FeedRow) => {
    setContextMenu(null);
    setAiLoading(true);
    setAiModal({ row });
    try {
      const result = await callJin10({
        action: 'interpret_flash',
        id: row.id,
        time: row.time,
        url: row.url,
        content: row.content || row.title || row.introduction || '',
      });
      if (!result?.success) throw new Error(result?.error || 'AI 解读失败');
      setAiModal({
        row,
        data: result?.data?.interpretation,
        provider: result?.data?.provider,
        model: result?.data?.model,
        modelSource: result?.data?.model_source,
      });
    } catch (e: any) {
      setAiModal({ row, error: e?.message || 'AI 解读失败' });
    } finally {
      setAiLoading(false);
    }
  };

  const copyFlash = async (row: FeedRow) => {
    const text = row.content || row.title || row.introduction || '';
    try {
      await navigator.clipboard?.writeText(text);
    } catch {}
    setContextMenu(null);
  };

  const rowsCount = useMemo(() => {
    if (active === 'flash') return flash.length;
    if (active === 'news') return news.length;
    if (active === 'quotes') return quotes.length;
    return calendar.length;
  }, [active, flash.length, news.length, quotes.length, calendar.length]);
  const quoteCoverage = active === 'quotes' && supportedQuoteCount
    ? ` / 支持 ${supportedQuoteCount} 品种`
    : '';

  const queryPlaceholder = active === 'quotes'
    ? '输入品种代码，如 XAUUSD、USOIL、USDCNH'
    : active === 'calendar'
      ? '财经日历为全量轮询，使用鼠标滚轮浏览'
      : '输入关键词，如 黄金、原油、美联储、通胀';

  return (
    <div className="jin10-panel" style={{ display: 'flex', flexDirection: 'column', gap: 12, width: '100%', minHeight: 'calc(100vh - 96px)' }}>
      <style>{`
        .jin10-header, .jin10-tabs, .jin10-query, .jin10-viewport, .jin10-viewport-head { min-width: 0; }
        .jin10-button { touch-action: manipulation; }
        @media (max-width: 620px) {
          .jin10-panel { gap: 10px !important; min-height: auto !important; }
          .jin10-header { align-items: flex-start !important; padding: 10px !important; }
          .jin10-header-main { min-width: 0; gap: 10px !important; }
          .jin10-header-main h2 { font-size: 18px !important; }
          .jin10-refresh-button { width: 44px; min-width: 44px; height: 44px !important; padding: 0 !important; justify-content: center; }
          .jin10-refresh-label { display: none; }
          .jin10-tabs { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; gap: 8px !important; }
          .jin10-tab { width: 100%; height: 48px !important; min-width: 0; padding: 0 10px !important; }
          .jin10-tab-desc { display: none; }
          .jin10-query { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
          .jin10-query-field { grid-column: 1 / -1; }
          .jin10-query-button { min-width: 0; height: 44px !important; padding: 0 10px !important; }
          .jin10-viewport { flex: 1 1 auto !important; height: auto !important; min-height: 430px !important; }
          .jin10-viewport-head { height: 46px !important; padding: 0 10px !important; }
          .jin10-viewport-desc, .jin10-desktop-hint { display: none; }
          [data-jin10-scroll="true"] { padding: 10px !important; }
          [data-jin10-detail-toggle] { min-height: 44px !important; }
        }
      `}</style>
      <ResearchBoundary kind="external" source="金十数据官方页面 / MCP 接口" />
      <div style={{ padding: '8px 11px', borderLeft: '2px solid #D4A531', background: '#111827', color: '#718096', fontSize: 12, lineHeight: 1.6 }}>
        组合相关优先：快讯与新闻仅作外部背景信息，按持仓、观察池和 A 股相关性优先阅读。来源时间以每条记录为准；仅在存在正文或图示时展开，情绪标签不直接触发交易。
      </div>
      <div className="jin10-header" style={{
        border: '1px solid rgba(212,165,49,0.24)',
        borderRadius: 8,
        background: '#0D1718',
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 16,
      }}>
        <div className="jin10-header-main" style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div style={{
            width: 38,
            height: 38,
            borderRadius: 8,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(13,122,95,0.18)',
            border: '1px solid rgba(13,122,95,0.36)',
            color: '#34D399',
          }}>
            <Wifi style={{ width: 19, height: 19 }} />
          </div>
          <div>
            <h2 style={{ margin: 0, color: '#F8FAFC', fontSize: 20, fontWeight: 900 }}>金十数据</h2>
            <div style={{ marginTop: 3, color: error ? '#F87171' : '#94A3B8', fontSize: 12 }}>
              {error || `实时自动刷新 · 当前 ${activeMeta.label} · ${rowsCount} 条${quoteCoverage} · ${updatedAt || '连接中'}`}
            </div>
          </div>
        </div>
        <button
          className="jin10-button jin10-refresh-button"
          aria-label="全量刷新"
          onClick={() => refreshAll(true)}
          style={{
            height: 34,
            padding: '0 14px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            borderRadius: 8,
            border: '1px solid #334155',
            background: '#0F172A',
            color: '#CBD5E1',
            cursor: 'pointer',
            fontWeight: 800,
          }}
        >
          <RefreshCw style={{ width: 15, height: 15 }} />
          <span className="jin10-refresh-label">全量刷新</span>
        </button>
      </div>

      <div className="jin10-tabs" style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 8,
      }}>
        {TABS.map((tab) => {
          const selected = active === tab.key;
          return (
            <button
              className="jin10-button jin10-tab"
              key={tab.key}
              data-jin10-tab={tab.key}
              onClick={() => setActive(tab.key)}
              style={{
                height: 56,
                borderRadius: 8,
                border: selected ? `1px solid ${tab.accent}` : '1px solid #1E293B',
                background: selected ? `${tab.accent}18` : 'rgba(15,23,42,0.78)',
                color: selected ? '#F8FAFC' : '#94A3B8',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '0 12px',
                textAlign: 'left',
              }}
            >
              <span style={{ width: 30, height: 30, borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center', color: tab.accent, background: `${tab.accent}18` }}>
                {tab.icon}
              </span>
              <span>
                <div style={{ fontSize: 13, fontWeight: 900 }}>{tab.label}</div>
                <div className="jin10-tab-desc" style={{ fontSize: 12, color: '#718096', marginTop: 3 }}>{tab.desc}</div>
              </span>
            </button>
          );
        })}
      </div>

      <div className="jin10-query" style={{
        border: '1px solid #1E293B',
        borderRadius: 8,
        background: 'rgba(15,23,42,0.82)',
        padding: 10,
        display: 'grid',
        gridTemplateColumns: active === 'calendar' ? '1fr auto' : 'minmax(260px, 1fr) auto auto',
        gap: 10,
        alignItems: 'center',
      }}>
        <div className="jin10-query-field" style={{ position: 'relative' }}>
          <Search style={{ width: 15, height: 15, color: '#64748B', position: 'absolute', left: 11, top: 11 }} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={active === 'calendar'}
            placeholder={queryPlaceholder}
            onKeyDown={(e) => {
              if (e.key === 'Enter') refreshActive(true);
            }}
            style={{ ...inputStyle, width: '100%', paddingLeft: 34, opacity: active === 'calendar' ? 0.55 : 1 }}
          />
        </div>
        <button
          className="jin10-button jin10-query-button"
          data-jin10-query-button="true"
          onClick={() => refreshActive(true)}
          disabled={loading}
          style={{
            height: 38,
            borderRadius: 8,
            border: `1px solid ${activeMeta.accent}66`,
            background: `${activeMeta.accent}18`,
            color: '#F8FAFC',
            padding: '0 16px',
            cursor: 'pointer',
            fontWeight: 900,
          }}
        >
          {loading ? '查询中' : '手动查询'}
        </button>
        {active !== 'calendar' && (
          <button
            className="jin10-button jin10-query-button"
            onClick={resetActive}
            style={{
              height: 38,
              borderRadius: 8,
              border: '1px solid #334155',
              background: '#0F172A',
              color: '#94A3B8',
              padding: '0 14px',
              cursor: 'pointer',
              fontWeight: 700,
            }}
          >
            重置
          </button>
        )}
      </div>

      <section className="jin10-viewport" style={{
        flex: '0 0 calc(100vh - 288px)',
        minHeight: 0,
        height: 'calc(100vh - 288px)',
        border: '1px solid #1E293B',
        borderRadius: 8,
        background: 'linear-gradient(180deg, rgba(15,23,42,0.92), rgba(8,13,24,0.96))',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div className="jin10-viewport-head" style={{
          height: 44,
          borderBottom: '1px solid #1E293B',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 14px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ color: activeMeta.accent }}>{activeMeta.icon}</span>
            <span style={{ color: '#F8FAFC', fontSize: 15, fontWeight: 900 }}>{activeMeta.label}</span>
            <span className="jin10-viewport-desc" style={{ color: '#718096', fontSize: 12 }}>{activeMeta.desc}</span>
          </div>
          <div className="jin10-desktop-hint" style={{ color: '#718096', fontSize: 12 }}>鼠标滚轮浏览 · 自动刷新</div>
        </div>

        <div data-jin10-scroll="true" style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 14 }}>
          {active === 'flash' && (
            <FeedList
              kind="flash"
              rows={flash}
              accent="#F59E0B"
              empty="暂无市场快讯"
              expandedKey={expandedFeedKey}
              details={feedDetails}
              loadingKey={detailLoadingKey}
              errors={detailErrors}
              onToggleDetail={toggleFeedDetail}
            />
          )}
          {active === 'news' && (
            <FeedList
              kind="news"
              rows={news}
              accent="#A78BFA"
              empty="暂无新闻资讯"
              expandedKey={expandedFeedKey}
              details={feedDetails}
              loadingKey={detailLoadingKey}
              errors={detailErrors}
              onToggleDetail={toggleFeedDetail}
            />
          )}
          {active === 'quotes' && <QuoteList rows={quotes} />}
          {active === 'calendar' && <CalendarList rows={calendar} />}
        </div>
      </section>

      {contextMenu && (
        <div
          data-jin10-context-menu="true"
          onClick={(e) => e.stopPropagation()}
          style={{
            position: 'fixed',
            left: contextMenu.x,
            top: contextMenu.y,
            zIndex: 50,
            minWidth: 150,
            border: '1px solid #334155',
            borderRadius: 8,
            background: '#0B1220',
            boxShadow: '0 18px 48px rgba(0,0,0,0.38)',
            padding: 6,
          }}
        >
          <button onClick={() => interpretFlash(contextMenu.row)} style={menuButtonStyle}>AI 解读</button>
          <button onClick={() => copyFlash(contextMenu.row)} style={menuButtonStyle}>复制原文</button>
        </div>
      )}

      {aiModal && (
        <div
          data-jin10-ai-modal="true"
          onClick={() => !aiLoading && setAiModal(null)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 60,
            background: 'rgba(2,6,23,0.62)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 'min(760px, 92vw)',
              maxHeight: '82vh',
              overflowY: 'auto',
              border: '1px solid rgba(212,165,49,0.28)',
              borderRadius: 8,
              background: 'linear-gradient(180deg, #0F172A, #08111F)',
              boxShadow: '0 24px 80px rgba(0,0,0,0.46)',
            }}
          >
            <div style={{ padding: 18, borderBottom: '1px solid #1E293B', display: 'flex', justifyContent: 'space-between', gap: 16 }}>
              <div>
                <div style={{ color: '#F8FAFC', fontSize: 18, fontWeight: 900 }}>AI 解读</div>
                <div style={{ color: '#94A3B8', fontSize: 12, marginTop: 5 }}>
                  金十快讯 · {timeText(aiModal.row.time)} · {aiModal.provider || '现有模型'} / {aiModal.model || '--'} · {aiModal.modelSource || '--'}
                </div>
              </div>
              <button onClick={() => !aiLoading && setAiModal(null)} style={{ ...menuButtonStyle, width: 60, justifyContent: 'center' }}>关闭</button>
            </div>
            <div style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 12, background: 'rgba(2,6,23,0.46)', color: '#CBD5E1', lineHeight: 1.65, fontSize: 13 }}>
                {aiModal.row.content || aiModal.row.title || aiModal.row.introduction}
              </div>
              {aiLoading && <div style={{ color: '#D4A531', fontSize: 14 }}>AI 正在解读...</div>}
              {aiModal.error && <div style={{ color: '#F87171', fontSize: 14 }}>{aiModal.error}</div>}
              {aiModal.data && <InterpretationView data={aiModal.data} />}
              <div style={{ color: '#64748B', fontSize: 12, lineHeight: 1.6 }}>
                安全边界：该结果为资讯解释层的影子信号，不直接触发交易，不绕过 verifier / risk gateway。
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const menuButtonStyle: React.CSSProperties = {
  width: '100%',
  height: 34,
  border: '0',
  borderRadius: 6,
  background: 'transparent',
  color: '#E2E8F0',
  display: 'flex',
  alignItems: 'center',
  padding: '0 10px',
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 800,
};

const jin10FeedFontStack = 'Inter, "Noto Sans SC", "Source Han Sans SC", "Microsoft YaHei UI", sans-serif';

function FeedList({
  kind,
  rows,
  accent,
  empty,
  expandedKey,
  details,
  loadingKey,
  errors,
  onToggleDetail,
}: {
  kind: 'flash' | 'news';
  rows: FeedRow[];
  accent: string;
  empty: string;
  expandedKey: string;
  details: Record<string, FeedDetail>;
  loadingKey: string;
  errors: Record<string, string>;
  onToggleDetail: (kind: 'flash' | 'news', row: FeedRow) => void;
}) {
  const [visibleCount, setVisibleCount] = useState(FEED_BATCH_SIZE);

  useEffect(() => {
    setVisibleCount(FEED_BATCH_SIZE);
  }, [kind]);

  useEffect(() => {
    setVisibleCount((current) => Math.min(
      Math.max(FEED_BATCH_SIZE, current),
      Math.max(FEED_BATCH_SIZE, rows.length),
    ));
  }, [rows.length]);

  if (!rows.length) return <Empty text={empty} />;
  const visibleRows = takeVisibleRows(rows, visibleCount);
  const hasMore = visibleRows.length < rows.length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontFamily: jin10FeedFontStack }}>
      {visibleRows.map((row) => {
        const key = feedDetailKey(kind, row);
        const detail = details[key];
        const isExpanded = expandedKey === key;
        const isLoading = loadingKey === key;
        const detailError = errors[key];
        const title = String(row.title || '').trim();
        const content = String(row.content || '').trim();
        const introduction = String(row.introduction || '').trim();
        const canLoadDetail = kind === 'news' ? Boolean(row.id) : Boolean(row.url);
        const detailImages = Array.from(new Set([
          ...(detail?.images || []),
          ...(detail?.image_url ? [detail.image_url] : []),
        ].filter(Boolean)));
        const detailContent = String(detail?.content || '').trim();
        const showDetailContent = detailContent
          && detailContent !== content
          && detailContent !== title;

        return (
          <article
            key={`${kind}:${feedIdentity(row)}`}
            onContextMenu={(event) => {
              event.preventDefault();
              window.dispatchEvent(new CustomEvent('jin10-feed-context', {
                detail: {
                  row,
                  x: event.clientX,
                  y: event.clientY,
                },
              }));
            }}
            style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 14, background: 'rgba(2,6,23,0.38)', cursor: 'context-menu' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 8 }}>
              <span style={{ color: accent, fontSize: 12, fontWeight: 700 }}>{timeText(row.time)}</span>
              <span style={{ color: '#596579', fontSize: 11, fontWeight: 500 }}>Jin10 MCP</span>
            </div>

            {row.title && (
              <div style={{ color: '#E7EDF5', fontSize: 14, lineHeight: 1.72, fontWeight: 700 }}>
                {clampText(title, 260)}
              </div>
            )}
            {row.content && content !== title && (
              <div style={{ color: title ? '#B8C3D1' : '#D6DEE9', fontSize: 13, lineHeight: 1.72, marginTop: title ? 7 : 0, fontWeight: title ? 400 : 600 }}>
                {clampText(content, 320)}
              </div>
            )}
            {!row.title && !row.content && row.introduction && (
              <div style={{ color: '#D6DEE9', fontSize: 14, lineHeight: 1.72, fontWeight: 600 }}>
                {clampText(introduction, 260)}
              </div>
            )}
            {row.introduction && introduction !== title && introduction !== content && (
              <div style={{ color: '#9AA7B8', fontSize: 13, lineHeight: 1.68, marginTop: 8, fontWeight: 400 }}>
                {clampText(introduction, 220)}
              </div>
            )}

            {(canLoadDetail || row.url) && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                {canLoadDetail && (
                  <button
                    data-jin10-detail-toggle={key}
                    onClick={() => onToggleDetail(kind, row)}
                    disabled={isLoading}
                    style={{
                      minHeight: 32,
                      borderRadius: 6,
                      border: `1px solid ${accent}55`,
                      background: `${accent}12`,
                      color: isLoading ? '#64748B' : accent,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 6,
                      padding: '0 10px',
                      cursor: isLoading ? 'wait' : 'pointer',
                      fontSize: 12,
                      fontWeight: 800,
                    }}
                  >
                    {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    {isLoading ? '加载中' : isExpanded ? '收起' : kind === 'flash' ? '展开正文/图示' : '阅读全文'}
                  </button>
                )}
                {row.url && (
                  <a
                    href={row.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: '#7F8CA0', fontSize: 12, fontWeight: 700, display: 'inline-flex', alignItems: 'center', gap: 5, textDecoration: 'none' }}
                  >
                    <ExternalLink size={13} />
                    金十原文
                  </a>
                )}
              </div>
            )}

            {isExpanded && (
              <div
                data-jin10-detail-panel={key}
                style={{
                  marginTop: 12,
                  borderTop: '1px solid #1E293B',
                  paddingTop: 12,
                  display: 'grid',
                  gap: 12,
                }}
              >
                {isLoading && <div style={{ color: '#94A3B8', fontSize: 13 }}>正在读取详情...</div>}
                {detailError && <div style={{ color: '#F87171', fontSize: 13 }}>{detailError}</div>}
                {detailImages.map((imageUrl) => (
                  <img
                    key={imageUrl}
                    data-jin10-detail-image="true"
                    src={imageUrl}
                    alt={detail?.title || title || '金十图示'}
                    loading="lazy"
                    style={{
                      display: 'block',
                      width: '100%',
                      maxHeight: 720,
                      objectFit: 'contain',
                      borderRadius: 6,
                      background: '#020617',
                    }}
                  />
                ))}
                {showDetailContent && (
                  <div style={{
                    color: '#CBD5E1',
                    fontSize: 13,
                    lineHeight: 1.8,
                    whiteSpace: 'pre-wrap',
                    maxHeight: 560,
                    overflowY: 'auto',
                    paddingRight: 6,
                  }}>
                    {detailContent}
                  </div>
                )}
                {!isLoading && !detailError && detail && !detailImages.length && !showDetailContent && (
                  <div style={{ color: '#94A3B8', fontSize: 13 }}>该条详情仅提供原文链接。</div>
                )}
              </div>
            )}
          </article>
        );
      })}
      {hasMore && (
        <button
          type="button"
          className="jin10-button"
          onClick={() => setVisibleCount((current) => nextVisibleCount(current, rows.length, FEED_BATCH_SIZE))}
          style={{
            minHeight: 44,
            border: '1px solid #334155',
            borderRadius: 7,
            color: '#CBD5E1',
            background: '#0F172A',
            cursor: 'pointer',
            fontSize: 13,
            fontWeight: 800,
          }}
        >
          继续加载 {Math.min(FEED_BATCH_SIZE, rows.length - visibleRows.length)} 条
          <span style={{ marginLeft: 8, color: '#94A3B8', fontWeight: 500 }}>
            已显示 {visibleRows.length} / {rows.length}
          </span>
        </button>
      )}
    </div>
  );
}

function InterpretationView({ data }: { data: FlashInterpretation }) {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
        <InfoBlock label="摘要" value={data.summary || '-'} strong />
        <InfoBlock label="影响判断" value={data.market_impact || '-'} />
        <InfoBlock label="风险级别" value={data.risk_level || '-'} />
        <InfoBlock label="操作提示" value={data.action_hint || '-'} />
      </div>
      <TagBlock label="相关资产" items={data.related_assets || []} color="#38BDF8" />
      <TagBlock label="相关板块" items={data.related_sectors || []} color="#A78BFA" />
      <TagBlock label="原因代码" items={data.reason_codes || []} color="#D4A531" />
      <InfoBlock label="模型推理" value={data.rationale || '-'} />
    </div>
  );
}

function InfoBlock({ label, value, strong = false }: { label: string; value: string; strong?: boolean }) {
  return (
    <div style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 12, background: 'rgba(15,23,42,0.62)' }}>
      <div style={{ color: '#64748B', fontSize: 11, fontWeight: 900, marginBottom: 7 }}>{label}</div>
      <div style={{ color: strong ? '#F8FAFC' : '#CBD5E1', fontSize: 13, lineHeight: 1.65, fontWeight: strong ? 900 : 700 }}>
        {value}
      </div>
    </div>
  );
}

function TagBlock({ label, items, color }: { label: string; items: string[]; color: string }) {
  return (
    <div style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 12, background: 'rgba(15,23,42,0.48)' }}>
      <div style={{ color: '#64748B', fontSize: 11, fontWeight: 900, marginBottom: 8 }}>{label}</div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {(items.length ? items : ['-']).map((item, index) => (
          <span key={`${item || '-'}-${index}`} style={{ border: `1px solid ${color}55`, borderRadius: 999, color, padding: '4px 9px', fontSize: 12, fontWeight: 800 }}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function QuoteList({ rows }: { rows: QuoteRow[] }) {
  if (!rows.length) return <Empty text="暂无宏观行情" />;
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
      {rows.map((row) => {
        const pct = Number(row.ups_percent || 0);
        const color = pct > 0 ? '#EF4444' : pct < 0 ? '#22C55E' : '#CBD5E1';
        return (
          <article key={row.code} style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 16, background: 'rgba(2,6,23,0.44)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
              <div>
                <div style={{ color: '#F8FAFC', fontSize: 18, fontWeight: 900 }}>{row.code}</div>
                <div style={{ color: '#94A3B8', fontSize: 13, marginTop: 4 }}>{row.name || row.code}</div>
              </div>
              <div style={{ textAlign: 'right' }}>
                <div style={{ color: '#F8FAFC', fontSize: 20, fontWeight: 900, fontFamily: 'JetBrains Mono, monospace' }}>{row.close || '-'}</div>
                <div style={{ color, fontSize: 14, fontWeight: 900, fontFamily: 'JetBrains Mono, monospace' }}>{pctText(row.ups_percent)}</div>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginTop: 16 }}>
              {[
                ['Open', row.open],
                ['High', row.high],
                ['Low', row.low],
              ].map(([label, value]) => (
                <div key={label} style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 10, background: '#0B1220' }}>
                  <div style={{ color: '#64748B', fontSize: 11 }}>{label}</div>
                  <div style={{ color: '#CBD5E1', fontSize: 13, fontWeight: 800, marginTop: 4 }}>{value || '-'}</div>
                </div>
              ))}
            </div>
            <div style={{ color: '#64748B', fontSize: 12, marginTop: 12 }}>更新时间 {timeText(row.time)}</div>
          </article>
        );
      })}
    </div>
  );
}

function CalendarList({ rows }: { rows: CalendarRow[] }) {
  if (!rows.length) return <Empty text="暂无财经日历" />;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {rows.map((row, index) => (
        <article key={`${row.pub_time || index}-${row.title || index}`} style={{ border: '1px solid #1E293B', borderRadius: 8, padding: 14, background: 'rgba(2,6,23,0.44)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '96px 1fr 80px', gap: 12, alignItems: 'center' }}>
            <div style={{ color: '#FB7185', fontSize: 13, fontWeight: 900 }}>{timeText(row.pub_time)}</div>
            <div>
              <div style={{ color: '#F8FAFC', fontSize: 14, fontWeight: 900, lineHeight: 1.55 }}>{row.title || '财经事件'}</div>
              <div style={{ color: '#94A3B8', fontSize: 12, marginTop: 6 }}>
                前值 {row.previous ?? '-'} / 预期 {row.consensus ?? '-'} / 实际 {row.actual ?? '未公布'}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ color: '#D4A531', fontSize: 12 }}>{'★'.repeat(Math.min(4, Number(row.star || 0))) || '待'}</div>
              <div style={{ color: '#CBD5E1', fontSize: 12, marginTop: 6 }}>{row.affect_txt || '待公布'}</div>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return (
    <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#64748B', fontSize: 14 }}>
      {text}
    </div>
  );
}

export default Jin10DataPanel;
