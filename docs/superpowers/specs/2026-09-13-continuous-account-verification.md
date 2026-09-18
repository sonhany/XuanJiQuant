# 2026-09-13 数据接入与单账户连续性验证

## 结论

已交付真实 API 数据准入报告、单账户跨批次持久回放及 CLI；已修复并在运行 API 验证新浪日期解析缺陷。**真实数据可执行准入尚未通过，AI 影子未接入，持续盘中服务尚未建设。** 本轮不切换 F5，不连接券商，不新增活动 OMS。

## 实际数据与修复证据

- Web 8888 返回 200（621ms）；API 数据 stats 返回 200（753ms），报告股票池 5203。这是接口报告值，不是本轮逐只验证全市场。
- 11:46:16（北京时间）对 600000、000001、600519 实取，3/3 返回 sina 报价，执行准入 0/3；捕获文件 `data/nautilus-baseline/data-intake-20260913.json`。
- 源头读取新浪 600000 原始响应，共 34 字段，字段 30 为 `2026-09-11`、字段 31 为 `15:34:59`。`scripts/market_data.py` 原解析仅保留时分秒，随后 `_ensure_quote_timestamp` 用今天拼日期，导致 API 输出 `20260913153459`。
- 先用 6 个测试复现，再让股票与指数解析保留供应商完整日期；无效或缺失日期不能给新浪报价补“今天”。未伪造新鲜度或缺失盘口。
- 精确核验并重载 API PID 6416 下的 data_runner 子进程 8732、23956、16576；没有重启 API 主进程或 F5 执行器。
- 11:51:57 再实取 3 只股票，API 已返回 `20260911…`，不再有 quote_future；2629ms。证据文件 `data/nautilus-baseline/data-intake-after-date-fix-20260913.json`。正常识别为历史行情，上游日期不匹配标记保留。

剩余数据阻断：周末非连续竞价、历史源时间、缺少显式交易所身份/事件时间语义/股数单位、买卖盘、日状态/价格带和日历。报告中的 instrument_mismatch 包括交易所字段缺失，不能解读为三个股票代码本身错误。来源已有不等于执行契约完整；不以最新价替代买卖一档。

## 单账户实跑

最终日志 `data/nautilus-baseline/continuous-final-20260913.sqlite3`，账户 `development-only`；输入 examples/continuous_day1.json 和 continuous_day2.json，均为合成场景。每条命令均为独立 Python 进程。此前 continuous-acceptance 日志保留为审查前证据，绑定旧适配代码哈希，不作为最终入口使用。

| 步骤 | 现金 | 持仓 | 结果 |
|---|---:|---|---|
| revision 1 | 89,994.90 | 600000：1000 股 | 买入 1 笔 |
| revision 2 | 99,984.80 | 空仓 | 次日卖出，本批新增 1 笔 |
| 重复第二批 | 99,984.80 | 空仓 | 不新增 revision、不重复成交 |
| 新进程恢复 | 99,984.80 | 空仓 | 累计 2 笔成交，完整输出一致 |

现金、持仓、结算批次、订单终态、预留释放、非负余额六项对账均通过。最终两版完整恢复单次墙钟 2.831 秒（含解释器启动），不是吞吐或实盘 SLA。测试还包含第三批次场景：同日卖出被拒、次日才可卖。旧 CLI recover 指向最终连续日志时实际返回退出码 1、continuous_journal_requires_account_api，未执行通用恢复。

## 验证

运行命令：

```powershell
.venv-kernel-eval\Scripts\python.exe -m pytest tests/nautilus_baseline tests/test_sina_event_date.py tests/test_realtime_snapshot_contract.py tests/test_market_money_flow.py tests/test_f5_intraday.py tests/test_f5_live_marks.py -q --tb=short --junitxml=data/nautilus-baseline/verification-continuous-20260913.xml
npm run test:contracts
```

最终结果：**124 passed**，124 条上游 Pandas Timestamp.utcnow 弃用警告，41.47 秒。Node 最终完整重跑 **58/58 文件通过**；首次 57/58，其中 cockpit_latency_contract_tests 的 Python 账户读取子进程超过 10 秒，单项复测通过，未修改超时阈值。记录为一次未消除根因的时延波动，不宣称性能问题已彻底解决。

新测试覆盖：三批次账户延续、重启、T+1、重复/冲突、版本冲突、配置与历史目标不可改、日志账户绑定、哈希链篡改、输入/输出提交后强退、历史成交改变时保持 pending；数据完整性、未来/陈旧时间、接收时序、市场阶段、覆盖率、真实本地 HTTP 请求及源日期保留。没有做 UI 交互或长期连续运行验收，不把 Node 静态契约代替它们。

## 模块关系与后续准入

独立只读代码审查提出两项重要问题，均先补失败测试后修复：旧试验入口可能误入连续日志；HTTP 默认跟随重定向可能离开固定本地 API。Journal 现在在打开与写入时检查 trial/continuous 模式，连续模式的通用 recover 被禁用，必须使用专用前缀核验恢复；提交校验器必须 callable，False/0 不能绕过。数据请求拒绝所有 HTTP 重定向，另用真实本地 HTTP 服务验证超时与畸形 JSON。审查后重跑相关回归，不修改门禁阈值。

- intake → 既有 `/api/data`，只观察和报告；不操作交易入口。
- continuous → Journal 持久提交 → native/rules → 原生账户与对账；历史成交前缀提交前核验。
- CLI 的 data-probe 不打开账户日志；account-* 强制显式路径，不复用独立试验默认日志。
- 单账户输入和结果版本是累计投影，不是两套账本；本目录的研发日志也不是活动 F5 账本。

下一阶段先为数据 API 补齐可审计的执行字段和主数据，并验证真实盘中输入；再完成长期单账户会话/增量恢复，之后接 AI 只读影子建议与基线对照。AI 没有执行授权，不能为了通过验收改变硬风控或伪造主数据。旧 Agent 不复活。

## 2026-09-14 延续验证

已补齐真实可得的执行前置字段：新浪 A 股原始字段中的买一/卖一价格与数量进入 `scripts/market_data.py`，`hot_snapshot` 统一发布 `venue`、`timestamp_kind=exchange`、`size_unit=shares`、当天 `calendar` 和带来源说明的 `market` 状态。`hot_quotes.stale_after_ms` 调整为 5000ms，与本模块 `max_quote_age_ms` 保持一致。长驻 data_runner 已精确重载。

13:30:37 实测 `data-probe --codes 600000,000001` 返回 execution_ready=true，覆盖 2/2；同轮包含 600519 时，600519 因源时间 7.9 秒未更新被拒，整批继续关闭。新增 `build_observed_realtime_request()` 只接受整批与单票都准入的报告，生成 `data_kind=observed_realtime` 单证券 paper 请求，并将价格规范到 0.01 精度。此前三位小数触发过 Nautilus `price_precision=2` 错误，已用失败测试复现后修复。

隔离实跑日志 `data/nautilus-baseline/continuous-observed-final-20260914.sqlite3`，账户 `observed-realtime-smoke`，revision 1，批次 `observed-20260914133451`。结果：600000 买入 100 股，成交价 9.40，费用 5.01，现金 99054.99，持仓 100 股，当日可卖 0，权益 99993.99；cash、positions、lots、terminal、reservations_released、nonnegative 六项对账通过。`account-recover` 独立进程恢复同一结果，`live_execution_authority=false`。仍未启用 AI 影子，未切换活动 F5，未建设长期驻留增量服务。
