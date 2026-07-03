# Web 页面 ↔ 后端 API ↔ Phase 1 改造映射

## 总体架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                    前端 (React 19 + TS, 端口 3333)                       │
│  App.tsx → 4 Tab: 智能分析 / 高级回测 / 数据同步 / 系统状态                │
└────────────────────────────────────────────────────────────────────────┘
                                  ↓ fetch POST/GET
┌────────────────────────────────────────────────────────────────────────┐
│              Node.js 后端 (端口 3334) + Python 量化层 (新)                │
│  routes: stock / db / qlib / sync / market / screener / cache          │
│  + 新增: /api/quant (Python 桥接) — Phase 2 待集成                       │
└────────────────────────────────────────────────────────────────────────┘
                                  ↓
┌────────────────────────────────────────────────────────────────────────┐
│         Phase 1: 数据层 (新) — Redis 缓存 + 多源回退                      │
│  quant/data/: cache.py / market_data.py / data_loader.py / universe.py │
│  quant/data/sources/: sina / tencent / baostock / node_proxy            │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Tab 1: 智能分析 (activeTab='analyze')

| Web 元素 | 调用的 API | 后端 handler | 数据源 | Phase 1 影响 |
|---------|-----------|-------------|--------|-------------|
| **股票代码输入框** | (UI) | — | — | — |
| **数据源切换按钮** (腾讯/AKShare/聚合/Baostock) | `fetchStockData()` (juheService) | `/api/stock/{akshare\|tencent\|baostock}/{code}` | `services/juheService.ts` | ⚠️ 待接入 quant 多源回退 |
| **13 个 Agent 卡片** | `runAnalystsStage/Managers/Risk/GM` | `/api/ai/{gemini\|deepseek\|qwen}` | 13 Agent LLM | 不受 Phase 1 影响 |
| **状态显示** ("获取数据..." "分析中" "完成") | WorkflowState | — | 客户端状态 | — |

**Phase 1 改造点：**
- `services/juheService.ts` → 可改为调用 `/api/quant` 端点
- 多源回退：当前是 HTTP 链，未来可走 quant `MarketDataProvider`

---

## Tab 2: 高级回测 (activeTab='qlib') — `components/QlibPanel.tsx`

| Web 元素 | 调用的 API | 后端 handler | 数据源 | Phase 1 影响 |
|---------|-----------|-------------|--------|-------------|
| **股票选择器** | `/api/db/klines?code={c}&fqt=1&limit={n}` | `handleDbKlines` | SQLite `daily_bars` | ✅ Phase 1 提供 Redis K线备选 |
| **单股分析** (因子→训练→回测) | `POST /api/qlib` | `handleQlib` | Python qlib_runner | Phase 2 改用新 quant 因子 |
| **批量回测** | `POST /api/qlib/batch-backtest` | `handleBatchBacktest` | Python qlib_runner | Phase 2 改用新 quant 组合优化 |

**Phase 1 改造点：**
- K线数据：当前读 SQLite，未来可走 `MarketDataProvider.get_history()` (Redis→多源)
- 单股/批量回测：Phase 2 改用 `quant/backtest/engine.py`

---

## Tab 3: 数据同步 (activeTab='sync') — `components/SyncPanel.tsx`

| Web 元素 | 调用的 API | 后端 handler | 数据源 | Phase 1 改造 |
|---------|-----------|-------------|--------|-------------|
| **数据源选择** (腾讯/AKShare/聚合/Baostock) | `POST /api/sync` | `handleSync` | 多源 | ✅ Phase 1 新增 `quant.data.sources.*` |
| **同步类型** (basic/daily/realtime/tick) | `POST /api/sync` | `handleSync` | 多源 | — |
| **进度条 + 实时日志** | `POST /api/sync` (action='progress') | `handleSync` | 客户端轮询 | — |
| **Tick 多股票** | `GET /api/tick/{code}` | `handleTickData` | SQLite tick | — |
| **数据库统计** | `POST /api/sync` (action='status') | `handleSync` | SQLite + Python worker | — |

**Phase 1 改造点：**
- 数据源选择器应增加 **`Redis 缓存`** 选项 (新)
- 同步目标可从 SQLite 改为 **Redis** (新)
- 待 Phase 2 集成 quant API

---

## Tab 4: 系统状态 (activeTab='db') — `components/DbPanel.tsx`

| Web 元素 | 调用的 API | 后端 handler | 数据源 | Phase 1 改造 |
|---------|-----------|-------------|--------|-------------|
| **5 个状态徽章** (API/DB/SQLite/Alpha/ML) | `/api/db/stats` + `/api/db/check` + `/api/qlib` | 多个 | 混合 | ✅ 新增 Redis 状态徽章 |
| **Alpha 引擎信息** | `POST /api/qlib` (action='status') | `handleQlib` | Python qlib_runner | — |
| **数据库统计** (股票/K线/DB大小/缓存) | `/api/db/stats` | `handleDbStats` | SQLite | ✅ 新增 Redis 统计卡片 |
| **架构卡片** (数据层/因子引擎/策略回测) | (硬编码) | — | — | ✅ Phase 1 标记已完成 |

**Phase 1 改造点：**
- 添加 **Redis 状态徽章** (新增)
- 添加 **Redis 统计** (K线数/股票数/TTL)
- 更新"数据层"卡片，反映 Redis 替换 SQLite 的进度

---

## Phase 1 在 Web 端的可验证变化

| 现状 | 改造后 | 验证方法 |
|------|-------|---------|
| 智能分析 → 数据源硬编码 4 个 | 增加 `Redis 优先` 选项（数据源切换 UI） | 浏览器切换数据源，查看 Network |
| 高级回测 → SQLite 读 K线 | 默认走 Redis 缓存，未命中回退 SQLite | Network → 响应时间对比 |
| 数据同步 → 同步到 SQLite | 同步目标增加 `Redis` | 同步完成后查看 Redis DBSIZE |
| 系统状态 → 5 个状态徽章 | 增加第 6 个 **`Redis`** 徽章 | 访问 3333/#db 看状态 |
| 系统状态 → 数据层卡片 | 标注 `[已迁移] Redis 缓存` | 静态展示 |

---

## 下一步：Phase 2 集成

需要在 Node.js server 添加 `/api/quant` 路由：
```js
// server/routes/quant.mjs (新)
export async function handleQuant(req, res) {
  const { type, ...params } = await readBody(req);
  const python = spawnSync('python', ['-c', quantDispatcher(type, params)], {
    encoding: 'utf-8', timeout: 60_000,
  });
  return json(res, 200, parseResult(python.stdout));
}
```

该路由将把请求转发给 `quant/server/api.py` 处理。
