# 原子研究发布与 F4 确定性候选工厂实施计划

**设计：** `docs/superpowers/specs/2026-08-19-atomic-research-publication-and-f4-candidate-factory-design.md`  
**执行方式：** 测试驱动、小步补丁、两阶段审阅；当前目录非 Git 仓库，因此无法创建 worktree 或提交，所有变更只发生在当前活动工作区。

## Task 1：建立研究发布状态机与原子指针

- 新建 `quant/research/publication.py`，实现 generation 身份、暂存目录、`status.json`、完成 pointer、哈希 manifest、失败状态和只读解析。
- 在 `tests/test_research_publication.py` 先写刷新保持旧 pointer、失败不发布、完整发布切换 pointer、路径逃逸/身份漂移失败测试。
- 运行该测试，确认红灯；实现后确认绿灯。

## Task 2：把日终因子/选股写入暂存 generation

- 为 `evaluate_factors.py`、`gpu_worker.py`、`generate_research_portfolio.py` 和 `research_training_scheduler.py` 增加显式 generation 输出路径，默认行为保持兼容。
- `factor_evaluation.json` 和 pickle/JSON 全部改为临时文件 + `os.replace`。
- `run_daily_research_pipeline.py` 在运行前标记 refreshing，在同版本三门禁后发布 pointer；异常写 failed 并保留旧 pointer。
- 扩展 `tests/test_daily_research_pipeline.py`、`tests/test_evaluate_factors_snapshot.py`、`tests/test_generate_research_portfolio.py`，验证 red-green。

## Task 3：读取端切换权威 generation 并修复只读鉴权

- `factor_runner.py`、`strategy_runner.py`、F5 运行时优先解析完成 pointer，缺失时兼容固定路径。
- API 返回 `research_refresh` 和 `is_current`，不把 refreshing 当 500。
- 把 `/api/strategy` 的 `research_selection` 加入 `server/router.mjs` 只读白名单。
- 更新 Node/页面契约，验证无令牌读成功且控制动作继续拒绝。

## Task 4：实现有界 F4 候选规格和 validation-only 选择

- 在 `quant/strategy` 新建候选工厂模块，定义六个不可变候选、规范哈希、稳定排序、factory 身份和不可变证据。
- 参数化 `fit_window_factors`、`simulate_f4_window`、`run_real_f4_pipeline`，支持候选政策与 `include_test=False`。
- 在 `tests/test_f4_candidate_factory.py` 先验证注册表有界、TopK≤10、总暴露≤0.95、逐窗口只用本窗口 validation、selection lock 先于 test、未选候选不读 test、排序稳定。

## Task 5：接入 F4 门禁、调度和页面状态

- `validate_strategy_portfolios.py` 先运行/复用候选 factory；每个外层窗口用 train/validation 原子锁定 winner 后，只允许该 winner 运行本窗口 test，最后聚合嵌套样本外结果并进入现有 F4 gate。
- 更新 identity/evidence/latest projection，全部失败显示 candidate factory exhausted，门槛和权限字段不得改变。
- `research_training_scheduler.py` 保持单任务幂等和失败关闭。
- 策略页面展示候选工厂证据、validation/test 分层和下一步状态。
- 扩展 F4、scheduler、Node/UI 契约测试。

## Task 6：文档、当前数据运行与全量验证

- 更新 `README.md`、`docs/XUANJI_HANDOFF.md`、系统工作流图。
- 运行相关 Python 测试，再运行全量 Python、`npm run test:contracts`、TypeScript、Vite 构建、Web/UI 验证。
- 只在数据/质量前置条件满足时运行一次实际候选工厂；如 Qlib/PIT 数据未到最新完整交易日，报告明确阻断，不伪造 F4 通过。
- 检查 API 返回、页面控制台、产物哈希与所有 `execution_authority=false`。
