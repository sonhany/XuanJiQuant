import React, { useEffect, useRef, useState } from 'react';
import {
  BellRing,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileSearch,
  RefreshCw,
  RotateCcw,
  Search,
  X,
} from 'lucide-react';
import { ResearchBoundary } from './ResearchBoundary';
import { syncIntervalMs } from '../lib/data-sync-policy';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const API_TOKEN = (import.meta as any).env?.VITE_XUANJI_API_TOKEN || '';
const CNINFO_INFLIGHT = new Map<string, Promise<unknown>>();
const CNINFO_POLL_MS = syncIntervalMs('cninfo_latest');

type Preset = 'latest' | 'performance_express' | 'performance_forecast' | 'periodic_report';

type Disclosure = {
  id: string;
  code: string;
  name: string;
  title: string;
  announcement_date: string;
  announcement_time?: number;
  tags?: string[];
  pdf_url?: string;
  detail_url?: string;
};

type QueryResult = {
  items: Disclosure[];
  count: number;
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
  cached: boolean;
  fetched_at?: string;
};

type DisclosureDetail = {
  content: string;
  page_count: number;
  truncated: boolean;
  cached: boolean;
  pdf_url: string;
  fetched_at?: string;
};

const PRESETS: Array<{ value: Preset; label: string; description: string }> = [
  { value: 'latest', label: '最新公告', description: '全部法定披露' },
  { value: 'performance_express', label: '业绩快报', description: '未经审计快报' },
  { value: 'performance_forecast', label: '业绩预告', description: '区间与方向预告' },
  { value: 'periodic_report', label: '业绩公告', description: '年报 / 半年报 / 季报' },
];

function localDate(offsetDays = 0) {
  const current = new Date();
  current.setHours(12, 0, 0, 0);
  current.setDate(current.getDate() + offsetDays);
  const year = current.getFullYear();
  const month = String(current.getMonth() + 1).padStart(2, '0');
  const day = String(current.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

async function callCninfo<T = QueryResult>(body: Record<string, unknown>): Promise<T> {
  const requestBody = JSON.stringify(body);
  const requestKey = `${API_BASE}/api/cninfo:${requestBody}`;
  const existing = CNINFO_INFLIGHT.get(requestKey);
  if (existing) return existing as Promise<T>;

  const request = (async () => {
    const response = await fetch(`${API_BASE}/api/cninfo`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
      },
      body: requestBody,
    });
    const payload = await response.json().catch(() => ({ success: false, error: `HTTP ${response.status} 返回了无效 JSON` }));
    if (!response.ok || !payload?.success) {
      throw new Error(payload?.error || `巨潮公告查询失败 (${response.status})`);
    }
    return payload.data as T;
  })();

  CNINFO_INFLIGHT.set(requestKey, request);
  try {
    return await request as T;
  } finally {
    if (CNINFO_INFLIGHT.get(requestKey) === request) CNINFO_INFLIGHT.delete(requestKey);
  }
}

function cleanError(value: unknown) {
  return String(value || '巨潮公告查询失败').replace(/^CNINFO disclosure error:\s*/i, '').slice(0, 240);
}

