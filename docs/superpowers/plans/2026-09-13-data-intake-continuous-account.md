# 数据准入与连续账户实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在当前会话执行；用户指定唯一工作区，不创建工作区外副本。

**Goal:** 交付真实数据准入诊断及一个隔离账户的持久跨批次延续。

**Architecture:** intake 只读 API；continuous 对 Journal 加追加契约；native 仍唯一负责撮合与账户。禁止把观测输出自动接成订单。

**Tech Stack:** Python 3.14、stdlib HTTP/SQLite、已有 NautilusTrader 1.231.0 隔离环境。

**Spec:** docs/superpowers/specs/2026-09-13-data-intake-continuous-account-design.md

## Global Constraints

- 仅 C:\Users\HYSHEN\XuanJiQuant；不触碰冻结备份、不切换 F5、不接券商。
- 10000 帧、100 个账户批次、单证券连续回放；不称作在线热恢复。
- 无 .git，无法创建 worktree 或提交；只改新模块、相关测试与交接文档。

## Task 1: 数据准入

文件：新增 trading_system/intake.py、tests/nautilus_baseline/test_intake.py。
接口：`assess_snapshot(snapshot, codes, checked_at) -> dict`；`capture_snapshot(codes, timeout=10) -> dict` 固定本地 API。

- [x] 编写缺股票、未来时间、缺盘口、陈旧状态和有效完整夹具测试。核心断言：`assert not report['execution_ready']`，并检查逐股票原因与实际覆盖。
- [x] 运行 `.venv-kernel-eval/Scripts/python.exe -m pytest tests/nautilus_baseline/test_intake.py -q`，确认因尚无接口失败。
- [x] 实现固定 API 请求、受限响应解码和纯输入准入分析；将原始响应与摘要放在返回报告中供审计。
- [x] 重跑测试；真实调用一次报告证据，不伪造周末执行。

## Task 2: 连续账户

文件：新增 trading_system/continuous.py、tests/nautilus_baseline/test_continuous.py；Journal 增加结果验证回调以在提交前验证成交前缀。
接口：`ContinuousAccount(path, account_id)` 上下文管理器；`append(batch_id, chunk, expected_revision, checkpoint_hook=None)`、`status()`、`recover()`。

- [x] 写真实内核三批次测试：买入 1000、同日卖出被拒、次日卖出；分别断言现金 89994.90、当日可卖 0、最终 99984.80 且无持仓。
- [x] 写重复/冲突、配置变化、历史日期/目标改写、错误账户、哈希链、强退待完成尾部测试。
- [x] 运行新测试，确认缺少 ContinuousAccount 失败。
- [x] 实现冻结配置、不可变前缀、上一结果哈希绑定和 expected_revision；仅调用 native 生成账户结果，不写第二套账户数学。
- [x] 重跑测试及全部 tests/nautilus_baseline；不删除原测试。

## Task 3: CLI 与交接

文件：修改 trading_system/cli.py、tests/nautilus_baseline/test_cli.py、trading_system/README.md、README.md、docs/XUANJI_HANDOFF.md。

- [x] 写 CLI 真实子进程 account-append/status/recover 测试；默认日志不得用于连续账户。
- [x] 运行失败测试，增加命令和 JSON 错误回执。
- [x] 原有 CLI 和全部测试通过后，用独立日志测试三批次并恢复；CLI 另用两日示例实跑，data-probe 保存报告。
- [x] 更新文档：源时间/完整性、唯一账户投影、重复累计结果不能相加、当前阻断和下一阶段准入。

## 补充修复与审查

- [x] 源日期错误：读取新浪原始 30/31 字段定位日期丢失；6 个失败测试后修复 scripts/market_data.py，精确重载数据读取子进程，真实 API 再证实日期正确。
- [x] 独立审查：补 Journal 双向模式隔离、连续模式必需 callable 校验器、禁止通用恢复；旧入口实跑拒绝。
- [x] 拒绝 HTTP 重定向；真实本地 HTTP 测试覆盖重定向、超时、畸形 JSON。

本计划交付边界为数据准入诊断与有界连续回放，不等于真实盘中执行已可用。验收证据：docs/superpowers/specs/2026-09-13-continuous-account-verification.md。
