/**
 * 量化技术指标计算服务
 * 基于日K线数据计算 MACD、RSI、KDJ、布林带、OBV、ATR 等核心指标
 * 将计算结果格式化为 LLM 可直接消费的结构化文本
 * 
 * 数据源：后端 /api/history 端点 (复用已有的 download_history.py)
 */

export interface KLine {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount?: number;
}

export interface ComputedIndicators {
  macd: {
    dif: number;
    dea: number;
    macdBar: number;
    signal: 'goldenCross' | 'deathCross' | 'bullBear' | 'bearBull' | 'neutral';
  };
  ema: {
    ema5: number;
    ema20: number;
    ema60: number;
    alignment: 'bullish' | 'bearish' | 'mixed';
  };
  boll: {
    upper: number;
    mid: number;
    lower: number;
    bandwidth: number;
    position: 'upper' | 'mid' | 'lower';
  };
  rsi: {
    rsi6: number;
    rsi12: number;
    rsi24: number;
    zone: 'overbought' | 'oversold' | 'normal';
  };
  kdj: {
    k: number;
    d: number;
    j: number;
    signal: 'goldenCross' | 'deathCross' | 'neutral';
  };
  obv: {
    obv: number;
    obvMA: number;
    divergence: 'positive' | 'negative' | 'none';
  };
  volume: {
    vol5: number;
    vol20: number;
    volRatio: number;
    signal: 'amplifying' | 'shrinking' | 'normal';
  };
  atr: {
    atr14: number;
    volatility: 'high' | 'medium' | 'low';
  };
}

// ─── 步骤1: 获取 K 线 ───────────────────────────────────────────

export async function fetchKLineData(
  symbol: string,
  days: number = 120
): Promise<KLine[]> {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - days);

  const fmt = (d: Date) =>
    `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;

  const code = symbol.replace(/^(sh|sz)/i, '').toUpperCase();

  try {
    const response = await fetch(`/api/history/${code}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        start: fmt(start),
        end: fmt(end),
        fqt: 1, // 前复权
      }),
    });

    if (!response.ok) {
      console.warn(`[TechnicalIndicator] 历史数据获取失败: ${response.status}`);
      return [];
    }

    const result = await response.json();
    if (!result.success || !result.klines || result.klines.length < 30) {
      console.warn(
        `[TechnicalIndicator] 历史数据不足: ${result.klines?.length || 0} bars`
      );
      return [];
    }

    return result.klines.map(
      (k: any): KLine => ({
        date: k.date,
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
        volume: k.volume,
        amount: k.amount,
      })
    );
  } catch (e) {
    console.error(`[TechnicalIndicator] 请求异常:`, e);
    return [];
  }
}

// ─── 步骤2: 计算全部指标 ────────────────────────────────────────

export function computeIndicators(klines: KLine[]): ComputedIndicators | null {
  if (klines.length < 30) return null;

  const closes = klines.map((k) => k.close);
  const highs = klines.map((k) => k.high);
  const lows = klines.map((k) => k.low);
  const volumes = klines.map((k) => k.volume);

  return {
    macd: calcMACD(closes),
    ema: calcEMA(closes),
    boll: calcBollinger(closes, 20, 2),
    rsi: calcRSI(closes),
    kdj: calcKDJ(highs, lows, closes),
    obv: calcOBV(closes, volumes),
    volume: calcVolumeMetrics(volumes),
    atr: calcATR(highs, lows, closes, 14),
  };
}

// ─── 各指标计算 ─────────────────────────────────────────────────

function ema(values: number[], period: number): number[] {
  const result: number[] = [];
  const multiplier = 2 / (period + 1);
  let prev =
    values.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(NaN);
    } else if (i === period - 1) {
      result.push(prev);
    } else {
      prev = (values[i] - prev) * multiplier + prev;
      result.push(prev);
    }
  }
  return result;
}

function sma(values: number[], period: number): number[] {
  const result: number[] = [];
  for (let i = 0; i < values.length; i++) {
    if (i < period - 1) {
      result.push(NaN);
    } else {
      result.push(
        values.slice(i - period + 1, i + 1).reduce((a, b) => a + b, 0) /
          period
      );
    }
  }
  return result;
}

