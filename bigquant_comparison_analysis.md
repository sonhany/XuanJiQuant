# XuanJiQuant vs BigQuant 交易系统专业对比分析报告

## 项目概览：XuanJiQuant

**架构设计（5层API + React前端）：**
- **第1层(数据)**: `/api/data` - 股票列表、K线查询、财务报表、实时行情、热点快照、tick采集器
- **第2层(因子)**: `/api/factor` - 因子元数据、评估、市场股票
- **第3层(策略)**: `/api/strategy` - 元数据、市场扫描、研究筛选
- **第4层(执行)**: `/api/execution` - 账户、持仓、订单、成交（仅F5模拟交易）
- **第5层(风控)**: `/api/risk` - 投资组合风控、系统健康、审计日志、决策轨迹
- **前端**: React + Vite，包含ExecutionPanel、PaperStrategyConfig及20多个分析面板
- **存储**: 默认SQLite（data/quant.db），可选Redis
- **运行时**: 持久化Python运行器（通过PersistentRunner），策略/风控/执行运行器

**BigQuant代码引用：**
- `quant/factor/lens.py`: "参考BigQuant FactorLens设计"
- `quant/distributed/executor.py`: "参考BigQuant FAI轻量版"
- `quant/backtest/fast_engine.py`: "参考BigQuant极速模式"

## 相对于BigQuant BigTrader的关键不足

| 类别 | XuanJiQuant局限 | BigQuant优势 |
|------|----------------|--------------|
| **执行引擎** | Python-based SQLite持久化模拟（F5）；无C++核心引擎 | C++核心撮合引擎，实现回测/模拟/实盘一致性|
| **市场覆盖** | A股为主（股票、基本因子） | 全市场：股票+基金+期货+可转债+指数+两融等 |
| **频率支持** | 主要日/Bar频率 | 日频+分钟+Tick+逐笔(Tick2)全部支持 |
| **策略回调框架** | 极简：状态/运行/订单/成交 | 丰富：initialize→before_trading_start→handle_data/handle_tick→handle_order/handle_trade→after_trading |
| **数据契约一致性** | SQLiteSchema可能随环境变化 | 保证跨环境100%Schema一致性（Arrow Flight协议） |
| **分布式计算** | LocalExecutor（concurrent.futures）基础多进程 | FAI：Ray-based水平扩展到云端集群 |
| **高性能数据传输** | HTTP/JSON over SQLite | Apache Arrow Flight：二进制直达、内存直接映射、多通道并行下载 |
| **策略编辑** | 代码优先；部分React面板用于配置/分析 | 完整Web IDE：可视化策略编辑器、拖拽式、Notebook式编辑 |
| **风控 granularity** | 熔断开关、质量门(F4)、执行通道 | 多层次：持仓限额、风险警报、熔断器、每策略滑点模型 |
| **状态同步** | 本地SQLite仅 | 本地↔云端状态同步、加密信道、跨日user_store持久化 |

## 改进方向

1. **升级执行引擎架构**
   - 设计C++兼容订单匹配接口
   - 实现统一引擎支持日/分钟/Tick模式
   - 确保回测/模拟/实盘引擎一致性

2. **扩展市场覆盖**
   - 添加期货、期权支持
   - 实现两融（融资融券）机制
   - 支持更广泛的标的类型

3. **丰富策略回调系统**
   - 采用BigQuant回调模式：initialize→before_trading_start→handle_data→handle_tick→handle_order→handle_trade→after_trading
   - 使策略逻辑更模块化、更易调试

4. **实施数据契约标准**
   - 定义统一DataFrame模式（日期、代码、开高低收、成交量、复权标志）
   - 在API边界添加模式验证
   - 版本化数据契约

5. **实现数据同步机制**
   - 跨日持久化状态（类似user_store）
   - 实现本地↔云端账户状态同步
   - 支持模拟↔实盘无缝过渡

6. **分布式因子计算**
   - 用Ray集成增强LocalExecutor
   - 启用批量因子计算的水平扩展
   - 支持云集群分布式计算（FAI灵感）

7. **高性能数据管线**
   - 用二进制列式格式替代 ad-hoc HTTP获取
   - 实现带模式演进支持的缓存层
   - 添加行情WebSocket流式传输（实时行情）

8. **因子分析平台完成**
   - 完成FactorLens特性：分布式分析、行业/市值分层、拥挤度分析
   - 添加因子IC排名、换手率、集中度风险指标
   - 提供一键综合因子诊断报告

9. **可视化策略编辑框架**
   - 开发最小化可视化编辑器用于常见策略
   - 支持策略模板库（类似BigQuant策略商城）
   - 启用拖拽式订单构建用于原型设计

10. **风控控制增强**
    - 添加持仓限额监控
    - 实现滑点模型（固定/百分比）
    - 添加成交量限制控制（类似BigQuant volume_limit参数）
    - 实现自动取消无法成交订单

## 值得从BigQuant复刻的功能架构

| 架构元素 | 复刻原因 | 实施方案 |
|----------|----------|----------|
| **C++核心订单匹配引擎** | 性能、回测/模拟/实盘一致性、低延迟 | 与C++团队合作或采用开源匹配引擎（如Crossing Engine）；通过Python C-extensions封装 |
| **统一策略回调框架** | 模块化策略逻辑、更易调试、跨模式一致性 | 重构现有策略运行器采用此回调模式；保持向后兼容 |
| **数据契约设计，附带Schema保证** | 防止环境导致策略 breakage | 定义统一DataFrame Schema；在API边界添加Schema验证；版本化数据契约 |
| **Arrow Flight-style数据传输** | 亿级因子/数据处理性能 | 评估Apache Arrow集成；二进制列式 IPC |
| **状态同步机制（本地↔云端）** | 启用模拟↔实盘过渡、策略持久化 | 设计账户状态模块，支持加密同步；支持Redis-backed persistent user_store |
| **多频率支持（日/分钟/Tick）** | 策略灵活性、更快开发周期 | 全局抽象频率参数；添加分钟/Tick数据适配器，补充现有日数据 |
| **综合风险控制系统** | 专业级防护措施 | 实施多层次：持仓限额、滑点模型、成交量限制、熔断器、自动取消无法成交订单 |
| **完整Factor分析平台（FactorLens-inspired）** | 降低因子研究门槛 | 开源现有FactorLens代码；扩展拥挤度指标、行业分层、IC排名；提供Web UI |
| **"Local-first"隐私架构** | 知识产权保护、监管合规 | 明确设计：源码/模型保留本地；云端提供数据+计算；无云端策略存储 |
| **策略版本化与实验追踪** | 可复现性、A/B测试 | 与现有mlflow/runs集成；添加策略修订追踪；对比baseline vs 实验输出 |

### 实施路线图优先级

**第一阶段（1-2个月）：** 采用回调框架；添加数据契约Schema验证；实施频率抽象层（日→分钟→Tick）。

**第二阶段（3-4个月）：** 升级风控引擎（持仓限额/滑点/成交量限制）；完成FactorLens Web UI；添加状态持久化模块。

**第三阶段（5-6个月）：** 设计C++引擎接口；集成Arrow Flight数据传输；实施模拟↔实盘路径；扩展市场覆盖（期权/期货）。

**第四阶段（7-12个月）：** 全面BigQuant架构平衡；分布式FAI-inspired计算；可视化策略编辑器；完整隐私架构。

XuanJiQuant项目已展现出强大的基础设计（5层架构、影子决策系统、F5模拟交易）。代码库中的BigQuant引用表明团队已理解目标架构。重点应放在升级执行引擎和统一数据/策略契约上，以实现BigQuant级别的能力。