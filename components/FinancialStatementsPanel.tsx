import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  CalendarRange,
  CalendarDays,
  ChevronRight,
  CircleGauge,
  Clock3,
  Database,
  FileSpreadsheet,
  Layers3,
  RefreshCw,
  Search,
} from 'lucide-react';
import {
  FIELD_META,
  FINANCIAL_GROUPS,
  FinancialGroupKey,
  FinancialTone,
  formatFinancialValue,
  formatPeriodDate,
  formatPeriodLabel,
  getExchangeLabel,
  getFieldGroup,
  getFieldLabel,
} from './financialFormatting';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';
const ACCENT = '#F59E0B';
const MONO = 'JetBrains Mono, "SFMono-Regular", Consolas, monospace';
const IDENTITY_FIELDS = new Set(['report_date', 'period', 'code', 'name']);
const FIELD_ORDER = [
  'report_date',
  'period',
  'code',
  'name',
  'revenue',
  'net_profit',
  'operating_cash_flow',
  'enterprise_fcf_per_share',
  'shareholder_fcf_per_share',
  'roe',
  'roa',
  'gross_margin',
  'net_margin',
  'revenue_growth',
  'profit_growth',
  'debt_ratio',
  'current_ratio',
  'inventory_turnover',
  'receivable_turnover',
  'asset_turnover',
];

const PAGE_STYLES = `
  @keyframes financial-spin { to { transform: rotate(360deg); } }
  .financial-summary-grid {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    border-top: 1px solid #1E293B;
    border-bottom: 1px solid #1E293B;
  }
  .financial-summary-metric {
    min-width: 0;
    padding: 14px 16px;
    border-right: 1px solid #1E293B;
  }
  .financial-summary-metric:last-child { border-right: 0; }
  .financial-quality-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    border-top: 1px solid #1E293B;
    border-bottom: 1px solid #1E293B;
  }
  .financial-quality-item {
    min-width: 0;
    padding: 10px 14px;
    border-right: 1px solid #1E293B;
  }
  .financial-quality-item:last-child { border-right: 0; }
  .financial-group-tabs {
    display: flex;
    gap: 4px;
    overflow-x: auto;
    padding-bottom: 2px;
    scrollbar-width: thin;
  }
  .financial-group-button,
  .financial-query-button,
  .financial-code-input {
    transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease, opacity 160ms ease;
  }
  .financial-group-button:focus-visible,
  .financial-query-button:focus-visible,
  .financial-code-input:focus-visible,
  .financial-raw-summary:focus-visible {
    outline: 2px solid #F59E0B;
    outline-offset: 2px;
  }
  .financial-table tbody tr:hover td {
    background: #111C2E;
  }
  .financial-table tbody tr:hover .financial-period-cell {
    background: #142137;
  }
  .financial-period-cell {
    position: sticky;
    left: 0;
    z-index: 2;
    background: #0D1728;
    box-shadow: 1px 0 0 #253247;
  }
  .financial-table thead .financial-period-cell {
    z-index: 4;
    background: #0A1220;
  }
  .financial-raw-details[open] .financial-chevron {
    transform: rotate(90deg);
  }
  .financial-chevron {
    transition: transform 160ms ease;
  }
  @media (max-width: 1120px) {
    .financial-summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .financial-summary-metric:nth-child(3) { border-right: 0; }
    .financial-summary-metric:nth-child(-n + 3) { border-bottom: 1px solid #1E293B; }
  }
  @media (max-width: 720px) {
    .financial-quality-strip { grid-template-columns: minmax(0, 1fr); }
    .financial-quality-item {
      border-right: 0;
      border-bottom: 1px solid #1E293B;
    }
    .financial-quality-item:last-child { border-bottom: 0; }
    .financial-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .financial-summary-metric,
    .financial-summary-metric:nth-child(3) { border-right: 1px solid #1E293B; }
    .financial-summary-metric:nth-child(even) { border-right: 0; }
    .financial-summary-metric:nth-child(-n + 4) { border-bottom: 1px solid #1E293B; }
    .financial-stock-header { align-items: flex-start !important; flex-direction: column; }
    .financial-stock-meta { justify-content: flex-start !important; }
    .financial-query-help { flex-basis: 100%; }
  }
  @media (prefers-reduced-motion: reduce) {
    .financial-group-button,
    .financial-query-button,
    .financial-code-input,
    .financial-chevron { transition: none; }
  }
`;

