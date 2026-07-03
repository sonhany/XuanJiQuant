# 中国A股量化交易系统 — 建设路线图

> 基于 AlphaCouncil2-AI 现状，面向实盘的完整四阶段建设路线图
> 目标市场：中国A股（沪深两市，含科创板/创业板）
> 建设周期：约 12-18 个月（业余时间）或 4-6 个月（全职）

---

## 现状评估

| 模块 | 当前状态 | 完成度 |
|------|---------|--------|
| Layer 1 数据层 | 五档行情 + 日K线 + SQLite | ~30% |
| Layer 2 因子层 | 8个技术指标（文本展示，非量化因子） | ~15% |
| Layer 3 策略层 | LLM文字分析报告（无数值信号） | ~5% |
| Layer 4 执行层 | 零 | 0% |
| Layer 5 风控层 | 文字风控建议，无实时监控 | ~10% |

---

## 四阶段总览

```
阶段一（基础建设）     → 阶段二（因子工厂）   → 阶段三（策略引擎）   → 阶段四（实盘闭环）
数据层完善              因子库 + AI因子挖掘      策略信号 + 组合优化     全自动化 + 实盘接入
预计 2-3 个月           预计 3-4 个月            预计 3-4 个月          预计 2-3 个月
总计：约 11-16 个月业余时间 / 4-6 个月全职
```

---

## 阶段一：数据层重建 优先级：🔴 最高

> "垃圾进，垃圾出" — 数据是整个系统的根基

### 1.1 数据库选型

| 选项 | 适合场景 | 推荐度 |
|------|---------|--------|
| TimescaleDB | 中小规模（千万~亿级）| ⭐⭐⭐⭐⭐ |
| ClickHouse | 超大规模（十亿级以上）| ⭐⭐⭐ |
| InfluxDB | 纯时序，超高频 | ⭐⭐⭐ |
| MySQL + 分表 | 简单存储 | ⭐⭐ |

**推荐：TimescaleDB（PostgreSQL 超扩展）**
- A 股 5000+ 股票 × 240 分钟 × 250 天 ≈ 3亿行/年分钟数据
- TimescaleDB 自动分区，一台 8 核 32G 服务器足够支撑个人量化
- PostgreSQL 生态，SQL 友好，学习成本极低

### 1.2 中国A股数据源

#### 实时行情（必须接入）

| 数据源 | 延迟 | 成本 | 推荐度 |
|--------|------|------|--------|
| Tushare Pro | ~1-3秒 | 免费（需积分）| ⭐⭐⭐⭐⭐ |
| 聚合数据 | 3-5秒 | 付费 | ⭐⭐⭐ |
| 腾讯/新浪 | 3-5秒 | 免费 | ⭐⭐⭐ |
| AKShare 东方财富 | 5-10秒 | 免费 | ⭐⭐ |

**Tushare Pro 积分要求：**
- 日线数据：需 1200 积分
- 分钟数据：需 2000 积分
- 实时行情：需 500 积分
- 财务数据：需 4000 积分（最终目标）

#### Level-2 行情（核心差距）

| 数据源 | 延迟 | 成本 | 推荐度 |
|--------|------|------|--------|
| 财富聚 (FortuneAPI) | <500ms | ¥299/月 | ⭐⭐⭐⭐ |
| Tushare Level-2 | <1s | 积分 5000+ | ⭐⭐⭐⭐ |
| 聚宽（JoinQuant） | <1s | 免费（有限额）| ⭐⭐⭐ |

**建议路径：Tushare Pro（日线/分钟/财务） → Tushare Level-2（十档） → 财富聚（逐笔）**

### 1.3 阶段一技术架构

```
                    WebSocket / 轮询（30秒）
                          │
┌─────────────────────────────────────────────────────────┐
│                    数据采集服务                           │
│  TushareCollector   — 日K/分钟/财务数据                  │
│  RealtimeCollector  — 实时行情轮询                       │
│  IndexCollector     — 指数/北向/两融                     │
│  NewsCollector      — 财经新闻（定时）                   │
└─────────────────────┬───────────────────┬────────────────┘
                     ↓                   ↓
        ┌────────────────────┐  ┌────────────────────┐
        │   TimescaleDB      │  │       Redis        │
        │  (历史+财务+因子)   │  │  (当前行情缓存)    │
        │   PostgreSQL超扩展   │  │  涨跌/持仓/信号    │
        └────────────────────┘  └────────────────────┘
```