const CninfoDisclosurePanel: React.FC = () => {
  const defaultStartRef = useRef(localDate(-7));
  const defaultEndRef = useRef(localDate(0));
  const [preset, setPreset] = useState<Preset>('latest');
  const [code, setCode] = useState('');
  const [keyword, setKeyword] = useState('');
  const [startDate, setStartDate] = useState(defaultStartRef.current);
  const [endDate, setEndDate] = useState(defaultEndRef.current);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState('');
  const [newCount, setNewCount] = useState(0);
  const [selected, setSelected] = useState<Disclosure | null>(null);
  const [detail, setDetail] = useState<DisclosureDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const latestIdsRef = useRef<Set<string>>(new Set());
  const pollInFlightRef = useRef(false);
  const filtersRef = useRef({ preset, code, keyword, startDate, endDate });
  filtersRef.current = { preset, code, keyword, startDate, endDate };

  const runQuery = async (
    nextPreset = preset,
    page = 1,
    forceRefresh = false,
    filters?: { code?: string; keyword?: string; startDate?: string; endDate?: string },
    background = false,
  ) => {
    try {
      if (background) setSyncing(true);
      else setLoading(true);
      setError('');
      const data = await callCninfo({
        action: 'query',
        preset: nextPreset,
        code: filters?.code ?? code,
        keyword: filters?.keyword ?? keyword,
        start_date: filters?.startDate ?? startDate,
        end_date: filters?.endDate ?? endDate,
        page,
        page_size: 30,
        force_refresh: forceRefresh,
      });
      if (background && latestIdsRef.current.size) {
        setNewCount(data.items.filter((item) => item.id && !latestIdsRef.current.has(item.id)).length);
      }
      latestIdsRef.current = new Set(data.items.map((item) => item.id).filter(Boolean));
      setResult(data);
    } catch (queryError) {
      setError(cleanError(queryError instanceof Error ? queryError.message : queryError));
      setResult(null);
    } finally {
      if (background) setSyncing(false);
      else setLoading(false);
    }
  };

  useEffect(() => {
    const poll = async (forceRefresh: boolean) => {
      const filters = filtersRef.current;
      const isLivePreset = !filters.code
        && !filters.keyword
        && filters.startDate === defaultStartRef.current
        && filters.endDate === defaultEndRef.current;
      if (!isLivePreset || document.visibilityState !== 'visible' || pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      try {
        await runQuery(filters.preset, 1, forceRefresh, filters, true);
      } finally {
        pollInFlightRef.current = false;
      }
    };
    poll(false);
    const timer = window.setInterval(() => poll(true), CNINFO_POLL_MS);
    return () => window.clearInterval(timer);
  }, []);

  const openDetail = async (item: Disclosure) => {
    setSelected(item);
    setDetail(null);
    setDetailError('');
    setDetailLoading(true);
    try {
      const data = await callCninfo<DisclosureDetail>({
        action: 'detail',
        pdf_url: item.pdf_url,
        title: item.title,
        code: item.code,
        name: item.name,
      });
      setDetail(data);
    } catch (detailFailure) {
      setDetailError(cleanError(detailFailure instanceof Error ? detailFailure.message : detailFailure));
    } finally {
      setDetailLoading(false);
    }
  };

  const selectPreset = (nextPreset: Preset) => {
    setPreset(nextPreset);
    setResult(null);
    setError('');
    setNewCount(0);
    latestIdsRef.current = new Set();
    void runQuery(nextPreset, 1, false, { code, keyword, startDate, endDate });
  };

  const resetFilters = () => {
    const nextStart = defaultStartRef.current;
    const nextEnd = defaultEndRef.current;
    setCode('');
    setKeyword('');
    setStartDate(nextStart);
    setEndDate(nextEnd);
      setResult(null);
    setError('');
  };

  const updatedText = result?.fetched_at
    ? new Date(result.fetched_at).toLocaleString('zh-CN', { hour12: false })
    : '等待查询';

  return (
    <div className="cninfo-panel">
      <style>{`
        .cninfo-panel { display: flex; flex-direction: column; gap: 12px; width: 100%; min-width: 0; min-height: calc(100vh - 156px); }
        .cninfo-panel button, .cninfo-panel input { font: inherit; }
        .cninfo-panel button:focus-visible, .cninfo-panel input:focus-visible { outline: 2px solid #38BDF8; outline-offset: 2px; }
        .cninfo-header { min-width: 0; display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 13px 15px; border: 1px solid #1E293B; border-radius: 8px; background: #0D1422; }
        .cninfo-title-block { min-width: 0; display: flex; align-items: center; gap: 11px; }
        .cninfo-title-icon { width: 36px; height: 36px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #164E63; border-radius: 7px; color: #38BDF8; background: #082F49; }
        .cninfo-title-icon svg { width: 18px; height: 18px; }
        .cninfo-title-copy { min-width: 0; }
        .cninfo-title-copy h2 { margin: 0; color: #F8FAFC; font-size: 18px; line-height: 1.25; }
        .cninfo-title-copy p { margin: 4px 0 0; color: #64748B; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .cninfo-live-state { display: inline-flex; align-items: center; gap: 5px; color: #67E8F9; }
        .cninfo-live-state svg { width: 12px; height: 12px; }
        .cninfo-icon-button { width: 36px; height: 36px; flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #334155; border-radius: 7px; color: #94A3B8; background: #0F172A; cursor: pointer; }
        .cninfo-icon-button:hover { color: #E2E8F0; background: #172033; }
        .cninfo-icon-button:disabled { cursor: wait; opacity: 0.5; }
        .cninfo-icon-button svg { width: 16px; height: 16px; }
        .cninfo-presets { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 7px; }
        .cninfo-preset { min-width: 0; height: 50px; padding: 0 12px; border: 1px solid #1E293B; border-radius: 7px; color: #64748B; background: #0F172A; cursor: pointer; text-align: left; }
        .cninfo-preset:hover { color: #CBD5E1; border-color: #334155; }
        .cninfo-preset[data-active="true"] { color: #E2E8F0; border-color: #0E7490; background: #102331; }
        .cninfo-preset strong, .cninfo-preset span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .cninfo-preset strong { font-size: 12px; }
        .cninfo-preset span { margin-top: 3px; color: #64748B; font-size: 11px; }
        .cninfo-query { display: grid; grid-template-columns: minmax(120px, 0.8fr) minmax(180px, 1.5fr) minmax(138px, 0.85fr) minmax(138px, 0.85fr) 38px 84px; gap: 8px; align-items: end; padding: 11px; border: 1px solid #1E293B; border-radius: 8px; background: #0B1220; }
        .cninfo-field { min-width: 0; }
        .cninfo-field label { display: block; margin-bottom: 5px; color: #64748B; font-size: 11px; }
        .cninfo-field input { width: 100%; height: 36px; box-sizing: border-box; border: 1px solid #334155; border-radius: 6px; padding: 0 10px; color: #E2E8F0; background: #0F172A; font-size: 12px; }
        .cninfo-field input::placeholder { color: #475569; }
        .cninfo-query-button { height: 36px; display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid #0E7490; border-radius: 6px; color: #E0F2FE; background: #0E5A70; cursor: pointer; font-size: 12px; font-weight: 700; }
        .cninfo-query-button:disabled { cursor: wait; opacity: 0.55; }
        .cninfo-query-button svg { width: 14px; height: 14px; }
        .cninfo-error { padding: 9px 11px; border: 1px solid #7F1D1D; border-radius: 6px; color: #FCA5A5; background: #240E12; font-size: 11px; line-height: 1.5; }
        .cninfo-list { min-width: 0; border: 1px solid #1E293B; border-radius: 8px; overflow: hidden; background: #0B1220; }
        .cninfo-list-head, .cninfo-row { display: grid; grid-template-columns: 130px minmax(260px, 1fr) 110px 54px; align-items: center; column-gap: 12px; }
        .cninfo-list-head { min-height: 38px; padding: 0 13px; color: #64748B; background: #111827; font-size: 11px; }
        .cninfo-list-body { max-height: calc(100vh - 450px); min-height: 260px; overflow-y: auto; }
        .cninfo-row { min-height: 59px; padding: 8px 13px; border-top: 1px solid #182235; content-visibility: auto; contain-intrinsic-size: 59px; }
        .cninfo-row:hover { background: #101827; }
        .cninfo-company { min-width: 0; }
        .cninfo-company strong, .cninfo-company span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .cninfo-company strong { color: #CBD5E1; font-size: 12px; font-variant-numeric: tabular-nums; }
        .cninfo-company span { margin-top: 3px; color: #64748B; font-size: 11px; }
        .cninfo-announcement { min-width: 0; }
        .cninfo-announcement-title { width: 100%; padding: 0; border: 0; color: #D6DEE9; background: transparent; cursor: pointer; font-size: 12px; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; text-align: left; }
        .cninfo-announcement-title:hover { color: #7DD3FC; }
        .cninfo-tags { display: flex; gap: 5px; margin-top: 4px; overflow: hidden; }
        .cninfo-tag { flex: 0 0 auto; padding: 1px 5px; border: 1px solid #334155; border-radius: 4px; color: #7890A8; font-size: 11px; }
        .cninfo-date { color: #94A3B8; font-size: 11px; font-variant-numeric: tabular-nums; }
        .cninfo-original-link { width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; color: #38BDF8; text-decoration: none; }
        .cninfo-original-link:hover { background: #123044; }
        .cninfo-original-link svg { width: 15px; height: 15px; }
        .cninfo-status { min-height: 42px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 12px; border-top: 1px solid #1E293B; color: #64748B; background: #0F172A; font-size: 11px; }
        .cninfo-pagination { display: flex; align-items: center; gap: 5px; }
        .cninfo-page-button { width: 30px; height: 30px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #334155; border-radius: 6px; color: #94A3B8; background: transparent; cursor: pointer; }
        .cninfo-page-button:disabled { cursor: default; opacity: 0.35; }
        .cninfo-page-button svg { width: 14px; height: 14px; }
        .cninfo-page-label { min-width: 48px; text-align: center; font-variant-numeric: tabular-nums; }
        .cninfo-loading, .cninfo-empty { min-height: 260px; display: flex; align-items: center; justify-content: center; padding: 24px; color: #64748B; text-align: center; }
        .cninfo-skeletons { width: 100%; padding: 0 13px; box-sizing: border-box; }
        .cninfo-skeleton { height: 42px; margin: 12px 0; border-radius: 6px; background: #172033; opacity: 0.75; }
        .cninfo-empty svg { width: 26px; height: 26px; margin-bottom: 10px; color: #475569; }
        .cninfo-empty p { margin: 0 0 12px; font-size: 12px; }
        .cninfo-empty button { height: 34px; padding: 0 12px; border: 1px solid #334155; border-radius: 6px; color: #CBD5E1; background: #111827; cursor: pointer; }
        .cninfo-detail-backdrop { position: fixed; inset: 0; z-index: 70; border: 0; background: rgba(2, 6, 23, 0.72); cursor: default; }
        .cninfo-detail-drawer { position: fixed; z-index: 71; top: 0; right: 0; width: min(760px, calc(100vw - 240px)); height: 100vh; display: flex; flex-direction: column; border-left: 1px solid #334155; background: #0B1220; box-shadow: -12px 0 32px rgba(0,0,0,0.32); }
        .cninfo-detail-head { min-height: 72px; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 16px; border-bottom: 1px solid #1E293B; }
        .cninfo-detail-head strong { display: block; color: #F1F5F9; font-size: 14px; line-height: 1.45; }
        .cninfo-detail-head span { display: block; margin-top: 4px; color: #64748B; font-size: 11px; }
        .cninfo-detail-body { min-height: 0; flex: 1; display: grid; grid-template-rows: minmax(150px, auto) minmax(320px, 1fr); overflow: hidden; }
        .cninfo-detail-text { max-height: 32vh; margin: 0; padding: 16px; overflow: auto; border-bottom: 1px solid #1E293B; color: #CBD5E1; background: #0F172A; font-family: inherit; font-size: 12px; line-height: 1.75; white-space: pre-wrap; }
        .cninfo-detail-message { padding: 16px; color: #94A3B8; font-size: 12px; line-height: 1.7; }
        .cninfo-detail-frame { width: 100%; height: 100%; border: 0; background: #111827; }
        @media (max-width: 980px) {
          .cninfo-query { grid-template-columns: repeat(2, minmax(0, 1fr)); }
          .cninfo-query-button { min-width: 0; }
          .cninfo-list-head, .cninfo-row { grid-template-columns: 112px minmax(220px, 1fr) 96px 44px; }
        }
        @media (max-width: 620px) {
          .cninfo-panel { gap: 10px; min-height: auto; }
          .cninfo-header { padding: 10px; }
          .cninfo-title-copy h2 { font-size: 16px; }
          .cninfo-presets { gap: 5px; }
          .cninfo-preset { height: 46px; padding: 0 8px; text-align: center; }
          .cninfo-preset span { display: none; }
          .cninfo-query { grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 9px; }
          .cninfo-field:nth-child(1), .cninfo-field:nth-child(2) { grid-column: 1 / -1; }
          .cninfo-query > .cninfo-icon-button, .cninfo-query-button { width: 100%; height: 44px; }
          .cninfo-list-head { display: none; }
          .cninfo-list-body { max-height: none; min-height: 320px; }
          .cninfo-row { grid-template-columns: minmax(0, 1fr) 44px; row-gap: 7px; min-height: 104px; padding: 11px; }
          .cninfo-company { grid-column: 1; display: flex; align-items: center; gap: 7px; }
          .cninfo-company strong, .cninfo-company span { display: inline; margin: 0; }
          .cninfo-announcement { grid-column: 1 / -1; grid-row: 2; }
          .cninfo-announcement-title { white-space: normal; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
          .cninfo-date { grid-column: 1; grid-row: 3; }
          .cninfo-original-link { grid-column: 2; grid-row: 1; width: 44px; height: 44px; }
          .cninfo-status { min-height: 50px; }
          .cninfo-detail-drawer { width: 100vw; }
          .cninfo-detail-body { grid-template-rows: minmax(120px, auto) minmax(260px, 1fr); }
        }
        @media (prefers-reduced-motion: reduce) {
          .cninfo-panel * { scroll-behavior: auto !important; }
        }
      `}</style>

      <ResearchBoundary kind="external" source="巨潮资讯网公告查询与官方披露原文" />

      <header className="cninfo-header">
        <div className="cninfo-title-block">
          <span className="cninfo-title-icon"><FileSearch aria-hidden="true" /></span>
          <div className="cninfo-title-copy">
            <h2>巨潮公告</h2>
            <p>{error || `官方披露 · ${result?.total ?? 0} 条匹配 · ${syncing ? '自动同步中' : result?.cached ? '缓存结果' : '上游结果'} · ${updatedText}`}</p>
          </div>
        </div>
        <button
          className="cninfo-icon-button"
          type="button"
          aria-label="刷新当前公告"
          title="刷新当前公告"
          disabled={loading || !result}
          onClick={() => runQuery(preset, result?.page || 1, true)}
        >
          <RefreshCw aria-hidden="true" />
        </button>
      </header>

      <div className="cninfo-live-state" aria-live="polite">
        <BellRing aria-hidden="true" /> 当前公告类型每 5 分钟自动更新{newCount > 0 ? ` · 新增 ${newCount} 条` : ''}
      </div>

      <div className="cninfo-presets" role="tablist" aria-label="公告类型">
        {PRESETS.map((item) => (
          <button
            className="cninfo-preset"
            data-active={preset === item.value}
            key={item.value}
            type="button"
            role="tab"
            aria-selected={preset === item.value}
            onClick={() => selectPreset(item.value)}
          >
            <strong>{item.label}</strong>
            <span>{item.description}</span>
          </button>
        ))}
      </div>

      <form className="cninfo-query" onSubmit={(event) => { event.preventDefault(); runQuery(preset, 1, true); }}>
        <div className="cninfo-field">
          <label htmlFor="cninfo-code">股票代码</label>
          <input id="cninfo-code" value={code} maxLength={6} inputMode="numeric" placeholder="如 300450" onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} />
        </div>
        <div className="cninfo-field">
          <label htmlFor="cninfo-keyword">关键词</label>
          <input id="cninfo-keyword" value={keyword} maxLength={60} placeholder="标题或正文关键词" onChange={(event) => setKeyword(event.target.value)} />
        </div>
        <div className="cninfo-field">
          <label htmlFor="cninfo-start">开始日期</label>
          <input id="cninfo-start" type="date" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} />
        </div>
        <div className="cninfo-field">
          <label htmlFor="cninfo-end">结束日期</label>
          <input id="cninfo-end" type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} />
        </div>
        <button className="cninfo-icon-button" type="button" aria-label="清除筛选" title="清除筛选" disabled={loading} onClick={resetFilters}>
          <RotateCcw aria-hidden="true" />
        </button>
        <button className="cninfo-query-button" type="submit" disabled={loading}>
          <Search aria-hidden="true" /> 查询
        </button>
      </form>

      {error ? <div className="cninfo-error" role="alert">{error}</div> : null}

      <section className="cninfo-list" aria-label="巨潮公告列表">
        <div className="cninfo-list-head">
          <span>公司</span><span>公告</span><span>披露日期</span><span>原文</span>
        </div>
        <div className="cninfo-list-body">
          {loading ? (
            <div className="cninfo-loading" data-cninfo-loading="true" aria-label="正在查询巨潮公告">
              <div className="cninfo-skeletons" aria-hidden="true">
                {[0, 1, 2, 3].map((item) => <div className="cninfo-skeleton" key={item} />)}
              </div>
            </div>
          ) : result?.items?.length ? result.items.map((item) => {
            const originalUrl = item.pdf_url || item.detail_url;
            return (
              <article className="cninfo-row" key={item.id || `${item.code}-${item.announcement_time}-${item.title}`}>
                <div className="cninfo-company"><strong>{item.code || '--'}</strong><span>{item.name || '名称缺失'}</span></div>
                <div className="cninfo-announcement">
                  <button className="cninfo-announcement-title" type="button" title={item.title} onClick={() => openDetail(item)}>{item.title || '公告标题缺失'}</button>
                  <div className="cninfo-tags">{(item.tags || []).slice(0, 3).map((tag) => <span className="cninfo-tag" key={tag}>{tag}</span>)}</div>
                </div>
                <time className="cninfo-date" dateTime={item.announcement_date}>{item.announcement_date || '--'}</time>
                {originalUrl ? (
                  <a
                    className="cninfo-original-link"
                    data-cninfo-original-link="true"
                    href={originalUrl}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`打开 ${item.code} 公告原文`}
                    title="打开巨潮官方原文"
                  >
                    <ExternalLink aria-hidden="true" />
                  </a>
                ) : <span />}
              </article>
            );
          }) : (
            <div className="cninfo-empty" data-cninfo-empty="true">
              <div>
                <FileSearch aria-hidden="true" />
                <p>{result ? '当前条件下没有找到公告' : '选择公告类型和筛选条件后查询'}</p>
                <button type="button" onClick={() => result ? resetFilters() : runQuery(preset, 1, false)}>
                  {result ? '清除筛选' : '查询公告'}
                </button>
              </div>
            </div>
          )}
        </div>
        <footer className="cninfo-status">
          <span>网站查询接口无 SLA · 低频缓存 · 以公告时间作为可用时点</span>
          <div className="cninfo-pagination">
            <button className="cninfo-page-button" type="button" aria-label="上一页" disabled={loading || !result || result.page <= 1} onClick={() => runQuery(preset, Math.max(1, (result?.page || 1) - 1))}>
              <ChevronLeft aria-hidden="true" />
            </button>
            <span className="cninfo-page-label">{result?.page || 1} / {Math.max(1, Math.ceil((result?.total || 0) / (result?.page_size || 30)))}</span>
            <button className="cninfo-page-button" type="button" aria-label="下一页" disabled={loading || !result?.has_more} onClick={() => runQuery(preset, (result?.page || 1) + 1)}>
              <ChevronRight aria-hidden="true" />
            </button>
          </div>
        </footer>
      </section>

      {selected ? (
        <>
          <button className="cninfo-detail-backdrop" type="button" aria-label="关闭公告详情" onClick={() => setSelected(null)} />
          <aside className="cninfo-detail-drawer" role="dialog" aria-modal="true" aria-label="公告内容">
            <header className="cninfo-detail-head">
              <div><strong>{selected.title}</strong><span>{selected.code} {selected.name} · {selected.announcement_date} · 巨潮官方原文</span></div>
              <button className="cninfo-icon-button" type="button" aria-label="关闭公告详情" onClick={() => setSelected(null)}><X aria-hidden="true" /></button>
            </header>
            <div className="cninfo-detail-body">
              {detailLoading ? <div className="cninfo-detail-message">正在解析公告正文...</div>
                : detail?.content ? <pre className="cninfo-detail-text">{detail.content}{detail.truncated ? '\n\n[正文过长，已截断；请在下方 PDF 阅读器查看完整原文]' : ''}</pre>
                  : <div className="cninfo-detail-message">{detailError || '该公告可能是扫描件，暂未提取到可检索文本；下方仍可查看官方 PDF 原文。'}</div>}
              {selected.pdf_url ? <iframe className="cninfo-detail-frame" src={selected.pdf_url} title={`${selected.code} 公告 PDF 原文`} /> : null}
            </div>
          </aside>
        </>
      ) : null}
    </div>
  );
};

export default CninfoDisclosurePanel;
