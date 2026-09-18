export type FinancialValueKind = 'money' | 'percent' | 'multiple' | 'perShare' | 'text' | 'number';
export type FinancialGroupKey = 'cashflow' | 'profitability' | 'growth' | 'solvency' | 'other';
export type FinancialTone = 'positive' | 'negative' | 'neutral' | 'muted';

export interface FinancialFieldMeta {
  label: string;
  kind: FinancialValueKind;
  group: FinancialGroupKey;
}

export interface FormattedFinancialValue {
  value: string;
  unit: string;
  display: string;
  title: string;
  tone: FinancialTone;
}

export const FIELD_META: Record<string, FinancialFieldMeta> = {
  revenue: { label: '营业收入', kind: 'money', group: 'cashflow' },
  net_profit: { label: '净利润', kind: 'money', group: 'cashflow' },
  operating_cash_flow: { label: '经营现金流', kind: 'money', group: 'cashflow' },
  enterprise_fcf_per_share: { label: '企业自由现金流/股', kind: 'perShare', group: 'cashflow' },
  shareholder_fcf_per_share: { label: '股东自由现金流/股', kind: 'perShare', group: 'cashflow' },
  roe: { label: '净资产收益率', kind: 'percent', group: 'profitability' },
  roa: { label: '总资产收益率', kind: 'percent', group: 'profitability' },
  gross_margin: { label: '毛利率', kind: 'percent', group: 'profitability' },
  net_margin: { label: '净利率', kind: 'percent', group: 'profitability' },
  revenue_growth: { label: '营收增长率', kind: 'percent', group: 'growth' },
  profit_growth: { label: '利润增长率', kind: 'percent', group: 'growth' },
  debt_ratio: { label: '资产负债率', kind: 'percent', group: 'solvency' },
  current_ratio: { label: '流动比率', kind: 'multiple', group: 'solvency' },
  inventory_turnover: { label: '存货周转率', kind: 'multiple', group: 'solvency' },
  receivable_turnover: { label: '应收账款周转率', kind: 'multiple', group: 'solvency' },
  asset_turnover: { label: '总资产周转率', kind: 'multiple', group: 'solvency' },
};

export const FINANCIAL_GROUPS: ReadonlyArray<{ key: FinancialGroupKey; label: string }> = [
  { key: 'cashflow', label: '利润与现金流' },
  { key: 'profitability', label: '盈利能力' },
  { key: 'growth', label: '成长能力' },
  { key: 'solvency', label: '偿债与运营' },
  { key: 'other', label: '其他指标' },
];

const GROWTH_FIELDS = new Set(['revenue_growth', 'profit_growth']);

function formatNumber(value: number, maximumFractionDigits: number, minimumFractionDigits = 0): string {
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits,
    minimumFractionDigits,
  }).format(value);
}

function formatMoney(value: number): FormattedFinancialValue {
  const absolute = Math.abs(value);
  const divisor = absolute >= 100_000_000 ? 100_000_000 : absolute >= 10_000 ? 10_000 : 1;
  const unit = divisor === 100_000_000 ? '亿元' : divisor === 10_000 ? '万元' : '元';
  const formattedValue = formatNumber(value / divisor, 2, 2);
  const exact = formatNumber(value, 6, 2);
  return {
    value: formattedValue,
    unit,
    display: `${formattedValue} ${unit}`,
    title: `¥${exact}`,
    tone: 'neutral',
  };
}

function primitiveDisplay(value: unknown): string {
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

export function getFieldGroup(field: string): FinancialGroupKey {
  return FIELD_META[field]?.group || 'other';
}

export function getFieldLabel(field: string): string {
  return FIELD_META[field]?.label || field;
}

export function formatFinancialValue(field: string, raw: unknown): FormattedFinancialValue {
  if (raw === null || raw === undefined || raw === '') {
    return { value: '--', unit: '', display: '--', title: '暂无数据', tone: 'muted' };
  }

  if (typeof raw !== 'number' || !Number.isFinite(raw)) {
    const display = typeof raw === 'number' ? '--' : primitiveDisplay(raw);
    return {
      value: display,
      unit: '',
      display,
      title: display === '--' ? '暂无数据' : display,
      tone: display === '--' ? 'muted' : 'neutral',
    };
  }

  const meta = FIELD_META[field];
  if (meta?.kind === 'money') return formatMoney(raw);

  let value = formatNumber(raw, meta?.kind === 'number' ? 6 : 2);
  let unit = '';
  if (meta?.kind === 'percent') unit = '%';
  if (meta?.kind === 'multiple') unit = '倍';
  if (meta?.kind === 'perShare') unit = '元/股';

  let tone: FinancialTone = 'neutral';
  if (GROWTH_FIELDS.has(field)) {
    tone = raw > 0 ? 'positive' : raw < 0 ? 'negative' : 'neutral';
  }

  return {
    value,
    unit,
    display: unit === '%' ? `${value}%` : unit ? `${value} ${unit}` : value,
    title: unit === '%' ? `${raw}%` : unit ? `${raw} ${unit}` : String(raw),
    tone,
  };
}

export function formatPeriodDate(value: unknown): string {
  const text = String(value ?? '');
  return /^\d{8}$/.test(text)
    ? `${text.slice(0, 4)}-${text.slice(4, 6)}-${text.slice(6, 8)}`
    : text || '--';
}

export function formatPeriodLabel(value: unknown): string {
  const text = String(value ?? '');
  if (!/^\d{8}$/.test(text)) return text || '--';
  const year = text.slice(0, 4);
  const monthDay = text.slice(4);
  if (monthDay === '0331') return `${year} Q1`;
  if (monthDay === '0630') return `${year} 中报`;
  if (monthDay === '0930') return `${year} Q3`;
  if (monthDay === '1231') return `${year} 年报`;
  return formatPeriodDate(text);
}

export function getExchangeLabel(code: string): string {
  if (/^(4|8|9)/.test(code)) return '北交所';
  if (/^(0|2|3)/.test(code)) return '深交所';
  if (/^6/.test(code)) return '上交所';
  return 'A 股';
}