function calcMACD(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9
): ComputedIndicators['macd'] {
  const emaFast = ema(closes, fast);
  const emaSlow = ema(closes, slow);
  const dif: number[] = [];
  for (let i = 0; i < closes.length; i++) {
    dif.push(
      isNaN(emaFast[i]) || isNaN(emaSlow[i]) ? NaN : emaFast[i] - emaSlow[i]
    );
  }
  const dea = ema(dif, signal);
  const macdBar: number[] = dif.map((d, i) =>
    isNaN(d) || isNaN(dea[i]) ? NaN : (d - dea[i]) * 2
  );

  const last = closes.length - 1;
  const prev = closes.length - 2;

  let sig: ComputedIndicators['macd']['signal'] = 'neutral';
  if (
    ![dif[last], dea[last], dif[prev], dea[prev]].some(isNaN)
  ) {
    if (dif[prev] <= dea[prev] && dif[last] > dea[last])
      sig = 'goldenCross';
    else if (dif[prev] >= dea[prev] && dif[last] < dea[last])
      sig = 'deathCross';
    else if (dif[last] > dea[last] && macdBar[last] > macdBar[prev])
      sig = 'bullBear';
    else if (dif[last] < dea[last] && macdBar[last] < macdBar[prev])
      sig = 'bearBull';
  }

  return {
    dif: dif[last] || 0,
    dea: dea[last] || 0,
    macdBar: macdBar[last] || 0,
    signal: sig,
  };
}

function calcEMA(
  closes: number[]
): ComputedIndicators['ema'] {
  const e5 = ema(closes, 5);
  const e20 = ema(closes, 20);
  const e60 = ema(closes, 60);
  const last = closes.length - 1;

  let alignment: ComputedIndicators['ema']['alignment'] = 'mixed';
  if (![e5[last], e20[last], e60[last]].some(isNaN)) {
    if (e5[last] > e20[last] && e20[last] > e60[last])
      alignment = 'bullish';
    else if (e5[last] < e20[last] && e20[last] < e60[last])
      alignment = 'bearish';
  }

  return { ema5: e5[last] || 0, ema20: e20[last] || 0, ema60: e60[last] || 0, alignment };
}

function calcBollinger(
  closes: number[],
  period = 20,
  multiplier = 2
): ComputedIndicators['boll'] {
  const midLine = sma(closes, period);
  const last = closes.length - 1;

  let upper = 0,
    lower = 0,
    bandwidth = 0;
  if (!isNaN(midLine[last])) {
    const slice = closes.slice(last - period + 1, last + 1);
    const mean = midLine[last];
    const stdDev = Math.sqrt(
      slice.reduce((s, v) => s + (v - mean) ** 2, 0) / period
    );
    upper = mean + multiplier * stdDev;
    lower = mean - multiplier * stdDev;
    bandwidth = ((upper - lower) / mean) * 100;
  }

  let position: ComputedIndicators['boll']['position'] = 'mid';
  if (closes[last] >= upper * 0.98) position = 'upper';
  else if (closes[last] <= lower * 1.02) position = 'lower';

  return { upper, mid: midLine[last] || 0, lower, bandwidth, position };
}

function calcRSI(closes: number[]): ComputedIndicators['rsi'] {
  const periods = [6, 12, 24] as const;
  const results: number[] = [];

  for (const p of periods) {
    const gains: number[] = [];
    const losses: number[] = [];
    for (let i = closes.length - p; i < closes.length; i++) {
      const change = closes[i] - closes[i - 1];
      gains.push(Math.max(change, 0));
      losses.push(Math.max(-change, 0));
    }
    const avgGain = gains.reduce((a, b) => a + b, 0) / p;
    const avgLoss = losses.reduce((a, b) => a + b, 0) / p;
    const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
    results.push(100 - 100 / (1 + rs));
  }

  const [rsi6, rsi12, rsi24] = results;
  let zone: ComputedIndicators['rsi']['zone'] = 'normal';
  if (rsi6 > 80 || rsi12 > 80) zone = 'overbought';
  else if (rsi6 < 20 || rsi12 < 20) zone = 'oversold';

  return { rsi6, rsi12, rsi24, zone };
}

