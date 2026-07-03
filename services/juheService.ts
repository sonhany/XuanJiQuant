const BACKEND_API_URL = '/api/stock';

export interface StockRealtimeData {
  gid: string;
  name: string;
  nowPri: string;
  increase: string;
  increPer: string;
  todayStartPri: string;
  yestodEndPri: string;
  todayMax: string;
  todayMin: string;
  competitivePri?: string;
  reservePri?: string;
  traNumber: string;
  traAmount: string;
  date?: string;
  time?: string;
  buyOne: string; buyOnePri: string;
  buyTwo?: string; buyTwoPri?: string;
  buyThree?: string; buyThreePri?: string;
  buyFour?: string; buyFourPri?: string;
  buyFive?: string; buyFivePri?: string;
  sellOne: string; sellOnePri: string;
  sellTwo?: string; sellTwoPri?: string;
  sellThree?: string; sellThreePri?: string;
  sellFour?: string; sellFourPri?: string;
  sellFive?: string; sellFivePri?: string;
  dapandata?: DapanData;
}

export interface DapanData {
  dot: string;
  name: string;
  nowPic: string;
  rate: string;
  traAmount: string;
  traNumber: string;
}

interface JuheApiResponse {
  resultcode: string;
  reason: string;
  result: Array<{
    data: StockRealtimeData;
    dapandata?: DapanData;
    gopicture?: {
      minurl: string;
      dayurl: string;
      weekurl: string;
      monthurl: string;
    };
  }>;
  error_code?: number;
}

function incompleteStockData(gid: string, name: string, data: any): StockRealtimeData {
  return {
    gid, name,
    nowPri: data.nowPri || '0.00',
    increase: data.increase || '0.00',
    increPer: data.increPer || '0.00',
    todayStartPri: data.todayStartPri || '0.00',
    yestodEndPri: data.yestodEndPri || '0.00',
    todayMax: data.todayMax || '0.00',
    todayMin: data.todayMin || '0.00',
    traNumber: data.traNumber || '0',
    traAmount: data.traAmount || '0',
    date: data.date || new Date().toISOString().slice(0, 10),
    time: data.time || new Date().toTimeString().slice(0, 8),
    buyOne: data.buyOne || '0',
    buyOnePri: data.buyOnePri || '0.00',
    sellOne: data.sellOne || '0',
    sellOnePri: data.sellOnePri || '0.00',
  };
}

function toStockCode(symbol: string): string {
  return symbol.replace(/^(sh|sz)/i, '').toUpperCase();
}

/**
 * 获取实时股票数据
 * dataSource: 'juhe' | 'akshare' | 'baostock' | 'tencent'
 * 自动降级: 首选 -> tencent -> akshare -> juhe -> baostock (tencent 最快且最稳定)
 */
export async function fetchStockData(
  symbol: string,
  apiKey?: string,
  dataSource: 'juhe' | 'akshare' | 'baostock' | 'tencent' = 'tencent'
): Promise<StockRealtimeData | null> {
  const sourceOrder: Record<string, string[]> = {
    tencent: ['tencent', 'akshare', 'juhe', 'baostock'],
    akshare: ['akshare', 'juhe', 'baostock', 'tencent'],
    juhe: ['juhe', 'akshare', 'tencent', 'baostock'],
    baostock: ['baostock', 'akshare', 'juhe', 'tencent'],
  };
  const sources = sourceOrder[dataSource] || sourceOrder.tencent;

  for (const source of sources) {
    try {
      const code = toStockCode(symbol);
      const endpoint = source === 'akshare'
        ? `${BACKEND_API_URL}/akshare/${code}`
        : source === 'tencent'
        ? `${BACKEND_API_URL}/tencent/${code}`
        : source === 'baostock'
        ? `${BACKEND_API_URL}/baostock/${code}`
        : `${BACKEND_API_URL}/${symbol}`;

      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol: code, apiKey })
      });

      if (!response.ok) {
        console.warn(`[${source}] ${response.status} for ${symbol}`);
        continue;
      }

      const result = await response.json();
      if (!result.success) {
        console.warn(`[${source}] API error: ${result.error}`);
        continue;
      }

      // All sources return { success: true, data: { gid, name, ... } } or similar
      const raw = result.data?.data || result.data;
      if (!raw || !raw.name) continue;

      // Normalize to StockRealtimeData shape
      const stockData = incompleteStockData(
        raw.gid || `${code.startsWith('6') ? 'sh' : 'sz'}${code}`,
        raw.name,
        raw
      );
      if (result.data.dapandata) {
        stockData.dapandata = result.data.dapandata;
      }
      return stockData;

    } catch (error) {
      console.warn(`[${source}] Request failed:`, error instanceof Error ? error.message : String(error));
    }
  }

  console.error(`[StockService] 所有数据源均失败: ${symbol}`);
  return null;
}