### 1.4 阶段一任务清单

```
P0（必须，完成后才能进阶段二）
├── [ ] 注册 Tushare Pro，积累积分到 2000+
├── [ ] 搭建 TimescaleDB 环境（Docker 1行命令）
├── [ ] 重写数据采集服务（TushareCollector）
│   ├── 日K线全量采集（2000年至今，所有股票）
│   ├── 分钟K线采集（1分钟/5分钟）
│   └── 每日增量更新（收盘后定时任务）
├── [ ] 实时行情轮询（30秒间隔，存 Redis）
│   ├── 股票当前价/涨跌幅/成交量
│   └── 指数（上证/深证/创业板/科创50）
├── [ ] 北向资金 + 两融余额 每日采集
└── [ ] 数据质量验证
    ├── 缺失值检测（停牌日期）
    ├── 复权价格验证（前复权/后复权）
    └── 成交量/成交额合理性

P1（重要，可并行）
├── [ ] 历史财务数据采集（PE/PB/ROE/营收/利润）
├── [ ] 指数成分股变更跟踪
├── [ ] 新闻数据源接入（财联社/东方财富）
└── [ ] 数据字典文档（所有表结构说明）
```

### 1.5 阶段一时间预估

| 任务 | 复杂度 | 预估工时 |
|------|--------|---------|
| Tushare 接口申请 + 调试 | 低 | 4h |
| TimescaleDB 部署 | 低 | 2h |
| 日K线全量采集 | 中 | 8h |
| 分钟数据采集 | 中 | 6h |
| 实时行情轮询 | 中 | 8h |
| 财务数据采集 | 中 | 6h |
| 数据质量验证 | 低 | 4h |
| **阶段一小计** | — | ~38h（约3-4周业余时间） |

---

## 阶段二：因子工厂 优先级：🔴 最高

> "因子是量化系统的原材料"
> AlphaCouncil2 的 8 个技术指标只是展示用，真正的因子要进计算流水线

### 2.1 因子分类体系（A股专用）

```
因子总库目标：150+ 因子
```

#### 量价类因子（~50因子，P0优先）

```
趋势类：MA/EMA/SAR/MACD/KDJ
动量类：RSI/CCI/ROC/MOM/DMI
波动类：ATR/布林带/Keltner通道/历史波动率
量价类：OBV/MFI/VR/量价背离
反转类：5日反转/20日反转/跳空缺口
```

#### 基本面因子（~60因子，P1）

```
估值类：PE/PB/PS/PCF/股息率/PEG
成长类：营收增速/净利润增速/毛利率变化/ROE/ROA/ROIC
质量类：资产负债率/流动比率/周转率/商誉比
预期类：分析师评级/一致预期EPS/研报覆盖数量
```

#### 市场结构因子（~30因子，P1，A股特色）

```
资金流向：北向资金/主力净流入/融资净买入
情绪类：涨停数量/跌停数量/炸板率/连板高度
轮动类：申万行业动量/风格轮动/ETF净申购
事件类：龙虎榜/大宗交易/业绩预告/增持减持
```

#### AI 因子（~10因子，P2）

```
文本情绪因子（新闻NLP）/ 量价图像特征（CNN）
产业链关系因子 / 另类数据因子 / 机构调研频次
```

### 2.2 因子处理流水线

```
原始因子值
    │
    ├── 缺失值处理（停牌日：前向填充）
    ├── 去极值（MAD / 3σ裁断 / Percentile）
    ├── 标准化（Z-score / Rank-based 横截面）
    ├── 中性化（市值 + 行业回归残差）
    └── 正交化（Gram-Schmidt）

处理后因子 ──→ 因子库（TimescaleDB）
    │
    ├── IC 跟踪（每日/每周/每月）
    ├── IR（IC均值/IC标准差）
    └── 因子衰减分析（因子寿命）
```

### 2.3 因子库表结构（TimescaleDB）

