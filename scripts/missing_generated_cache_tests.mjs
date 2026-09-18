import fs from 'node:fs';

const API = 'http://127.0.0.1:8880';

function loadToken() {
  const envToken = process.env.XUANJI_API_TOKEN || process.env.VITE_XUANJI_API_TOKEN || '';
  if (envToken) return envToken;
  try {
    for (const line of fs.readFileSync('.env', 'utf-8').split(/\r?\n/)) {
      const match = line.match(/^(?:XUANJI_API_TOKEN|VITE_XUANJI_API_TOKEN)=(.*)$/);
      if (match) return match[1].trim().replace(/^['"]|['"]$/g, '');
    }
  } catch {}
  return '';
}

const API_TOKEN = loadToken();

async function post(route, body) {
  const response = await fetch(`${API}/api/${route}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(API_TOKEN ? { 'X-XuanJi-Token': API_TOKEN } : {}),
    },
    body: JSON.stringify(body),
  });
  const json = await response.json();
  return { status: response.status, json };
}

const factor = await post('factor', { action: 'market_eval' });
if (factor.status !== 200 || !factor.json.success) {
  throw new Error(`market_eval should degrade without generated cache, got ${factor.status} ${JSON.stringify(factor.json)}`);
}
if (!Array.isArray(factor.json.data?.factors)) {
  throw new Error('market_eval data.factors must be an array');
}

const strategy = await post('strategy', { action: 'market_scan' });
if (strategy.status !== 200 || !strategy.json.success) {
  throw new Error(`market_scan should degrade without generated cache, got ${strategy.status} ${JSON.stringify(strategy.json)}`);
}
if (!Array.isArray(strategy.json.data?.strategies)) {
  throw new Error('market_scan data.strategies must be an array');
}
if (strategy.json.data?.source === 'missing_cache_fallback' && strategy.json.data.strategies.length === 0) {
  throw new Error('market_scan should build a usable proxy scan from factor snapshot when generated cache is missing');
}

console.log('missing generated cache tests passed');
