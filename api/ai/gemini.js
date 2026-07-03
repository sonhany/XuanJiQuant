import { GoogleGenAI } from '@google/genai';

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;

if (!GEMINI_API_KEY) {
  console.error('[Gemini] 未配置 GEMINI_API_KEY 环境变量');
}

export default async function handler(req, res) {
  // 设置 CORS 头
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ success: false, error: 'Method not allowed' });
  }

  const { model, prompt, temperature, tools, apiKey } = req.body;

  // 优先使用 Vercel 环境变量，前端传递的 API Key 作为备用
  const effectiveApiKey = GEMINI_API_KEY || apiKey;

  if (!effectiveApiKey) {
    return res.status(500).json({
      success: false,
      error: '未配置 Gemini API Key。请在 Vercel 项目设置中配置 GEMINI_API_KEY 环境变量，或在前端临时输入 API Key'
    });
  }

  try {
    const ai = new GoogleGenAI({ apiKey: effectiveApiKey });
    
    const response = await ai.models.generateContent({
      model: model || 'gemini-2.5-flash',
      contents: prompt,
      config: {
        temperature: temperature || 0.7,
        tools: tools || [{ googleSearch: {} }]
      }
    });

    return res.json({
      success: true,
      text: response.text || ''
    });
  } catch (error) {
    console.error('[Gemini] 请求失败:', error.message);
    return res.status(500).json({
      success: false,
      error: error.message
    });
  }
}