```sql
-- 因子库主表（TimescaleDB 自动分区，按月）
CREATE TABLE factors (
    trade_date DATE NOT NULL,
    code        TEXT NOT NULL,
    factor_name TEXT NOT NULL,
    value       DOUBLE PRECISION,
    CONSTRAINT factors_pkey PRIMARY KEY (trade_date, code, factor_name)
);
SELECT create_hypertable('factors', 'trade_date');

-- 因子元数据表
CREATE TABLE factor_metadata (
    factor_name   TEXT PRIMARY KEY,
    category      TEXT,
    sub_category  TEXT,
    description   TEXT,
    author        TEXT,
    created_at    TIMESTAMP,
    ic_mean       DOUBLE PRECISION,
    ic_std        DOUBLE PRECISION,
    ir            DOUBLE PRECISION,
    is_active     BOOLEAN DEFAULT TRUE
);

-- IC 跟踪表
CREATE TABLE factor_ic_log (
    trade_date    DATE,
    factor_name   TEXT,
    ic            DOUBLE PRECISION,
    rank_ic       DOUBLE PRECISION,
    PRIMARY KEY (trade_date, factor_name)
);
SELECT create_hypertable('factor_ic_log', 'trade_date');
```

### 2.4 阶段二任务清单

```
P0（必须）
├── [ ] 因子计算框架（Python，numpy向量化）
│   ├── 基础：50+ 量价因子
│   ├── 进阶：20+ 基本面因子
│   └── 高阶：10+ 市场结构因子
├── [ ] 因子处理流水线
│   ├── 去极值 + 标准化 + 中性化
│   └── 因子 IC/IR 每日自动计算 + 入库
├── [ ] 因子库（TimescaleDB）
│   ├── 因子计算结果写入
│   ├── 因子筛选 API（IC > 0.02 的有效因子）
│   └── 因子相关性分析工具
└── [ ] 因子监控面板
    ├── IC 热力图（因子有效性）
    ├── IR 衰减曲线（因子寿命）
    └── 新增因子快速回测（5分钟验证）

P1（重要）
├── [ ] A股特色因子（涨跌停/北向/两融/龙虎榜）
├── [ ] 基本面因子集（60+）
├── [ ] AI 因子挖掘（文本情绪 / 量价图像）
└── [ ] 因子组合工具（IC加权/最大化IR加权）
```

### 2.5 阶段二时间预估

| 任务 | 复杂度 | 预估工时 |
|------|--------|---------|
| 因子计算框架搭建 | 高 | 16h |
| 50+ 量价因子实现 | 中 | 20h |
| 因子处理流水线 | 高 | 12h |
| 因子库 + API | 中 | 10h |
| IC/IR 监控面板 | 中 | 8h |
| 基本面因子（60+）| 高 | 24h |
| A股特色因子 | 中 | 16h |
| AI 因子（NLP/图像）| 高 | 20h |
| **阶段二小计** | — | ~126h（约8-10周业余时间） |

---

## 阶段三：策略引擎 优先级：🔴 最高

> "这是从数据到决策的核心跃迁"
> 从 LLM 文字建议 → 精确数值信号

### 3.1 信号合成框架

```
多因子加权信号
       │
       ├── 第一步：因子加权
       │   ├── IC 加权（根据近期 IC/IR 动态调整）
       │   ├── 均值方差优化（最大化 IC/IR）
       │   └── 等权（基准）
       │
       ├── 第二步：信号生成
       │   ├── 因子打分（z-score 排名加权求和）
       │   ├── 信号阈值（Top 20% → 多头信号）
       │   └── 方向判断（看多/看空/中性）
       │
       ├── 第三步：风控过滤
       │   ├── 市场环境过滤（沪深300多头时才能做多）
       │   ├── 行业集中度过滤（单行业 < 30%）
       │   ├── 个股流动性过滤（日均成交额 > 5000万）
       │   └── 涨跌停过滤（涨停不买/跌停不卖）
       │
       └── 第四步：输出数值信号
           {
             "code": "600519",
             "signal": "LONG",
             "score": 0.82,
             "weight": 0.08,
             "entry_price": null,
             "stop_loss": -0.05,
             "take_profit": 0.12,
             "hold_days_max": 20,
             "priority": 3,
             "risk_level": "MEDIUM",
             "reason": "因子打分0.82，ROE高位，量价突破"
           }
```

### 3.2 策略类型覆盖