/**
 * 将原始 JSON 数据格式化为 AI 可读的字符串
 */
export function formatStockDataForPrompt(data: StockRealtimeData | null): string {
  if (!data) return "无法获取实时行情数据 (API连接失败)，请依赖您的内部知识库或搜索工具。";

  const val = (v: any, def = '0') => v != null && v !== '' ? v : def;
  const traNumber = parseFloat(val(data.traNumber));
  const traAmount = parseFloat(val(data.traAmount));
  const traNumberFormatted = traNumber > 10000
    ? `${(traNumber / 10000).toFixed(2)}万手`
    : `${traNumber}手`;
  const traAmountFormatted = traAmount > 100000000
    ? `${(traAmount / 100000000).toFixed(2)}亿元`
    : `${(traAmount / 10000).toFixed(2)}万元`;

  const todayMax = parseFloat(val(data.todayMax));
  const todayMin = parseFloat(val(data.todayMin));
  const currentPrice = parseFloat(val(data.nowPri));
  const dailyAmplitude = currentPrice > 0 ? ((todayMax - todayMin) / currentPrice * 100).toFixed(2) : '0.00';

  const dapandata = data.dapandata;
  const marketIndexInfo = dapandata ? `
【大盘指数】
  指数名称: ${dapandata.name}
  当前点位: ${dapandata.dot}
  涨跌幅度: ${parseFloat(dapandata.rate) >= 0 ? '+' : ''}${dapandata.rate}%
  成交量: ${dapandata.traNumber}万手
  成交额: ${dapandata.traAmount}亿元
` : '';

  const pad = (s: any, len = 8) => String(val(s)).padEnd(len);

  return `
╔══════════════════════════════════════════════════════╗
║              实时行情数据                           ║
╚══════════════════════════════════════════════════════╝

【基本信息】
  股票名称: ${data.name}
  股票代码: ${data.gid.toUpperCase()}
  数据时间: ${val(data.date, '--')} ${val(data.time, '--')}

【价格信息】
  当前价格: ¥${data.nowPri}
  涨跌幅度: ${parseFloat(data.increPer) >= 0 ? '+' : ''}${data.increPer}%
  涨跌金额: ${parseFloat(data.increase) >= 0 ? '+' : ''}¥${data.increase}
  今日开盘: ¥${data.todayStartPri}
  昨日收盘: ¥${data.yestodEndPri}
  今日最高: ¥${data.todayMax}
  今日最低: ¥${data.todayMin}

【成交情况】
  成交量: ${traNumberFormatted}
  成交额: ${traAmountFormatted}
  日振幅: ${dailyAmplitude}%
  流动性: ${traAmount > 100000000 ? '充足' : traAmount > 50000000 ? '一般' : '偏弱'}${marketIndexInfo}

【五档盘口】
  ┌────────────────────────────────────┐
  │ 卖五  ¥${pad(data.sellFivePri)}│ ${pad(data.sellFive, 10)}手 │
  │ 卖四  ¥${pad(data.sellFourPri)}│ ${pad(data.sellFour, 10)}手 │
  │ 卖三  ¥${pad(data.sellThreePri)}│ ${pad(data.sellThree, 10)}手 │
  │ 卖二  ¥${pad(data.sellTwoPri)}│ ${pad(data.sellTwo, 10)}手 │
  │ 卖一  ¥${pad(data.sellOnePri)}│ ${pad(data.sellOne, 10)}手 │ ⬅️ 压力
  ├────────────────────────────────────┤
  │ 买一  ¥${pad(data.buyOnePri)}│ ${pad(data.buyOne, 10)}手 │ ⬅️ 支撑
  │ 买二  ¥${pad(data.buyTwoPri)}│ ${pad(data.buyTwo, 10)}手 │
  │ 买三  ¥${pad(data.buyThreePri)}│ ${pad(data.buyThree, 10)}手 │
  │ 买四  ¥${pad(data.buyFourPri)}│ ${pad(data.buyFour, 10)}手 │
  │ 买五  ¥${pad(data.buyFivePri)}│ ${pad(data.buyFive, 10)}手 │
  └────────────────────────────────────┘

💡 分析提示: 请重点关注盘口买卖挂单量差异，判断主力意图
═══════════════════════════════════════════════════════
  `;
}
