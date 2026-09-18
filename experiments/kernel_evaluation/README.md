# 交易内核隔离评估

此目录是工程实验，不是第二套活动OMS。全部测试使用合成证券/行情、内存账户和独立结果目录，不导入项目quant、F5或生产配置。

## 运行环境

- NautilusTrader 1.231.0，Python 3.14，环境`.venv-kernel-eval`，依赖见requirements.lock。
- LEAN 2.5.18042，NuGet依赖，局部SDK `.\data\kernel-evaluation\dotnet\dotnet.exe`，版本10.0.401。
- 官方来源：PyPI nautilus_trader，NuGet QuantConnect.Lean/Common；接口阅读参考GitHub QuantConnect/Lean commit `8ee075a39918f2df6fe9e0a5944e366fb60d10dc`。源码参考提交与NuGet构建不宣称完全相同。
- 结果位于`data/kernel-evaluation/comparison.json`，LEAN每场景日志及结果独立保存。

从项目根目录执行：

```powershell
.\.venv-kernel-eval\Scripts\python.exe -m pytest experiments\kernel_evaluation\test_native_probes.py -q
.\data\kernel-evaluation\dotnet\dotnet.exe build experiments\kernel_evaluation\lean\KernelProbe.csproj --packages data\kernel-evaluation\nuget
.\data\kernel-evaluation\dotnet\dotnet.exe build experiments\kernel_evaluation\lean_engine\EngineProbe.csproj --packages data\kernel-evaluation\nuget
.\.venv-kernel-eval\Scripts\python.exe experiments\kernel_evaluation\run_comparison.py
```

首次部署需准备LEAN的官方market-hours/symbol-properties数据到上述结果目录的lean-data中，参考backtest.json；采样zip由收集脚本生成。路径固定当前项目，移动机器后必须改配置并复核。

## 文件边界

- scenarios.json：统一基准现金、币种、数量、费用、预期账户数值；非历史收益样本。
- nautilus_probe.py：真正BacktestEngine/策略/风控/模拟撮合/账户，报价驱动；另执行成交事件重复投递与订单事件重放。
- lean/：原生SecurityPortfolioManager.ProcessFills账户模块实验。直接投递成交位于OMS以下，不能用来评价LEAN整个OMS去重。
- lean_engine/：真正LEAN Launcher/Engine、QCAlgorithm及BacktestingBrokerage；本地分钟数据，CNY现金账户与自定义xshg证券；AlwaysOpen仅为合成场景，未验证A股交易日历。
- run_comparison.py：顺序运行并记录两个内核，不同时维护活动交易账户；结果记录代码和场景哈希。
- test_native_probes.py：数值/状态回归断言。4个strict xfail是尚未满足的A股准入要求，不能算通过。

## 解释限制

报价与分钟Bar粒度不同，限价触价语义和流动性模型不同。因此订单最终数量/资金可比较，部分成交时序与吞吐不能直接打分。精确同Tick回放、实际A股历史样本、完整进程重启、持久账户恢复、公司行动和负载测试仍需补齐。

普通full测试：100000 CNY，10元买1000股，每次成交固定5元费用，余额89995。这个5元是统一工程夹具，不能直接成为生产收费规则。roundtrip用于发现卖出可用量和资金交收差异，不把成功卖出判定为通过A股T+1。

LEAN本次NuGet链存在依赖漏洞告警；已在隔离工程覆盖System.Drawing.Common旧版本，但DotNetZip与完整Launcher链的其他传递依赖仍待处理。Nautilus出现Pandas弃用警告；未开展完整供应链审计。不能因某环境没有输出漏洞告警就认定安全。

评估环境可单独卸载，当前API端口、F5账本、计划任务与现有Qlib环境不属于本实验。SDK首次初始化报告生成ASP.NET开发证书，本轮没有执行证书信任操作，也没有修改系统PATH。
