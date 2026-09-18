# LEAN 与 NautilusTrader 内核实测报告

日期：2026-09-11。范围：五阶段路线中的A阶段内核初筛。数据：合成工程夹具，不是历史选股或收益回测。

## 结论

选择NautilusTrader作为后续确定性模拟系统的开发主线，LEAN保留为评估对照，不建设第二套活动OMS。该决定不是批准切换当前F5，也不是A股适配已经完成。

选择依据：本机原生Python/Rust发行包可运行，真实BacktestEngine已覆盖报价、订单、风控、撮合、资金冻结、成交去重和事件重放；这些边界适合后续把AI视为一个产生组合提案的工作进程。LEAN完整Engine同样已运行并正确处理普通成交、资金不足和交收；其组合框架值得借鉴，但本次隔离环境涉及.NET/Python双运行时、较多传递依赖及不同Bar撮合语义，当前项目的AI/Python研究集成成本更高。

这不是通用性能排名。没有用缺测项目判定另一框架失败；当前也没有证明任一候选能未经A股适配直接接管账户。A阶段剩余的同粒度回放、A股规则适配和完整重启恢复是后续准入条件。

## 版本和隔离

| 项目 | 本轮实际使用 |
|---|---|
| NautilusTrader | 1.231.0，Windows amd64，Python 3.14，依赖锁在experiments/kernel_evaluation/requirements.lock |
| LEAN | NuGet QuantConnect.Lean/Common 2.5.18042，真实Launcher/Engine与QCAlgorithm |
| .NET | 10.0.401，安装于data/kernel-evaluation/dotnet，未改系统PATH |
| Python | .venv-kernel-eval；现有系统Python和.venv-qlib的依赖未修改 |
| 输入 | 600000，CNY，初始100000，基准价10，每次成交固定5元；XSHG为实验证券市场 |
| 输出 | data/kernel-evaluation/comparison.json，逐场景LEAN日志与结果目录 |

固定费用是测试参数，不代表生产手续费或法定收费政策。两边没有接券商或使用活动F5数据。LEAN采用AlwaysOpen合成市场，尚未验证节假日与A股分时交易日历。

## 实测矩阵

| 场景 | Nautilus本轮配置 | LEAN本轮配置 | 判断 |
|---|---|---|---|
| 买1000股 | 余额89995，持仓1000 | 余额89995，持仓1000 | 两边真实内核完成成交和费用核算 |
| 400/600分批流动性，限价10 | 两笔合计1000股，余额89990 | 原生Bar限价触价场景未成交，订单Submitted | 撮合假设不同，不据此判LEAN损坏 |
| 部分成交后撤单 | 400成交，剩600取消，余额95995 | 本场景0成交后取消 | 需要相同Tick输入及明确部分成交模型后再比时序 |
| 现金不足买20000股 | DENIED，余额100000 | Invalid，余额100000 | 两边都没有透支成交 |
| 同日买入再卖出 | 全部卖出，余额99990 | 全部卖出，可用现金89990，未交收资金10000，权益99990 | 两边当前配置均未实现A股买入股票T+1；不能混淆资金交收 |
| 被动限价挂单/取消 | 观察到9000冻结，取消后为0 | 订单已取消，无成交；冻结额度未直接验证 | 不将LEAN未测项记为通过/失败 |
| 停牌状态注入 | InstrumentStatus(HALT)后本配置仍成交 | Initialize设置IsTradable=false后本配置仍成交 | 必须补市场状态到提交时准入的适配；不是通用内核无法支持停牌的结论 |
| 超过夹具预设日涨幅价格 | 当前未接日价格带，12元成交 | 当前未接日价格带，12元成交 | 两边都需证券日价格带适配 |
| 买101股 | 原生接受101 | 原生调整为100 | 适配器必须拒绝或明确解释调整，不能静默改变AI目标 |
| 主动限价10.01 | 当前L1模型在剩余深度未给出时完成1000股，余额89984 | Bar模型1000股成交，余额89995 | 必须明确L1深度外推和保守容量假设 |

