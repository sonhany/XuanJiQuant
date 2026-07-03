import fetch from 'node-fetch';

const JUHE_API_KEY = process.env.JUHE_API_KEY;
const JUHE_BASE_URL = 'http://web.juhe.cn/finance/stock/hs';

if (!JUHE_API_KEY) {
  console.error('[Juhe Data] 未配置 JUHE_API_KEY 环境变量');
}

export default async function handler(req, res) {
  // 设置 CORS 头
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  let symbol, apiKey;
  
  // 支持 GET 和 POST 两种方式
  if (req.method === 'GET') {
    symbol = req.query.symbol;
    apiKey = req.query.apiKey;
  } else if (req.method === 'POST') {
    symbol = req.body.symbol;
    apiKey = req.body.apiKey;
  }

  if (!symbol) {
    return res.status(400).json({ success: false, error: '缺少股票代码' });
  }

  // 优先使用 Vercel 环境变量，前端传递的 API Key 作为备用
  const effectiveApiKey = JUHE_API_KEY || apiKey;

  if (!effectiveApiKey) {
    return res.status(500).json({
      success: false,
      error: '未配置聚合数据 API Key。请在 Vercel 项目设置中配置 JUHE_API_KEY 环境变量，或在前端临时输入 API Key'
    });
  }

  // 格式化股票代码
  let gid = symbol.toLowerCase();
  if (!gid.startsWith('sh') && !gid.startsWith('sz')) {
    if (gid.startsWith('6')) {
      gid = `sh${gid}`;
    } else {
      gid = `sz${gid}`;
    }
  }

  const url = `${JUHE_BASE_URL}?gid=${gid}&key=${effectiveApiKey}`;

  try {
    const response = await fetch(url);
    const data = await response.json();

    if (data.resultcode !== '200') {
      return res.status(400).json({
        success: false,
        error: data.reason || '未知错误'
      });
    }

    return res.json({
      success: true,
      data: data.result[0]
    });
  } catch (error) {
    console.error('获取股票数据失败:', error);
    return res.status(500).json({
      success: false,
      error: '服务器内部错误'
    });
  }
}