type FinancialRow = Record<string, unknown>;

interface FinancialQuality {
  completeness: {
    status: 'complete' | 'partial' | 'missing';
    complete_periods: number;
    total_periods: number;
    incomplete_periods: number;
    ratio: number;
    latest_complete: boolean;
    latest_missing_fields: string[];
    missing_by_field: Record<string, number>;
  };
  freshness: {
    status: 'current' | 'stale' | 'unknown';
    as_of_date: string;
    latest_period: string;
    expected_period: string;
    lag_quarters: number | null;
  };
  coverage: {
    start_period: string;
    end_period: string;
  };
}

interface FinancialPayload {
  code: string;
  name: string;
  keys: string[];
  datasets: Record<string, unknown>;
  history: FinancialRow[];
  history_count: number;
  latest_report_date: string;
  quality?: FinancialQuality;
}

interface FinancialStatementsPanelProps {
  initialCode?: string;
  requestKey?: number;
}

function normalizeCode(value: string): string {
  let code = String(value || '').trim().toUpperCase();
  code = code.replace(/\.SH$|\.SZ$|\.BJ$/i, '');
  if (/^(SH|SZ|BJ)/.test(code)) code = code.slice(2);
  return /^\d{6}$/.test(code) ? code : '';
}

function collectColumns(rows: FinancialRow[]): string[] {
  const fields = new Set<string>();
  rows.forEach(row => Object.keys(row || {}).forEach(field => fields.add(field)));
  const priority = FIELD_ORDER.filter(field => fields.delete(field));
  return [...priority, ...Array.from(fields).sort((a, b) => a.localeCompare(b))];
}

function flattenDataset(value: unknown, path = '', out: Array<{ path: string; value: unknown }> = []) {
  if (Array.isArray(value)) {
    if (!value.length) out.push({ path: path || 'value', value: [] });
    value.forEach((item, index) => flattenDataset(item, `${path}[${index}]`, out));
    return out;
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>);
    if (!entries.length) out.push({ path: path || 'value', value: {} });
    entries.forEach(([key, item]) => flattenDataset(item, path ? `${path}.${key}` : key, out));
    return out;
  }
  out.push({ path: path || 'value', value });
  return out;
}

function rawDisplayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '--';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return '--';
    return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 6 }).format(value);
  }
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

function getPeriodValue(row: FinancialRow): unknown {
  return row.report_date || row.period;
}

function toneColor(tone: FinancialTone): string {
  if (tone === 'positive') return '#4ADE80';
  if (tone === 'negative') return '#F87171';
  if (tone === 'muted') return '#475569';
  return '#D6E0EE';
}

function qualityCompletenessColor(ratio: number): string {
  if (ratio >= 0.9) return '#4ADE80';
  if (ratio >= 0.6) return '#FBBF24';
  return '#F87171';
}

function qualityFreshnessColor(status: FinancialQuality['freshness']['status']): string {
  if (status === 'current') return '#4ADE80';
  if (status === 'stale') return '#F87171';
  return '#8291A7';
}

function unitHint(field: string): string {
  const kind = FIELD_META[field]?.kind;
  if (kind === 'money') return '亿元 / 万元';
  if (kind === 'percent') return '%';
  if (kind === 'multiple') return '倍';
  if (kind === 'perShare') return '元/股';
  return '';
}

const SummaryMetric: React.FC<{ field: string; label: string; value: unknown }> = ({ field, label, value }) => {
  const formatted = formatFinancialValue(field, value);
  return (
    <div className="financial-summary-metric" title={formatted.title}>
      <div style={{ color: '#7D8CA3', fontSize: 11, lineHeight: 1.4, marginBottom: 7 }}>{label}</div>
      <div
        aria-label={`${label} ${formatted.display}`}
        style={{
          minWidth: 0,
          color: toneColor(formatted.tone),
          fontFamily: MONO,
          fontSize: 17,
          fontWeight: 700,
          lineHeight: 1.2,
          fontVariantNumeric: 'tabular-nums',
          whiteSpace: 'nowrap',
        }}
      >
        {formatted.value}
        {formatted.unit ? (
          <span style={{ color: '#7D8CA3', fontFamily: 'inherit', fontSize: 11, fontWeight: 500, marginLeft: 5 }}>
            {formatted.unit}
          </span>
        ) : null}
      </div>
    </div>
  );
};