| 策略类型 | 难度 | 说明 | 优先级 |
|---------|------|------|--------|
| 多因子选股 | 中 | 核心策略 | P0 |
| 行业轮动 | 中 | 申万行业动量 | P0 |
| 北向资金跟随 | 低 | 跟北向聪明钱 | P0 |
| 指数增强 | 中 | 对标沪深300/中证500 | P1 |
| 大小盘轮动 | 中 | 沪深300 vs 中证1000 | P1 |
| 事件驱动 | 中 | 业绩超预期/增持/定增 | P1 |
| CTA 趋势 | 高 | 分钟线级别，期货/ETF | P2 |
| 套利策略 | 高 | 期现/跨品种/ETF | P2 |

### 3.3 组合优化器

```python
# 目标：最大化预期收益 / 最小化风险
# 约束：
#   - 单股权重 <= 10%
#   - 单行业权重 <= 30%
#   - 总仓位 <= 95%（留5%现金）
#   - 最小持仓股票数 >= 10
#   - 与基准行业偏离 <= 10%

from scipy.optimize import minimize
import numpy as np

def portfolio_optimize(signals_df, cov_matrix):
    n = len(signals_df)
    if n == 0: return []

    constraints = []
    constraints.append({'type': 'eq', 'fun': lambda w: np.sum(w) - 0.95})

    for i in range(n):
        constraints.append({'type': 'ineq', 'fun': lambda w, i=i: 0.10 - w[i]})

    industries = signals_df['industry'].unique()
    for ind in industries:
        ind_mask = (signals_df['industry'] == ind).values
        constraints.append({'type': 'ineq',
                            'fun': lambda w, m=ind_mask: 0.30 - np.sum(w[m])})

    def objective(w):
        return 0.5 * w @ cov_matrix @ w  # 组合方差

    w0 = np.ones(n) / n
    result = minimize(objective, w0, method='SLSQP', constraints=constraints)
    return result.x
```

### 3.4 A股特有回测规则

```python
class AShareBacktestEngine:
    """A股回测特殊处理"""

    def can_buy(self, stock, date):
        # 涨跌停不买（买不进去）
        if stock.limit_up_today(date):
            return False, "涨停板封死"
        # 停牌不买
        if stock.suspended(date):
            return False, "停牌中"
        # T+1
        if self.had_position_yesterday(stock, date):
            return False, "T+1 规则"
        return True, ""

    def can_sell(self, stock, date):
        # 跌停卖不出
        if stock.limit_down_today(date):
            return False, "跌停板封死"
        # T+1
        if self.bought_today(stock, date):
            return False, "T+1 规则"
        return True, ""

    def estimate_slippage(self, stock, amount):
        """滑点估算"""
        liquidity = stock.avg_volume_20d()
        if liquidity < 5000_万:    return 0.003   # 0.3%
        elif liquidity < 2_亿:     return 0.001   # 0.1%
        else:                       return 0.0005  # 0.05%
```

### 3.5 回测引擎升级目标

| 功能 | 当前 | 目标 |
|------|------|------|
| 回测频率 | 日线 | 日线 + 1/5/15/30/60 分钟 |
| 选股范围 | 单股/批量 | 全市场 5000+ |
| 持仓方式 | 多头 | 多头+空头（需券商支持） |
| 成本模型 | 固定 0.1% | 滑点 + 冲击成本 + 印花税 |
| 成交模拟 | 无 | T+1 模拟 + 涨跌停模拟 |
| 基准对比 | 无 | 沪深300 + 中证500 + 绝对收益 |
| 归因分析 | 无 | Brinson 归因 + 因子暴露分析 |

### 3.6 阶段三任务清单

```
P0（必须）
├── [ ] 信号合成框架
│   ├── 因子加权模型（IC加权/等权/优化）
│   ├── 横截面打分排序
│   ├── 信号阈值 + 方向判定
│   └── 输出标准化 JSON 信号
├── [ ] A股风控过滤模块
│   ├── 涨跌停过滤
│   ├── T+1 规则处理
│   ├── 流动性过滤
│   └── 行业集中度过滤
├── [ ] 组合优化器
│   ├── scipy.optimize 均值方差
│   ├── 约束条件引擎
│   └── 权重分配算法
└── [ ] 专业回测引擎
    ├── 分钟级回测支持
    ├── A股成本模型
    ├── 成交模拟（涨跌停/T+1）
    └── 业绩归因分析

P1（重要）
├── [ ] 行业轮动策略
├── [ ] 北向资金跟随策略
├── [ ] 多策略并行（选股+轮动+事件）
├── [ ] 策略信号 API（供 Layer 4 调用）
└── [ ] 回测报告自动生成

P2（扩展）
├── [ ] CTA 趋势策略（分钟线）
├── [ ] 事件驱动策略
└── [ ] Barra 风险模型
```

