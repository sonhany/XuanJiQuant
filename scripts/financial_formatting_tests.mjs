import assert from 'node:assert/strict';
import {
  formatFinancialValue,
  formatPeriodLabel,
  getExchangeLabel,
  getFieldGroup,
} from '../components/financialFormatting.ts';

const revenue = formatFinancialValue('revenue', 54_702_912_385.23);
assert.equal(revenue.value, '547.03');
assert.equal(revenue.unit, '亿元');
assert.equal(revenue.display, '547.03 亿元');
assert.equal(revenue.title, '¥54,702,912,385.23');

const smallMoney = formatFinancialValue('net_profit', -123_456);
assert.equal(smallMoney.display, '-12.35 万元');

const roe = formatFinancialValue('roe', 10.57);
assert.equal(roe.display, '10.57%');
assert.equal(roe.tone, 'neutral');

const negativeGrowth = formatFinancialValue('profit_growth', -4.532254);
assert.equal(negativeGrowth.display, '-4.53%');
assert.equal(negativeGrowth.tone, 'negative');

const positiveGrowth = formatFinancialValue('revenue_growth', 6.336009);
assert.equal(positiveGrowth.display, '6.34%');
assert.equal(positiveGrowth.tone, 'positive');

const currentRatio = formatFinancialValue('current_ratio', 7.060728);
assert.equal(currentRatio.display, '7.06 倍');

const perShare = formatFinancialValue('enterprise_fcf_per_share', 61.262903);
assert.equal(perShare.display, '61.26 元/股');

const missing = formatFinancialValue('revenue', null);
assert.equal(missing.display, '--');
assert.equal(missing.tone, 'muted');

assert.equal(getFieldGroup('gross_margin'), 'profitability');
assert.equal(getFieldGroup('unmapped_database_field'), 'other');
assert.equal(getExchangeLabel('600519'), '上交所');
assert.equal(getExchangeLabel('300750'), '深交所');
assert.equal(getExchangeLabel('830799'), '北交所');
assert.equal(formatPeriodLabel('20260331'), '2026 Q1');
assert.equal(formatPeriodLabel('20251231'), '2025 年报');

console.log('financial formatting tests passed');