const FinancialHistoryTable: React.FC<{ rows: FinancialRow[]; columns: string[]; groupLabel: string }> = ({
  rows,
  columns,
  groupLabel,
}) => {
  if (!columns.length) {
    return (
      <div style={{ padding: '28px 16px', border: '1px solid #1E293B', borderRadius: 7, color: '#64748B', fontSize: 12, textAlign: 'center' }}>
        当前数据库没有“{groupLabel}”分组字段
      </div>
    );
  }

  return (
    <div
      style={{
        width: '100%',
        maxHeight: 560,
        overflow: 'auto',
        border: '1px solid #253247',
        borderRadius: 7,
        background: '#0A1322',
      }}
    >
      <table
        className="financial-table"
        aria-label={`${groupLabel}历史财务数据`}
        style={{
          minWidth: Math.max(720, 154 + columns.length * 172),
          width: '100%',
          borderCollapse: 'separate',
          borderSpacing: 0,
          fontSize: 12,
        }}
      >
        <thead>
          <tr>
            <th
              className="financial-period-cell"
              style={{
                top: 0,
                width: 154,
                minWidth: 154,
                padding: '10px 12px',
                borderBottom: '1px solid #2A384D',
                color: '#A5B3C6',
                fontSize: 11,
                fontWeight: 600,
                textAlign: 'left',
                whiteSpace: 'nowrap',
              }}
            >
              报告期
            </th>
            {columns.map(column => (
              <th
                key={column}
                title={column}
                style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 3,
                  minWidth: 172,
                  padding: '8px 12px',
                  borderBottom: '1px solid #2A384D',
                  background: '#0A1220',
                  color: '#A5B3C6',
                  fontWeight: 600,
                  textAlign: 'right',
                  whiteSpace: 'nowrap',
                }}
              >
                <span style={{ display: 'block', fontSize: 11 }}>{getFieldLabel(column)}</span>
                <span style={{ display: 'block', minHeight: 14, color: '#596A82', fontSize: 11, fontWeight: 500, marginTop: 2 }}>
                  {unitHint(column)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => {
            const period = getPeriodValue(row);
            return (
              <tr key={`${String(period || rowIndex)}-${rowIndex}`}>
                <td
                  className="financial-period-cell"
                  title={formatPeriodDate(period)}
                  style={{
                    width: 154,
                    minWidth: 154,
                    padding: '10px 12px',
                    borderBottom: '1px solid #18263A',
                    color: '#E2E8F0',
                    fontFamily: MONO,
                    fontSize: 12,
                    fontWeight: rowIndex === 0 ? 700 : 500,
                    textAlign: 'left',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {formatPeriodLabel(period)}
                </td>
                {columns.map(column => {
                  const formatted = formatFinancialValue(column, row[column]);
                  return (
                    <td
                      key={column}
                      title={formatted.title}
                      style={{
                        minWidth: 172,
                        padding: '10px 12px',
                        borderBottom: '1px solid #18263A',
                        color: toneColor(formatted.tone),
                        fontFamily: MONO,
                        fontVariantNumeric: 'tabular-nums',
                        textAlign: 'right',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {formatted.display}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const RawArrayTable: React.FC<{ rows: FinancialRow[] }> = ({ rows }) => {
  const columns = useMemo(() => collectColumns(rows), [rows]);
  if (!rows.length || !columns.length) {
    return <div style={{ color: '#64748B', fontSize: 12 }}>暂无表格记录</div>;
  }

  return (
    <div style={{ width: '100%', maxHeight: 520, overflow: 'auto', border: '1px solid #253247', borderRadius: 7 }}>
      <table style={{ minWidth: Math.max(760, columns.length * 140), width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr>
            {columns.map(column => (
              <th
                key={column}
                title={column}
                style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 1,
                  padding: '9px 11px',
                  borderBottom: '1px solid #253247',
                  background: '#0A1220',
                  color: '#8291A7',
                  fontWeight: 600,
                  textAlign: 'right',
                  whiteSpace: 'nowrap',
                }}
              >
                {getFieldLabel(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`${String(getPeriodValue(row) || rowIndex)}-${rowIndex}`}>
              {columns.map(column => {
                const value = rawDisplayValue(row[column]);
                return (
                  <td
                    key={column}
                    title={value}
                    style={{
                      padding: '8px 11px',
                      borderBottom: '1px solid #18263A',
                      color: value === '--' ? '#475569' : '#C8D3E1',
                      fontFamily: typeof row[column] === 'number' ? MONO : 'inherit',
                      fontVariantNumeric: 'tabular-nums',
                      textAlign: 'right',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const RawDataset: React.FC<{ name: string; value: unknown }> = ({ name, value }) => {
  const arrayRows = Array.isArray(value) && value.every(item => item && typeof item === 'object' && !Array.isArray(item))
    ? value as FinancialRow[]
    : null;
  const flattened = useMemo(() => arrayRows ? [] : flattenDataset(value), [arrayRows, value]);

  return (
    <details className="financial-raw-details" style={{ borderTop: '1px solid #1E293B' }}>
      <summary
        className="financial-raw-summary"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          minHeight: 44,
          cursor: 'pointer',
          color: '#CBD5E1',
          fontFamily: MONO,
          fontSize: 12,
          fontWeight: 600,
          listStyle: 'none',
        }}
      >
        <ChevronRight className="financial-chevron" aria-hidden="true" style={{ width: 15, height: 15, color: '#64748B' }} />
        <span>{name}</span>
        <span style={{ color: '#526278', fontFamily: 'inherit', fontSize: 11, fontWeight: 500 }}>
          {arrayRows ? `${arrayRows.length} 条记录` : `${flattened.length} 个字段`}
        </span>
      </summary>
      <div style={{ paddingBottom: 14 }}>
        {arrayRows ? (
          <RawArrayTable rows={arrayRows} />
        ) : (
          <div style={{ maxHeight: 520, overflow: 'auto', border: '1px solid #253247', borderRadius: 7 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={{ position: 'sticky', top: 0, width: '46%', padding: '9px 11px', textAlign: 'left', color: '#718199', background: '#0A1220' }}>
                    字段路径
                  </th>
                  <th style={{ position: 'sticky', top: 0, padding: '9px 11px', textAlign: 'left', color: '#718199', background: '#0A1220' }}>
                    数据库原值
                  </th>
                </tr>
              </thead>
              <tbody>
                {flattened.map((item, index) => {
                  const valueDisplay = rawDisplayValue(item.value);
                  return (
                    <tr key={`${item.path}-${index}`}>
                      <td style={{ padding: '8px 11px', borderTop: '1px solid #18263A', color: '#94A3B8', fontFamily: MONO, verticalAlign: 'top', overflowWrap: 'anywhere' }}>
                        {item.path}
                      </td>
                      <td
                        title={valueDisplay}
                        style={{
                          padding: '8px 11px',
                          borderTop: '1px solid #18263A',
                          color: valueDisplay === '--' ? '#475569' : '#CBD5E1',
                          fontFamily: typeof item.value === 'number' ? MONO : 'inherit',
                          verticalAlign: 'top',
                          overflowWrap: 'anywhere',
                        }}
                      >
                        {valueDisplay}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </details>
  );
};

const FinancialStatementsPanel: React.FC<FinancialStatementsPanelProps> = ({
  initialCode = '600519',
  requestKey = 0,
}) => {
  const resolvedInitialCode = normalizeCode(initialCode) || '600519';
  const [codeInput, setCodeInput] = useState(resolvedInitialCode);
  const [data, setData] = useState<FinancialPayload | null>(null);
  const [activeGroup, setActiveGroup] = useState<FinancialGroupKey>('cashflow');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadFinancials = useCallback(async (value: string) => {
    const code = normalizeCode(value);
    if (!code) {
      setError('请输入合法的六位 A 股代码');
      setData(null);
      return;
    }
    setLoading(true);
    setError('');
    try {
      const query = new URLSearchParams({ action: 'financials', code });
      const response = await fetch(`${API_BASE}/api/data?${query.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      const payload = await response.json();
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.error || `财务数据查询失败 (${response.status})`);
      }
      setCodeInput(code);
      setActiveGroup('cashflow');
      setData(payload.data as FinancialPayload);
    } catch (reason: any) {
      setData(null);
      setError(reason?.message || '财务数据查询失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadFinancials(resolvedInitialCode);
  }, [loadFinancials, requestKey, resolvedInitialCode]);

  const historyRows = useMemo(() => {
    const rows = Array.isArray(data?.history) ? data.history : [];
    return [...rows].sort((a, b) => String(getPeriodValue(b) || '').localeCompare(String(getPeriodValue(a) || '')));
  }, [data]);

  const allDataColumns = useMemo(
    () => collectColumns(historyRows).filter(field => !IDENTITY_FIELDS.has(field)),
    [historyRows],
  );

  const columnsByGroup = useMemo(() => {
    const grouped: Record<FinancialGroupKey, string[]> = {
      cashflow: [],
      profitability: [],
      growth: [],
      solvency: [],
      other: [],
    };
    allDataColumns.forEach(field => grouped[getFieldGroup(field)].push(field));
    return grouped;
  }, [allDataColumns]);

  const latestRow = historyRows[0] || null;
  const rawKeys = useMemo(
    () => (data?.keys || []).filter(key => key !== `fin:abstract:${data?.code || ''}`),
    [data],
  );
  const activeGroupLabel = FINANCIAL_GROUPS.find(group => group.key === activeGroup)?.label || '财务指标';
  const completeness = data?.quality?.completeness ?? null;
  const freshness = data?.quality?.freshness ?? null;
  const coverage = data?.quality?.coverage ?? null;

  return (
    <div aria-busy={loading} style={{ display: 'flex', flexDirection: 'column', gap: 20, minWidth: 0 }}>
      <style>{PAGE_STYLES}</style>

      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <label htmlFor="financial-code-input" style={{ display: 'flex', flexDirection: 'column', gap: 6, color: '#8796AA', fontSize: 11 }}>
          股票代码
          <span style={{ position: 'relative', display: 'block' }}>
            <Search aria-hidden="true" style={{ position: 'absolute', left: 11, top: '50%', transform: 'translateY(-50%)', width: 15, height: 15, color: '#64748B' }} />
            <input
              id="financial-code-input"
              className="financial-code-input"
              aria-label="股票代码"
              value={codeInput}
              onChange={event => setCodeInput(event.target.value.toUpperCase().slice(0, 12))}
              onKeyDown={event => {
                if (event.key === 'Enter') loadFinancials(codeInput);
              }}
              placeholder="600519 / SH600519"
              style={{
                width: 210,
                height: 40,
                boxSizing: 'border-box',
                padding: '0 12px 0 36px',
                borderRadius: 7,
                border: '1px solid #334155',
                background: '#0A1220',
                color: '#E2E8F0',
                fontFamily: MONO,
                fontSize: 13,
              }}
            />
          </span>
        </label>
        <button
          type="button"
          className="financial-query-button"
          onClick={() => loadFinancials(codeInput)}
          disabled={loading}
          style={{
            height: 40,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 7,
            padding: '0 16px',
            borderRadius: 7,
            border: `1px solid ${ACCENT}66`,
            background: `${ACCENT}18`,
            color: ACCENT,
            fontSize: 13,
            fontWeight: 650,
            cursor: loading ? 'wait' : 'pointer',
            opacity: loading ? 0.7 : 1,
          }}
        >
          <RefreshCw
            aria-hidden="true"
            style={{ width: 15, height: 15, animation: loading ? 'financial-spin 900ms linear infinite' : 'none' }}
          />
          {loading ? '查询中' : '查询'}
        </button>
        <div className="financial-query-help" style={{ color: '#68788F', fontSize: 11, lineHeight: '40px' }}>
          仅查询本地数据库，不触发财务更新
        </div>
      </div>

      {error ? (
        <div role="alert" style={{ padding: '10px 12px', border: '1px solid #EF444455', borderRadius: 7, background: '#EF444410', color: '#FCA5A5', fontSize: 12 }}>
          {error}
        </div>
      ) : null}

      {loading && !data ? (
        <div style={{ padding: 36, borderTop: '1px solid #1E293B', textAlign: 'center', color: '#718199', fontSize: 13 }}>
          正在读取财务数据...
        </div>
      ) : null}

      {!loading && data && data.keys.length === 0 ? (
        <div style={{ padding: 40, borderTop: '1px solid #1E293B', textAlign: 'center' }}>
          <FileSpreadsheet aria-hidden="true" style={{ width: 30, height: 30, color: '#475569', marginBottom: 11 }} />
          <div style={{ color: '#DCE5F1', fontSize: 15, fontWeight: 650 }}>{data.name || '未知股票'}</div>
          <div style={{ color: '#8291A7', fontFamily: MONO, fontSize: 12, marginTop: 5 }}>{data.code}</div>
          <div style={{ color: '#64748B', fontSize: 12, marginTop: 10 }}>数据库中暂无该股票的财务数据</div>
        </div>
      ) : null}

      {data && data.keys.length > 0 ? (
        <>
          <section style={{ minWidth: 0 }}>
            <div
              className="financial-stock-header"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 16,
                paddingBottom: 14,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
                <div
                  aria-hidden="true"
                  style={{
                    width: 40,
                    height: 40,
                    flex: '0 0 40px',
                    display: 'grid',
                    placeItems: 'center',
                    border: `1px solid ${ACCENT}55`,
                    borderRadius: 7,
                    background: `${ACCENT}14`,
                    color: '#FBBF24',
                    fontSize: 16,
                    fontWeight: 750,
                  }}
                >
                  {(data.name || '股').slice(0, 1)}
                </div>
                <div style={{ minWidth: 0 }}>
                  <h2 style={{ margin: 0, color: '#F4F7FB', fontSize: 19, fontWeight: 750, lineHeight: 1.3 }}>
                    {data.name || '未知股票'}
                  </h2>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', color: '#8291A7', fontSize: 11, marginTop: 4 }}>
                    <span style={{ color: '#B8C5D6', fontFamily: MONO }}>{data.code}</span>
                    <span aria-hidden="true">·</span>
                    <span>{getExchangeLabel(data.code)}</span>
                    <span aria-hidden="true">·</span>
                    <span>本地 SQLite</span>
                  </div>
                </div>
              </div>

              <div className="financial-stock-meta" style={{ display: 'flex', justifyContent: 'flex-end', gap: 18, flexWrap: 'wrap' }}>
                <div>
                  <div style={{ color: '#68788F', fontSize: 11, marginBottom: 4 }}>最新报告期</div>
                  <div title={formatPeriodDate(data.latest_report_date)} style={{ color: '#E2E8F0', fontFamily: MONO, fontSize: 12, fontWeight: 650 }}>
                    {formatPeriodLabel(data.latest_report_date)}
                  </div>
                </div>
                <div>
                  <div style={{ color: '#68788F', fontSize: 11, marginBottom: 4 }}>历史报告</div>
                  <div style={{ color: '#E2E8F0', fontFamily: MONO, fontSize: 12, fontWeight: 650 }}>{data.history_count} 期</div>
                </div>
                <div>
                  <div style={{ color: '#68788F', fontSize: 11, marginBottom: 4 }}>数据库集</div>
                  <div style={{ color: '#E2E8F0', fontFamily: MONO, fontSize: 12, fontWeight: 650 }}>{data.keys.length} 个</div>
                </div>
              </div>
            </div>

            {completeness && freshness && coverage ? (
              <div className="financial-quality-strip" aria-label="财务数据质量" style={{ marginBottom: 16 }}>
                <div className="financial-quality-item">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#718199', fontSize: 11 }}>
                    <CircleGauge aria-hidden="true" style={{ width: 14, height: 14 }} />
                    <span>历史完整度</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, marginTop: 5, minWidth: 0 }}>
                    <strong
                      style={{
                        color: qualityCompletenessColor(completeness.ratio),
                        fontFamily: MONO,
                        fontSize: 13,
                        fontWeight: 700,
                      }}
                    >
                      {(completeness.ratio * 100).toFixed(1)}%
                    </strong>
                    <span style={{ color: '#8291A7', fontFamily: MONO, fontSize: 11 }}>
                      {completeness.complete_periods}/{completeness.total_periods} 期
                    </span>
                  </div>
                  <div
                    style={{
                      color: completeness.latest_complete ? '#64748B' : '#F87171',
                      fontSize: 11,
                      marginTop: 3,
                    }}
                  >
                    {completeness.latest_complete
                      ? '最新报告期字段完整'
                      : `最新报告期缺少 ${completeness.latest_missing_fields.map(getFieldLabel).join('、')}`}
                  </div>
                </div>

                <div className="financial-quality-item">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#718199', fontSize: 11 }}>
                    <Clock3 aria-hidden="true" style={{ width: 14, height: 14 }} />
                    <span>数据时效</span>
                  </div>
                  <div
                    style={{
                      color: qualityFreshnessColor(freshness.status),
                      fontFamily: MONO,
                      fontSize: 13,
                      fontWeight: 700,
                      marginTop: 5,
                    }}
                  >
                    {freshness.status === 'current'
                      ? '当前'
                      : freshness.status === 'stale'
                        ? `滞后 ${freshness.lag_quarters ?? '--'} 季度`
                        : '未知'}
                  </div>
                  <div style={{ color: '#64748B', fontSize: 11, marginTop: 3 }}>
                    最低合理报告期 {formatPeriodLabel(freshness.expected_period)}
                  </div>
                </div>

                <div className="financial-quality-item">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, color: '#718199', fontSize: 11 }}>
                    <CalendarRange aria-hidden="true" style={{ width: 14, height: 14 }} />
                    <span>覆盖区间</span>
                  </div>
                  <div style={{ color: '#E2E8F0', fontFamily: MONO, fontSize: 12, fontWeight: 650, marginTop: 5 }}>
                    {coverage.start_period
                      ? `${formatPeriodLabel(coverage.start_period)} - ${formatPeriodLabel(coverage.end_period)}`
                      : '--'}
                  </div>
                  <div style={{ color: '#64748B', fontSize: 11, marginTop: 3 }}>
                    仅统计本地数据库已有报告期
                  </div>
                </div>
              </div>
            ) : null}

            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 9 }}>
              <CalendarDays aria-hidden="true" style={{ width: 15, height: 15, color: ACCENT }} />
              <div style={{ color: '#DDE6F2', fontSize: 13, fontWeight: 650 }}>最新一期核心指标</div>
              <div style={{ color: '#64748B', fontFamily: MONO, fontSize: 11 }}>
                {formatPeriodDate(getPeriodValue(latestRow || {}))}
              </div>
            </div>
            <div className="financial-summary-grid">
              <SummaryMetric field="revenue" label="营业收入" value={latestRow?.revenue} />
              <SummaryMetric field="net_profit" label="净利润" value={latestRow?.net_profit} />
              <SummaryMetric field="operating_cash_flow" label="经营现金流" value={latestRow?.operating_cash_flow} />
              <SummaryMetric field="roe" label="净资产收益率" value={latestRow?.roe} />
              <SummaryMetric field="gross_margin" label="毛利率" value={latestRow?.gross_margin} />
              <SummaryMetric field="debt_ratio" label="资产负债率" value={latestRow?.debt_ratio} />
            </div>
          </section>

          <section style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 10 }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Layers3 aria-hidden="true" style={{ width: 15, height: 15, color: ACCENT }} />
                  <div style={{ color: '#DDE6F2', fontSize: 14, fontWeight: 700 }}>历史财务指标</div>
                </div>
                <div style={{ color: '#68788F', fontSize: 11, marginTop: 4 }}>共 {historyRows.length} 期，最新报告期在前</div>
              </div>
              <div className="financial-group-tabs" role="group" aria-label="财务指标分组">
                {FINANCIAL_GROUPS.map(group => {
                  const selected = activeGroup === group.key;
                  return (
                    <button
                      key={group.key}
                      type="button"
                      className="financial-group-button"
                      aria-pressed={selected}
                      onClick={() => setActiveGroup(group.key)}
                      style={{
                        minHeight: 38,
                        flex: '0 0 auto',
                        padding: '0 12px',
                        border: selected ? `1px solid ${ACCENT}66` : '1px solid transparent',
                        borderRadius: 6,
                        background: selected ? `${ACCENT}16` : 'transparent',
                        color: selected ? '#FBBF24' : '#8291A7',
                        fontSize: 11,
                        fontWeight: selected ? 650 : 550,
                        cursor: 'pointer',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {group.label}
                      <span style={{ color: selected ? '#D99A20' : '#526278', fontFamily: MONO, fontSize: 11, marginLeft: 6 }}>
                        {columnsByGroup[group.key].length}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>

            <FinancialHistoryTable
              rows={historyRows}
              columns={columnsByGroup[activeGroup]}
              groupLabel={activeGroupLabel}
            />
          </section>

          <section style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
              <Database aria-hidden="true" style={{ width: 15, height: 15, color: '#718199' }} />
              <div style={{ color: '#C8D3E1', fontSize: 13, fontWeight: 650 }}>数据库原始数据</div>
            </div>
            <div style={{ color: '#64748B', fontSize: 11, marginBottom: 8 }}>
              保留除标准历史表外的全部财务键与嵌套字段
            </div>
            {rawKeys.length ? rawKeys.map(key => (
              <RawDataset key={key} name={key} value={data.datasets[key]} />
            )) : (
              <div style={{ padding: '14px 0', borderTop: '1px solid #1E293B', color: '#64748B', fontSize: 12 }}>
                无额外原始财务数据
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
};

export default FinancialStatementsPanel;