Nautilus另验证：把同一OrderFilled重新发送到ExecutionEngine后，现金、订单已成交量和持仓量不变；真实订单初始化和全部事件重新应用后重建状态一致。用新BacktestEngine重复相同输入，观察结果相同。

LEAN另对同一份scenarios.json运行原生SecurityPortfolioManager.ProcessFills，四种分批/买卖数量的账户数学均通过断言。直接在这个会计函数重复投递会重复入账，这只能说明该函数依赖上游去重，不能据此推断LEAN完整OMS没有去重。LEAN完整OMS重复投递测试尚未完成。

## 运行与质量证据

- Nautilus自动断言：7 passed，4 strict xfailed。4个预期失败分别标记T+1、停牌、日价格带、买入整手的适配缺口；它们不是通过项。Pandas弃用警告保留。
- 加上跨内核结果断言后，隔离评估测试共12 passed / 4 xfailed；其中跨内核检查包含未交收资金，避免误判LEAN现金核算。该数量不是全项目回归数量。
- LEAN完整引擎：10个场景都产生真实引擎结果；退出码0表示回测运行结束，不表示A股业务符合。
- LEAN账户模块：4个共同夹具的现金/数量断言通过。
- LEAN每个独立进程场景约5至6秒，包含启动；Nautilus小夹具测试套件约3秒。环境/粒度不同，不作吞吐或P95比较。
- NuGet恢复发现System.Drawing.Common 4.7.0严重告警，隔离工程已固定覆盖10.0.12；DotNetZip及完整Launcher其他传递依赖仍有告警。没有关闭漏洞扫描或把告警写成已解决。Nautilus本轮未作完整供应链审计。
- LEAN运行可出现组件扫描的System.Formats.Nrbf依赖警告、缺少基准数据等诊断，需在正式精简运行制品中修复，不宣称环境完全无错误。

## 后续实现门槛

下一阶段仅围绕Nautilus开发A股适配和确定性基线：

1. 证券与日历：每个证券的交易日、T+1、交易单位、涨跌幅范围、停复牌、公司行动有显式来源和版本。
2. 事前门禁：在内核接收订单前复核账户版本、资金预留、可卖数量、价格带、状态；目标调整返回明确原因。
3. 模拟模型：Level-1不能推断完整队列，采用有界流动性模型；部分成交/撤单和余额有可重复的独立断言。
4. 单一会计与恢复：持久化订单事件与账户事实，杀进程后从事件/检查点恢复并对账，通过后再释放新决策；不将内存重放称为重启恢复。
5. 同一输入基线：逐事件回放、在线模拟、固定策略使用同一核心；引擎初筛夹具扩展为真实A股历史样本和多交易日测试。
6. 完成这些门槛后接AI影子，然后才允许切换唯一活动owner。

尚未完成：完整进程崩溃恢复、真实数据回测与在线模拟等价、公司行动、交易日历、AI影子对照、活动账户迁移、备份恢复演练、告警投递、20交易日运营观察。本报告不将五阶段路线写成已完成。

## 复现与源码

入口和环境说明见experiments/kernel_evaluation/README.md。原始机器输出见data/kernel-evaluation/comparison.json；控制记录、实验产物和当前运行账本分离，评估代码无活动执行权限。

参考官方来源：

- https://pypi.org/project/nautilus_trader/1.231.0/
- https://nautilustrader.io/docs/latest/concepts/architecture/
- https://nautilustrader.io/docs/latest/concepts/execution/
- https://www.nuget.org/packages/QuantConnect.Lean/2.5.18042
- https://www.nuget.org/packages/QuantConnect.Common/2.5.18042
- https://github.com/QuantConnect/Lean/tree/8ee075a39918f2df6fe9e0a5944e366fb60d10dc