function calcKDJ(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 9
): ComputedIndicators['kdj'] {
  const kValues: number[] = [];
  const dValues: number[] = [];

  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) {
      kValues.push(NaN);
      dValues.push(NaN);
      continue;
    }
    const hh = Math.max(...highs.slice(i - period + 1, i + 1));
    const ll = Math.min(...lows.slice(i - period + 1, i + 1));
    const rsv = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;

    const prevK = isNaN(kValues[i - 1]) ? 50 : kValues[i - 1];
    const prevD = isNaN(dValues[i - 1]) ? 50 : dValues[i - 1];

    kValues.push((2 / 3) * prevK + (1 / 3) * rsv);
    dValues.push((2 / 3) * prevD + (1 / 3) * kValues[i]);
  }

  const last = closes.length - 1;
  const prev = closes.length - 2;
  const j = 3 * kValues[last] - 2 * dValues[last];

  let signal: ComputedIndicators['kdj']['signal'] = 'neutral';
  if (
    ![kValues[prev], dValues[prev], kValues[last], dValues[last]].some(isNaN)
  ) {
    if (kValues[prev] <= dValues[prev] && kValues[last] > dValues[last])
      signal = 'goldenCross';
    else if (kValues[prev] >= dValues[prev] && kValues[last] < dValues[last])
      signal = 'deathCross';
  }

  return { k: kValues[last] || 0, d: dValues[last] || 0, j, signal };
}

function calcOBV(
  closes: number[],
  volumes: number[]
): ComputedIndicators['obv'] {
  const obvVals: number[] = [volumes[0]];
  for (let i = 1; i < closes.length; i++) {
    if (closes[i] > closes[i - 1])
      obvVals.push(obvVals[i - 1] + volumes[i]);
    else if (closes[i] < closes[i - 1])
      obvVals.push(obvVals[i - 1] - volumes[i]);
    else obvVals.push(obvVals[i - 1]);
  }

  const last = closes.length - 1;
  const obvMA = obvVals.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const priceTrend = closes[last] > sma(closes, 5)[last];
  const obvTrend = obvVals[last] > obvMA;
  let divergence: ComputedIndicators['obv']['divergence'] = 'none';
  if (priceTrend && !obvTrend) divergence = 'negative';
  else if (!priceTrend && obvTrend) divergence = 'positive';

  return { obv: obvVals[last], obvMA, divergence };
}

function calcVolumeMetrics(
  volumes: number[]
): ComputedIndicators['volume'] {
  const last = volumes.length - 1;
  const vol5 = volumes.slice(-5).reduce((a, b) => a + b, 0) / 5;
  const vol20 = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  const volRatio = vol20 > 0 ? vol5 / vol20 : 1;

  let signal: ComputedIndicators['volume']['signal'] = 'normal';
  if (volRatio > 1.5) signal = 'amplifying';
  else if (volRatio < 0.6) signal = 'shrinking';

  return { vol5, vol20, volRatio, signal };
}

function calcATR(
  highs: number[],
  lows: number[],
  closes: number[],
  period = 14
): ComputedIndicators['atr'] {
  const tr: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    tr.push(
      Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      )
    );
  }
  const atr14 =
    tr.slice(-period).reduce((a, b) => a + b, 0) / period;
  const avgPrice = closes[closes.length - 1];
  const atrPct = (atr14 / avgPrice) * 100;

  let volatility: ComputedIndicators['atr']['volatility'] = 'medium';
  if (atrPct > 5) volatility = 'high';
  else if (atrPct < 2) volatility = 'low';

  return { atr14, volatility };
}

// ─── 步骤3: 格式化为 LLM Prompt 文本 ──────────────────────────

const signalMap: Record<string, string> = {
  goldenCross: '金叉 ↑',
  deathCross: '死叉 ↓',
  bullBear: '多头力度增强',
  bearBull: '空头力度增强',
  bullish: '多头排列 ↑',
  bearish: '空头排列 ↓',
  mixed: '均线缠绕',
  upper: '上轨',
  mid: '中轨',
  lower: '下轨',
  overbought: '超买区',
  oversold: '超卖区',
  normal: '正常区间',
  amplifying: '放量',
  shrinking: '缩量',
  positive: '正背离（价跌量先行）',
  negative: '负背离（价升量不跟）',
  none: '量价正常',
  high: '高波动 ⚠️',
  medium: '中等波动',
  low: '低波动',
};