### 3.7 阶段三时间预估

| 任务 | 复杂度 | 预估工时 |
|------|--------|---------|
| 信号合成框架 | 高 | 16h |
| A股风控过滤 | 中 | 10h |
| 组合优化器 | 高 | 12h |
| 专业回测引擎 | 高 | 20h |
| 行业轮动策略 | 中 | 12h |
| 北向跟随策略 | 低 | 6h |
| 多策略并行 | 高 | 16h |
| 归因分析 | 中 | 10h |
| **阶段三小计** | — | ~102h（约7-8周业余时间） |

---

## 阶段四：执行层 + 风控闭环 优先级：🔴 最高

> "让系统真正能动起来"
> 从"模拟"到"真实"的最后一步

### 4.1 执行层 — 券商接口选择

| 接口 | 门槛 | 成本 | 功能 | 推荐度 |
|------|------|------|------|--------|
| QMT（迅投） | 低，用户最多 | 免费 | 完整 | ⭐⭐⭐⭐⭐ |
| PTrade（恒生） | 中 | 免费/收费 | 完整，高频好 | ⭐⭐⭐⭐ |
| XTP（夕乐） | 高 | 收续费 | 机构级，最快 | ⭐⭐⭐ |
| Mini Band（华泰） | 机构专属 | 高 | 完整 | ⭐⭐ |

**推荐路径：QMT → PTrade（资金门槛低，生态成熟）**

### 4.2 QMT 接入方案

```
QMT（迅投极速交易系统）
   │
   ├── 本地 Python API（miniqmt）
   │   ├── xtquant() 获取行情
   │   ├── order() 市价/限价下单
   │   ├── order_tree() 批量下单
   │   └── get_position() 获取持仓
   │
   └── 限制
       ├── 每账户每秒最多 30 笔
       ├── 隔夜持仓需 15:05 前确认
       └── 部分券商有资金门槛
```

### 4.3 系统架构（Layer 4）

```
策略信号（Layer 3）
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│                  交易执行引擎                            │
│  信号验证器 → 订单生成器 → 订单管理（OMS）→ 算法执行    │
└──────────────────────────┬──────────────────────────────┘
                           ↓
                    QMT / PTrade 接口
              下单 → 券商柜台 → 交易所撮合
              ←── 成交回报 / 持仓更新 ──←
                           ↓
┌─────────────────────────────────────────────────────────┐
│              Layer 5: 风控层                            │
│  事前：黑名单 / 仓位上限 / 流动性 / T+1                 │
│  事中：硬止损 / 移动止盈 / 回撤熔断 / 持仓监控          │
│  事后：盘后报告 / 归因分析                              │
└──────────────────────────┬──────────────────────────────┘
                           ↓
                    Redis（实时状态）
            持仓 / 挂单 / 浮动盈亏 / 当日成交
                           ↓
                    监控面板（实时）
          持仓 / 浮盈亏 / 夏普 / 最大回撤 / 告警推送
```

### 4.4 风控体系（A股特色）

