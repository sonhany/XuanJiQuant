# 因子输入治理与研究候选交付设计

## 1. 目标

把当前“直接遍历可变 `kline:*:d`”的因子链收敛为：版本化数据快照、明确当前可交易股票池、可复现因子产物、确定性研究调度和仅供研究的候选排名。该改造不恢复 Agent，不开启自动交易，不赋予因子结果订单权限。

## 2. 方案选择

采用严格快照方案：因子全市场评估和当前截面排名必须绑定 `data:snapshot:a_share_daily:latest_passed`。数据层以全市场覆盖率为质量门禁；允许少量证券抓取失败，但仅在覆盖率达到配置阈值时发布 `passed`，并把抓取失败数量记录为警告。拒绝继续使用无版本的可变缓存作为正式因子输入。

没有合格快照、快照过期、股票池哈希不一致、有效证券覆盖不足时，因子全市场任务失败关闭；单股诊断计算可以读取指定证券，但必须标明 `diagnostic_only=true`，不得冒充全市场选股。

## 3. 数据契约

新增 `quant/factor/input_contract.py`，提供：

- `FactorInputSnapshot`：包含 `snapshot_id`、`data_version`、`as_of`、`universe_version`、活跃股票池、当前可排名股票池、排除原因和覆盖率。
- `FactorInputContractError`：稳定错误码，包括 `factor_snapshot_missing`、`factor_snapshot_stale`、`factor_universe_mismatch`、`factor_coverage_below_gate`。
- `load_factor_input_snapshot(cache, expected_date=None)`：只读取 `latest_passed`，验证日期、股票池哈希、日K日期、最小历史长度和当前可交易名称。

当前排名排除名称包含 `ST`、`*ST` 或 `退` 的证券、无足够历史、无快照日数据和零成交量证券。历史K线和退市证券仍保留在数据库，不删除审计事实。

## 4. 因子计算与产物

固定因子仍为 19 个技术、28 个量价和 11 个基本面因子。动态 DSL 默认关闭，只能读取 `research:factor:approved`，本设计不新增动态因子。

`evaluate_factors.py` 必须使用输入契约给出的股票代码，不再遍历全部 `kline:*:d`。生成的 `factor_snapshot.pkl`、`factor_snapshot_latest.json` 和 `factor_evaluation.json` 必须携带：

- `snapshot_id`
- `data_version`
- `universe_version`
- `universe_policy=current_tradeable_v1`
- `as_of`
- `eligible_count` 与排除原因统计
- `promotion_state=research_only`
- `execution_authority=false`

## 5. 页面与策略边界

`factor_stocks` 只对契约允许的代码排名；若截面版本与最新合格快照不一致，返回失败，不提供旧排名。单股因子接口必须传入 `code`，保证基本面因子能够读取对应财务数据。

市场榜单必须展示数据截止日、快照编号、股票池口径、是否中性化和研究态标签。策略扫描只能读取同一 `data_version` 的因子评估和因子快照；不匹配时失败关闭。

## 6. 调度

交易日 16:20 的因子任务以前一已完成交易日的 `latest_passed` 为输入。调度幂等键绑定 `market_date + data_version + factor_version`，成功结果只能是 `research_only`。策略周任务必须依赖相同数据版本的成功因子任务。

六年 Qlib 清单仍是独立研究门禁；在其 `incomplete` 时不得声明六年 PIT 研究完成，但不阻断日频固定因子对合格 SQLite 日K快照的研究计算。

## 7. 验收

1. 缺失、过期或股票池哈希不一致的快照会阻断全市场因子评估与排名。
2. 当前排名不再出现 ST、退市、缺少快照日K或零成交量证券。
3. 三类因子产物都携带同一数据版本和 `research_only` 权限字段。
4. 单股因子接口可以计算基本面字段。
5. 研究调度账本记录实际运行或稳定阻断原因，不再把进程存活当作研究成功。
6. 自动交易继续关闭，历史数据库和日志不改写。