function lbl(s: string): string {
  return signalMap[s] || s;
}

function getSummary(i: ComputedIndicators): string {
  const s: string[] = [];
  if (i.macd.signal === 'goldenCross') s.push('MACD金叉，中期趋势偏多');
  else if (i.macd.signal === 'deathCross') s.push('MACD死叉，中期趋势偏空');
  if (i.ema.alignment === 'bullish') s.push('均线多头排列，趋势向上');
  else if (i.ema.alignment === 'bearish') s.push('均线空头排列，趋势向下');
  if (i.rsi.zone === 'overbought') s.push('RSI超买，短期有回调风险');
  else if (i.rsi.zone === 'oversold') s.push('RSI超卖，短期有反弹需求');
  if (i.kdj.signal === 'goldenCross') s.push('KDJ金叉，短线偏多');
  else if (i.kdj.signal === 'deathCross') s.push('KDJ死叉，短线偏空');
  if (i.volume.signal === 'amplifying') s.push('成交量放大，市场关注度高');
  else if (i.volume.signal === 'shrinking')
    s.push('成交量萎缩，观望情绪浓');
  if (i.obv.divergence === 'negative')
    s.push('⚠️ 量价负背离，上涨动能不足');
  if (i.obv.divergence === 'positive')
    s.push('💡 量价正背离，底部或已确认');
  return s.length > 0 ? s.join('；') : '趋势信号不明确，等待确认';
}

export function formatIndicatorsForPrompt(
  indicators: ComputedIndicators
): string {
  const { macd, ema, boll, rsi, kdj, obv, volume, atr } = indicators;

  return `
【量化技术指标 — 自动计算，非人工预计】

📈 趋势指标
  MACD: DIF=${macd.dif.toFixed(2)} DEA=${macd.dea.toFixed(2)} 柱=${macd.macdBar.toFixed(2)}
  MACD信号: ${lbl(macd.signal)}
  EMA排列: ${lbl(ema.alignment)} (5:${ema.ema5.toFixed(2)} / 20:${ema.ema20.toFixed(2)} / 60:${ema.ema60.toFixed(2)})
  布林带: 上${boll.upper.toFixed(2)} 中${boll.mid.toFixed(2)} 下${boll.lower.toFixed(2)} 带宽${boll.bandwidth.toFixed(1)}%
  布林位置: 当前价在${lbl(boll.position)}轨附近

📊 震荡指标
  RSI(6/12/24): ${rsi.rsi6.toFixed(1)} / ${rsi.rsi12.toFixed(1)} / ${rsi.rsi24.toFixed(1)} 
  区域: ${lbl(rsi.zone)} (${rsi.zone === 'overbought' ? '⚠️ 超买' : rsi.zone === 'oversold' ? '💡 超卖' : '正常'})
  KDJ: K=${kdj.k.toFixed(1)} D=${kdj.d.toFixed(1)} J=${kdj.j.toFixed(1)} → ${lbl(kdj.signal)}

📊 量能指标
  成交量: 5日均量=${(volume.vol5 / 10000).toFixed(0)}万  |  20日均量=${(volume.vol20 / 10000).toFixed(0)}万
  量比: ${volume.volRatio.toFixed(2)}x → ${lbl(volume.signal)}
  量价关系: ${lbl(obv.divergence)}

📊 波动指标
  ATR(14): ${atr.atr14.toFixed(2)} (占均价${((atr.atr14 / boll.mid) * 100).toFixed(1)}%) 
  波动率: ${lbl(atr.volatility)}

💡 综合判断: ${getSummary(indicators)}
`;
}

// ─── 主入口 ──────────────────────────────────────────────────────

export async function getTechnicalIndicatorText(
  symbol: string
): Promise<string> {
  const klines = await fetchKLineData(symbol, 120);
  if (klines.length < 30) {
    return `【量化技术指标】数据不足（当前${klines.length}条，需≥30天），请基于实时盘口数据做判断。`;
  }
  const indicators = computeIndicators(klines);
  if (!indicators) {
    return `【量化技术指标】计算失败，请基于实时盘口数据做判断。`;
  }
  return formatIndicatorsForPrompt(indicators);
}