```python
class AShareRiskManager:
    """A股全链路风控"""

    # ── 事前风控（下单前）────────────────────────────
    def pre_trade_check(self, signal, position_manager):
        # 1. 黑名单过滤（ST/*ST/新股首日）
        if self.in_blacklist(signal.code):
            return False, "黑名单股票"
        # 2. 仓位上限（单股 <= 10%）
        current_weight = position_manager.get_weight(signal.code)
        if current_weight + signal.weight > 0.10:
            return False, f"仓位超限：{current_weight:.1%}+{signal.weight:.1%}>10%"
        # 3. 总仓位上限（<= 95%）
        if position_manager.total_exposure() > 0.95:
            return False, "总仓位已满"
        # 4. 流动性检查（20日均成交额 > 5000万）
        if not self.liquidity_ok(signal.code):
            return False, "流动性不足"
        # 5. 涨跌停状态
        if self.limit_up_today(signal.code):
            return False, "涨停板，无法买入"
        # 6. T+1
        if self.bought_today(signal.code):
            return False, "T+1 规则：今日已买入"
        return True, "通过"

    # ── 事中风控（持仓监控）─────────────────────────
    def monitor_position(self, position, current_price):
        pnl_pct = (current_price - position.entry_price) / position.entry_price
        # 硬止损 -5%
        if pnl_pct <= -0.05:
            return 'STOP_LOSS', f"触发硬止损：{pnl_pct:.2%}"
        # 移动止盈 +12% 回撤3%触发
        if pnl_pct >= 0.12:
            if position.trailing_stop is None:
                position.trailing_stop = current_price * 0.97
            elif current_price < position.trailing_stop:
                return 'TAKE_PROFIT', f"移动止盈：{pnl_pct:.2%}"
        # 回撤熔断 -3%
        if self.get_today_pnl() <= -self.total_capital * 0.03:
            return 'CIRCUIT_BREAKER', "总资金回撤3%，停止交易"
        return 'HOLD', ''

    # ── 事后风控（收盘后）───────────────────────────
    def post_close_report(self, trading_log):
        # 当日盈亏 / 胜率统计 / 滑点分析 / 因子暴露报告
```

### 4.5 阶段四任务清单

```
P0（必须，实盘核心）
├── [ ] QMT 接口接入
│   ├── miniqmt 安装 + 账号对接
│   ├── 行情订阅（实时价格）
│   ├── 下单/撤单/持仓查询 API
│   └── 成交回报处理
├── [ ] 订单管理系统（OMS）
│   ├── 信号 → 订单 转换
│   ├── 下单状态跟踪
│   ├── 失败重试（最多3次）
│   └── 订单日志完整记录
├── [ ] 事前风控引擎
│   ├── 黑名单过滤（ST/*ST/新股）
│   ├── 仓位上限检查
│   ├── 流动性门槛
│   └── T+1 规则处理
├── [ ] 事中风控引擎
│   ├── 实时止损（硬止损 + 移动止盈）
│   ├── 回撤熔断
│   ├── 持仓实时监控（每秒检查）
│   └── 告警推送（微信/短信）
├── [ ] 持仓同步 + 盈亏计算
│   ├── 浮动盈亏实时更新
│   ├── 实现盈亏计算
│   └── 持仓成本管理
└── [ ] 实时监控面板
    ├── 持仓 / 浮盈亏展示
    ├── 夏普 / 最大回撤 实时
    ├── 成交记录流水
    └── 告警历史

P1（重要）
├── [ ] TWAP/VWAP 算法执行（大单拆小）
├── [ ] 盘后清算报告自动生成
├── [ ] 策略信号与持仓联动
├── [ ] 隔夜仓位管理（15:05 前自动处理）
└── [ ] 历史交易记录 + 业绩归因

P2（扩展）
├── [ ] PTrade 接口（高频策略支持）
├── [ ] Level-2 委托队列整合
├── [ ] 夜盘商品期货联动（如有）
└── [ ] 多账户管理
```

### 4.6 阶段四时间预估

| 任务 | 复杂度 | 预估工时 |
|------|--------|---------|
| QMT 接口接入 | 中 | 12h |
| OMS 订单管理系统 | 高 | 16h |
| 事前风控引擎 | 中 | 10h |
| 事中风控引擎 | 高 | 16h |
| 持仓同步 + 盈亏计算 | 中 | 10h |
| 实时监控面板 | 中 | 12h |
| TWAP/VWAP 算法 | 高 | 16h |
| 盘后清算报告 | 低 | 6h |
| 告警推送（微信） | 低 | 4h |
| 策略与持仓联动 | 高 | 12h |
| **阶段四小计** | — | ~114h（约8-10周业余时间） |

---

## 全阶段汇总

| 阶段 | 核心任务 | P0 工时 | 总工时 | 业余时间 |
|------|---------|---------|--------|---------|
| 阶段一：数据层 | TimescaleDB + Tushare 采集 | 38h | 38h | 3-4周 |
| 阶段二：因子工厂 | 150+ 因子库 + IC/IR 流水线 | 76h | 126h | 8-10周 |
| 阶段三：策略引擎 | 信号合成 + 组合优化 + 回测 | 70h | 102h | 7-8周 |
| 阶段四：执行层 | QMT接入 + OMS + 风控 + 面板 | 82h | 114h | 8-10周 |
| **总计** | | **266h** | **380h** | **26-32周（6-8个月）** |

---

## 优先级排序（推荐执行顺序）

```
立即开始（本周）
├── [ ] 注册 Tushare Pro，写接口申请
├── [ ] Docker 部署 TimescaleDB（1行命令）
└── [ ] 重写日K线采集脚本（复用现有 download_history.py 逻辑）

第一周周末
├── [ ] 分钟数据采集（Tushare 分钟接口）
├── [ ] 实时行情轮询（30秒，存 Redis）
└── [ ] 因子计算框架（Python 向量化）

第一个月
├── [ ] 50+ 量价因子实现
├── [ ] 因子 IC/IR 跟踪系统
├── [ ] 信号合成框架
└── [ ] A股风控过滤（T+1/涨跌停）

第二个月
├── [ ] 组合优化器
├── [ ] 专业回测引擎（分钟级）
├── [ ] QMT 接口接入
└── [ ] OMS 订单管理系统

第三个月
├── [ ] 实时风控引擎
├── [ ] 监控面板
└── [ ] 微信告警推送
```

---

## 关键技术栈汇总

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 数据库 | TimescaleDB | PostgreSQL 超扩展，时序数据首选 |
| 缓存 | Redis | 实时行情/持仓缓存 |
| 采集 | Python（Tushare SDK）| 官方 SDK，稳定可靠 |
| 因子计算 | Python（NumPy/Pandas）| 向量化，批量计算 |
| 因子库 | TimescaleDB | 时序分区，SQL 查询 |
| 策略框架 | Python（NumPy/scipy）| 信号合成/组合优化 |
| 回测引擎 | Python（自研）| A股规则内置 |
| 执行接口 | miniQMT（Python）| 迅投官方 |
| 监控面板 | React（复用现有前端）| 增强 AlphaCouncil2 |
| 告警推送 | 微信测试号 / Server酱 | 免费即时推送 |
| 调度 | Python APScheduler | 定时任务 |

---

## 与 AlphaCouncil2 的集成方案

```
现有 AlphaCouncil2-AI                          增强版
    │                                              │
    ▼                                              ▼
App.tsx（13 Agent 协作界面）        →      增强：保留 AI 分析模块
    │                                     + 新增：量化策略信号面板
    │                                              │
    ▼                                              ▼
QlibPanel（回测界面）             →      增强：接入 TimescaleDB 历史数据
    │                                     + 新增：实盘持仓监控 Tab
    │                                              │
    ▼                                              ▼
服务端（Node.js）               →      增强：Python 微服务（因子计算+策略）
    │                                     + Python 微服务（执行引擎+QMT）
    │                                              │
    ▼                                              ▼
SQLite（本地）                   →      TimescaleDB（历史）
    │                                     + Redis（实时）
    │                                              │
    ▼                                              ▼
（无）                          ←      QMT 接口 → 真实下单
```

**集成策略：**
1. Node.js 服务保留，作为 Web UI 层和 API 网关
2. Python 微服务独立部署（因子计算、策略引擎、执行引擎）
3. 通过 HTTP/gRPC 通信，Node.js 做路由分发
4. 现有 Agent 分析模块保持，作为策略辅助研究工具
5. AlphaCouncil2 的价值转向"AI 研究员"，专注分析 + 风控判断

---

## 风险与注意事项

```
⚠️ 法律风险
├── 未经券商书面授权的程序化交易可能违规
├── 建议：先使用模拟账户测试，待系统稳定后再申请实盘授权
└── 重大：实盘前务必咨询券商合规部门

⚠️ 技术风险
├── Tushare 积分获取需要时间和贡献
├── QMT 券商支持有限（仅支持部分券商）
├── Level-2 数据成本较高
└── A股政策变化（涨跌停/T+1制度）可能影响策略逻辑

⚠️ 量化策略风险
├── Alpha 因子寿命（A 股约 3-6 个月，美股 1-2 年）
├── 滑点估算不准确会导致回测虚高
└── 流动性风险（小盘股）容易被忽略

⚠️ 运维风险
├── 服务器断网 = 当日无法交易
├── 数据库损坏 = 历史数据丢失
└── 建议：配置服务器告警 + 定期备份
```

---

*本路线图可根据实际进展灵活调整。建议每个月末回顾进度，重新评估优先级。*
