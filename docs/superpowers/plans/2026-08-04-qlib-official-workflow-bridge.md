# XuanJiQuant Qlib Official Workflow Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 XuanJiQuant Qlib 模块升级为可复现、可审计、经过 Qlib 官方回测与 A 股规则回测双重验证、最多晋升到影子信号的成熟日频研究主链。

**Architecture:** 保留现有采集器、`qlib_runner.py` 白名单控制面、`qlib_meta.db`、中文研究面板和交易安全链，在 `quant/qlib` 内增加路径解析、版本化质量门禁、官方 Workflow/Recorder、产物导入、A 股回测桥和双门禁。Recorder 是实验事实来源，`qlib_meta.db` 是控制索引；研究产物不能生成订单。

**Tech Stack:** Python 3.11、pyqlib 0.9.7、MLflow Recorder、LightGBM 4.6.0、XGBoost 2.1.4、pandas 2.2.3、SQLite WAL、Node.js ESM、React 19、TypeScript 5.8、Vite 8、pytest、Node 契约测试。

---

## 执行约束

- 只在 `C:\Users\HYSHEN\XuanJiQuant` 操作；冻结备份 `C:\Users\HYSHEN\AlphaCouncil2-AI` 不运行、不测试、不写入。
- 活动 Qlib 根默认为 `C:\Users\HYSHEN\XuanJiQuant\data\qlib`。
- 不改写历史日志和数据库中的旧名称、旧路径；运行时分离 `recorded_path` 与 `resolved_path`。
- 不初始化新的 Git 仓库。当前目录没有 `.git`；每项提交步骤先运行 `git status`，若仍提示不是仓库，只登记检查点，不执行 `git init`。
- 普通回归使用小型确定性数据。六年全市场采集、完整模型矩阵和连续计划任务属于受控离线验收。
- 实施前阅读 `docs/superpowers/specs/2026-08-04-qlib-official-workflow-bridge-design.md`。

## 文件结构

新建的核心文件及职责：

| 文件 | 职责 |
|---|---|
| `quant/qlib/failures.py` | 数据源失败分类和重试判定 |
| `quant/qlib/workflow_config.py` | Alpha、模型和官方回测固定配置 |
| `quant/qlib/workflow_bridge.py` | 运行 Qlib Workflow、Recorder 和三类 Record |
| `quant/qlib/artifact_importer.py` | 校验 Recorder 产物并幂等登记 |
| `quant/qlib/ashare_backtest.py` | 把版本化信号送入现有 A 股回测器 |
| `quant/qlib/promotion_gate.py` | 统一数据、信号、双回测和差异门禁 |
| `quant/qlib/capabilities.py` | 计算真实能力状态 |
| `quant/qlib/shadow_signal.py` | 写入不含订单的影子信号 |
| `lib/qlib-types.ts` | Qlib API 前端类型 |
| `scripts/qlib_acceptance.py` | 只读检查第一阶段验收条件 |

既有边界文件保持职责：

- `scripts/qlib_runner.py`：固定 action、请求字段和授权边界。
- `scripts/qlib_job_worker.py`：离线 job 阶段编排。
- `scripts/qlib_train.py`：训练入口，改为调用 Workflow 桥，不再承载模型实现。
- `quant/qlib/registry.py`：SQLite 控制索引。
- `quant/backtest/engine.py`：A 股成交真实性约束。
- `components/QlibResearchPanel.tsx` 与 `components/qlib/*.tsx`：七页签中文研究控制面。

## Task 1: 活动数据根与历史路径解析

**Files:**
- Create: `tests/test_qlib_paths.py`
- Modify: `quant/qlib/paths.py:1-21`

- [ ] **Step 1: 写入失败测试**

~~~python
from pathlib import Path
import pytest

from quant.qlib.paths import PathResolution, data_root, resolve_recorded_path


def test_default_root_is_active_project(monkeypatch):
    monkeypatch.delenv("QLIB_DATA_ROOT", raising=False)
    assert data_root() == Path(r"C:\Users\HYSHEN\XuanJiQuant\data\qlib")


@pytest.mark.parametrize("value", [
    r"C:\XuanJiQuant-QlibData",
    r"C:\AlphaCouncil-QlibData",
    r"C:\Users\HYSHEN\AlphaCouncil2-AI\data\qlib",
])
def test_rejects_obsolete_and_frozen_active_roots(monkeypatch, value):
    monkeypatch.setenv("QLIB_DATA_ROOT", value)
    with pytest.raises(ValueError, match="活动 Qlib 数据根"):
        data_root()


def test_legacy_record_is_mapped_without_rewrite(monkeypatch, tmp_path):
    active = tmp_path / "qlib"
    target = active / "models" / "m1" / "model.pkl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model")
    monkeypatch.setenv("QLIB_DATA_ROOT", str(active))
    result = resolve_recorded_path(
        r"C:\AlphaCouncil-QlibData\models\m1\model.pkl"
    )
    assert result.recorded_path.startswith(r"C:\AlphaCouncil-QlibData")
    assert result.resolved_path == str(target.resolve())
    assert result.path_state == "mapped_legacy"


def test_frozen_record_is_visible_but_not_resolved(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path / "qlib"))
    result = resolve_recorded_path(
        r"C:\Users\HYSHEN\AlphaCouncil2-AI\data\qlib\models\old.pkl"
    )
    assert result.path_state == "rejected_frozen"
    assert result.resolved_path == ""
~~~

- [ ] **Step 2: 运行并确认失败**

Run:

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_paths.py -q
~~~

Expected: collection fails because `PathResolution` and `resolve_recorded_path` do not exist.

- [ ] **Step 3: 实现路径安全边界**

在 `quant/qlib/paths.py` 保留 `resolve_data_path`，加入：

~~~python
from dataclasses import dataclass

FROZEN_ROOT = Path(r"C:\Users\HYSHEN\AlphaCouncil2-AI").resolve()
LEGACY_ROOTS = (
    Path(r"C:\XuanJiQuant-QlibData").resolve(),
    Path(r"C:\AlphaCouncil-QlibData").resolve(),
)


@dataclass(frozen=True)
class PathResolution:
    recorded_path: str
    resolved_path: str
    path_state: str
    resolution_reason: str


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _validated_active_root(candidate: Path) -> Path:
    resolved = candidate.resolve()
    if _inside(resolved, FROZEN_ROOT) or any(
        _inside(resolved, root) for root in LEGACY_ROOTS
    ):
        raise ValueError(f"活动 Qlib 数据根禁止使用旧路径或冻结备份: {resolved}")
    return resolved


def data_root() -> Path:
    configured = os.environ.get("QLIB_DATA_ROOT", "").strip()
    return _validated_active_root(
        Path(configured) if configured else DEFAULT_DATA_ROOT
    )
~~~

`resolve_recorded_path` 必须返回 `active`、`mapped_legacy`、`missing_historical`、`rejected_frozen` 四种状态；旧外部根按相对后缀映射到当前 `data_root()`，目标不存在时不伪造 `resolved_path`。

- [ ] **Step 4: 运行路径与现有 registry 回归**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_paths.py tests\test_qlib_registry.py tests\test_qlib_runner_actions.py -q
~~~

Expected: all selected tests pass，且没有访问冻结备份。

- [ ] **Step 5: Commit/Checkpoint**

~~~powershell
git status --short
git add quant\qlib\paths.py tests\test_qlib_paths.py
git commit -m "fix: enforce active qlib data root"
~~~

若不是 Git 仓库，跳过 add/commit，只登记 Task 1 检查点。

## Task 2: Workflow、质量和回测控制索引

**Files:**
- Modify: `quant/qlib/registry.py:47-114,202-330,431-464`
- Modify: `tests/test_qlib_registry.py`

- [ ] **Step 1: 写入缺表和幂等测试**

~~~python
def test_workflow_control_tables_exist(tmp_path):
    store = Registry(tmp_path / "qlib_meta.db")
    assert {"quality_reports", "workflow_runs", "backtest_results"} <= set(
        store.table_names()
    )


def test_workflow_upsert_is_idempotent(tmp_path):
    store = Registry(tmp_path / "qlib_meta.db")
    row = {
        "id": "wf_1",
        "experiment_id": "local_1",
        "qlib_experiment_id": "7",
        "recorder_id": "rec_1",
        "dataset_version": "daily-pit-v1",
        "quality_report_id": "quality_1",
        "handler": "Alpha158",
        "model_type": "LightGBM",
        "seed": 42,
        "config_hash": "a" * 64,
        "status": "succeeded",
        "recorded_path": r"C:\AlphaCouncil-QlibData\mlruns\7\rec_1",
        "artifacts": {"pred.pkl": "b" * 64},
        "metrics": {"rank_ic": 0.03},
        "gate": {"passed": False},
    }
    store.upsert_workflow_run(row)
    store.upsert_workflow_run({**row, "metrics": {"rank_ic": 0.04}})
    items = store.list_workflow_runs()
    assert len(items) == 1
    assert items[0]["metrics"]["rank_ic"] == 0.04
~~~

- [ ] **Step 2: 运行并确认缺表/缺方法**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_registry.py -q
~~~

Expected: new tests fail.

- [ ] **Step 3: 增加三张表**

在 `Registry._init_schema` 同一事务追加：

~~~sql
CREATE TABLE IF NOT EXISTS quality_reports (
    id TEXT PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    gate_version TEXT NOT NULL,
    passed INTEGER NOT NULL,
    report_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(dataset_id, dataset_version, gate_version)
);
CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL UNIQUE,
    qlib_experiment_id TEXT NOT NULL,
    recorder_id TEXT NOT NULL UNIQUE,
    dataset_version TEXT NOT NULL,
    quality_report_id TEXT NOT NULL,
    handler TEXT NOT NULL,
    model_type TEXT NOT NULL,
    seed INTEGER NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    recorded_path TEXT NOT NULL DEFAULT '',
    artifacts_json TEXT NOT NULL DEFAULT '{}',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    gate_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS backtest_results (
    id TEXT PRIMARY KEY,
    workflow_run_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    signal_hash TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    config_json TEXT NOT NULL DEFAULT '{}',
    artifact_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(workflow_run_id, engine)
);
~~~

- [ ] **Step 4: 实现 CRUD 和路径视图**

新增 `upsert_quality_report`、`upsert_workflow_run`、`list_workflow_runs`、`get_workflow_run`、`upsert_backtest_result`、`list_backtest_results`。`list_workflow_runs` 通过 Task 1 的解析器补充：

~~~python
resolution = resolve_recorded_path(item.get("recorded_path"))
item.update({
    "resolved_path": resolution.resolved_path,
    "path_state": resolution.path_state,
    "resolution_reason": resolution.resolution_reason,
})
~~~

同一 `recorder_id` 和同一 `(workflow_run_id, engine)` 必须更新原记录而不是插入重复行。JSON 均使用 `ensure_ascii=False`。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_registry.py tests\test_qlib_research_integration.py -q
git status --short
git add quant\qlib\registry.py tests\test_qlib_registry.py
git commit -m "feat: add qlib workflow control index"
~~~

若不是 Git 仓库，只登记 Task 2 检查点。

## Task 3: 失败分类、上海字段兼容和可恢复采集

**Files:**
- Create: `quant/qlib/failures.py`
- Create: `tests/test_qlib_failures.py`
- Modify: `quant/qlib/sources.py:34-109,170-300`
- Modify: `quant/qlib/collector.py:149-267`
- Modify: `tests/test_qlib_sources.py`
- Modify: `tests/test_qlib_collector.py`

- [ ] **Step 1: 写入失败分类测试**

~~~python
from quant.qlib.failures import classify_failure


def test_missing_columns_is_not_retryable():
    result = classify_failure(ValueError("missing columns: 成交量, 成交额"))
    assert (result.reason_code, result.retryable) == ("missing_columns", False)


def test_timeout_is_retryable():
    result = classify_failure(TimeoutError("source timed out"))
    assert (result.reason_code, result.retryable) == ("source_network", True)


def test_price_jump_is_not_retryable():
    result = classify_failure(RuntimeError("price jump exceeds tolerance"))
    assert (result.reason_code, result.retryable) == ("price_jump", False)
~~~

`tests/test_qlib_sources.py` 增加上海 DataFrame 字段别名测试；缺少成交量时必须显式报出 `volume`，不能静默写 0。

- [ ] **Step 2: 运行并确认失败**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_failures.py tests\test_qlib_sources.py tests\test_qlib_collector.py -q
~~~

Expected: missing module and unstructured manifest assertions fail.

- [ ] **Step 3: 实现分类器**

~~~python
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FailureDetail:
    reason_code: str
    retryable: bool
    message: str
    exception_type: str

    def as_dict(self) -> dict:
        return asdict(self)


def classify_failure(exc: BaseException) -> FailureDetail:
    message = str(exc)[:500]
    lowered = message.lower()
    if "missing column" in lowered or "缺少字段" in message:
        code, retryable = "missing_columns", False
    elif isinstance(exc, (TimeoutError, ConnectionError)) or any(
        token in lowered for token in ("timeout", "timed out", "connection")
    ):
        code, retryable = "source_network", True
    elif "price jump" in lowered:
        code, retryable = "price_jump", False
    elif "calendar" in lowered or "trade date" in lowered:
        code, retryable = "calendar_mismatch", False
    elif "empty" in lowered or "no rows" in lowered:
        code, retryable = "empty_window", False
    elif isinstance(exc, OSError):
        code, retryable = "write_failure", True
    else:
        code, retryable = "unknown", False
    return FailureDetail(code, retryable, message, type(exc).__name__)
~~~

- [ ] **Step 4: 标准化字段和结构化 manifest**

`sources.py` 新增固定别名：

~~~python
AKSHARE_DAILY_FIELDS = {
    "date": ("日期", "date"),
    "open": ("开盘", "open"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "close": ("收盘", "close"),
    "volume": ("成交量", "volume"),
    "amount": ("成交额", "amount"),
}
~~~

在 DataFrame 转 records 前检查每个标准字段至少有一个别名。`collector.py` 对 `source_network` 最多重试 3 次，退避 1、2 秒；其他分类不盲目重试。`failed_symbols[symbol]` 固定写：

~~~python
{
    "reason_code": detail.reason_code,
    "retryable": detail.retryable,
    "attempts": attempts,
    "message": detail.message,
    "exception_type": detail.exception_type,
    "last_failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
}
~~~

保持每 25 只原子检查点，增加每 250 只的批次统计。只有 manifest 的 dataset_version 与当前起止日期一致，且 raw、adjusted、point-in-time 三个产物都存在并标记成功时才跳过标的。end_date 前移时，从该标的已存最新日期前 15 个自然日开始补采，把新旧记录按 datetime 合并去重后原子替换；source/adjustment schema version 改变时才执行该标的全窗口重建。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_failures.py tests\test_qlib_sources.py tests\test_qlib_collector.py tests\test_qlib_normalizer.py tests\test_qlib_corporate_actions.py tests\test_qlib_point_in_time.py -q
git status --short
git add quant\qlib\failures.py quant\qlib\sources.py quant\qlib\collector.py tests\test_qlib_failures.py tests\test_qlib_sources.py tests\test_qlib_collector.py
git commit -m "fix: make qlib collection resumable and diagnosable"
~~~

若不是 Git 仓库，只登记 Task 3 检查点。

## Task 4: 版本化六年数据质量门禁

**Files:**
- Modify: `quant/qlib/quality_gate.py:1-55`
- Modify: `scripts/qlib_job_worker.py:254-384`
- Modify: `tests/test_qlib_quality_gate.py`
- Modify: `tests/test_qlib_job_worker.py`

- [ ] **Step 1: 写入门禁身份测试**

~~~python
from quant.qlib.quality_gate import GATE_VERSION, check_dataset_quality


def test_quality_report_has_stable_identity():
    result = check_dataset_quality(
        requested=100,
        completed=99,
        recent_coverage=1.0,
        trading_days=1300,
        latest_date_matches=True,
        duplicate_rows=0,
        invalid_ohlc=0,
        non_positive_factors=0,
        unknown_st_samples=0,
        invalid_lifecycle_samples=0,
        dataset_version="daily-pit-v1",
    )
    assert result["passed"] is True
    assert result["gate_version"] == GATE_VERSION == "qlib_phase1_gate_v1"
    assert result["report_id"].startswith("quality_")
~~~

- [ ] **Step 2: 运行并确认缺少 gate version**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_quality_gate.py tests\test_qlib_job_worker.py -q
~~~

Expected: new assertions fail.

- [ ] **Step 3: 固定门槛和 report ID**

~~~python
GATE_VERSION = "qlib_phase1_gate_v1"
THRESHOLDS = {
    "coverage": 0.98,
    "recent_coverage": 0.99,
    "trading_days": 1200,
    "duplicate_rows": 0,
    "invalid_ohlc": 0,
    "non_positive_factors": 0,
    "unknown_st_samples": 0,
    "invalid_lifecycle_samples": 0,
}
~~~

`check_dataset_quality` 增加必填 `dataset_version`；`report_id` 是 dataset version、gate version、排序后 thresholds 的 SHA-256 前 20 位，前缀为 `quality_`。

- [ ] **Step 4: 绑定数据指纹并登记**

`_quality_six_years` 使用 `SH600000`、`SZ000001`、`SZ300750` 中存在标的的最新日期作为 `expected_latest_date`，三个都缺失时加入 `reference_symbols_missing`。报告同时保存 manifest hash、raw file hash 清单、dataset SHA-256，并调用：

~~~python
store.upsert_quality_report({
    "id": report["report_id"],
    "dataset_id": SIX_YEAR_DATASET_ID,
    "dataset_version": report["dataset_version"],
    "gate_version": report["gate_version"],
    "passed": report["passed"],
    "report": report,
})
~~~

`_require_six_year_quality` 验证 gate version、manifest hash、dataset SHA-256 和 registry 记录完全一致，否则阻断导出和训练。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_quality_gate.py tests\test_qlib_job_worker.py tests\test_qlib_exporter.py -q
git status --short
git add quant\qlib\quality_gate.py scripts\qlib_job_worker.py tests\test_qlib_quality_gate.py tests\test_qlib_job_worker.py
git commit -m "feat: version qlib dataset quality gate"
~~~

若不是 Git 仓库，只登记 Task 4 检查点。

## Task 5: 受控 Alpha、模型和官方回测配置

**Files:**
- Modify: `requirements-qlib.txt:1-14`
- Modify: `quant/qlib/features.py:1-31`
- Create: `quant/qlib/workflow_config.py`
- Create: `tests/test_qlib_workflow_config.py`
- Modify: `scripts/setup_qlib_env.ps1`

- [ ] **Step 1: 写入固定矩阵测试**

~~~python
import pytest
from quant.qlib.workflow_config import (
    MODEL_MATRIX,
    build_dataset_config,
    build_model_config,
    build_port_analysis_config,
    config_sha256,
)


def test_phase1_matrix_is_bounded():
    assert MODEL_MATRIX == (
        ("Alpha158", "LightGBM"),
        ("Alpha360", "LightGBM"),
        ("Alpha158", "XGBoost"),
        ("Alpha158", "Linear"),
    )


@pytest.mark.parametrize("handler", ["Alpha158", "Alpha360"])
def test_dataset_config_uses_future_five_day_label(handler):
    config = build_dataset_config(
        handler=handler,
        instruments="all",
        segments={
            "train": ("2020-01-01", "2022-12-31"),
            "valid": ("2023-01-01", "2023-12-31"),
            "test": ("2024-01-01", "2024-12-31"),
        },
    )
    assert config["kwargs"]["handler"]["kwargs"]["label"] == [
        "Ref($close, -5) / $close - 1"
    ]


def test_model_seed_and_official_topk_config():
    assert build_model_config("LightGBM", 42)["kwargs"]["seed"] == 42
    assert build_model_config("XGBoost", 43)["kwargs"]["seed"] == 43
    assert build_model_config("Linear", 44)["kwargs"]["estimator"] == "ridge"
    port = build_port_analysis_config("2024-01-01", "2024-12-31")
    assert port["strategy"]["class"] == "TopkDropoutStrategy"
    assert port["strategy"]["kwargs"] == {
        "signal": "<PRED>", "topk": 50, "n_drop": 5
    }
    assert config_sha256({"a": 1, "b": 2}) == config_sha256({"b": 2, "a": 1})
~~~

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_workflow_config.py -q
~~~

Expected: import fails.

- [ ] **Step 3: 固定依赖和 Alpha360**

在 `requirements-qlib.txt` 增加：

~~~text
xgboost==2.1.4
~~~

`features.py` 提取通用 handler builder，并保留 `alpha158_handler_config`，新增同签名的 `alpha360_handler_config`。两者统一使用 RobustZScoreNorm、Fillna、DropnaLabel、CSRankNorm 和未来 5 日标签。

- [ ] **Step 4: 实现配置生成器**

`workflow_config.py` 定义上方 `MODEL_MATRIX`，并定义：

~~~python
MODEL_CONFIGS = {
    "LightGBM": {
        "class": "LGBModel",
        "module_path": "qlib.contrib.model.gbdt",
        "kwargs": {
            "loss": "mse", "learning_rate": 0.0421,
            "colsample_bytree": 0.8879, "subsample": 0.8789,
            "lambda_l1": 205.6999, "lambda_l2": 580.9768,
            "max_depth": 8, "num_leaves": 210, "num_threads": 8,
        },
    },
    "XGBoost": {
        "class": "XGBModel",
        "module_path": "qlib.contrib.model.xgboost",
        "kwargs": {
            "objective": "reg:squarederror", "eta": 0.05,
            "max_depth": 8, "subsample": 0.9,
            "colsample_bytree": 0.9, "nthread": 8,
        },
    },
    "Linear": {
        "class": "LinearModel",
        "module_path": "qlib.contrib.model.linear",
        "kwargs": {
            "estimator": "ridge", "alpha": 0.001,
            "fit_intercept": True,
        },
    },
}
~~~

`build_model_config` 深复制配置；LightGBM 写 seed、feature_fraction_seed、bagging_seed，XGBoost 写 seed，Linear 只在实验元数据记录 seed。`build_port_analysis_config` 固定 TopkDropout 50/5、日频 SimulatorExecutor、1 亿元账户、SH000300、收盘成交、开仓 0.0005、平仓 0.0015、最低费用 5 元。`config_sha256` 使用排序 JSON。

- [ ] **Step 5: 安装、探针和回归**

~~~powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_qlib_env.ps1
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_workflow_config.py tests\test_qlib_environment.py tests\test_qlib_dataset.py -q
git status --short
git add requirements-qlib.txt quant\qlib\features.py quant\qlib\workflow_config.py scripts\setup_qlib_env.ps1 tests\test_qlib_workflow_config.py
git commit -m "feat: define bounded qlib workflow matrix"
~~~

Expected: xgboost 2.1.4 可导入，tests pass。若不是 Git 仓库，只登记 Task 5 检查点。

## Task 6: 官方 Workflow、Recorder 和三类 Record

**Files:**
- Create: `quant/qlib/workflow_bridge.py`
- Create: `tests/test_qlib_workflow_bridge.py`
- Modify: `scripts/qlib_train.py:91-121,360-500`
- Modify: `tests/test_qlib_train_entry.py`

- [ ] **Step 1: 写入可注入运行时的编排测试**

~~~python
def test_workflow_generates_all_required_records(tmp_path):
    calls = []
    request = WorkflowRequest(
        local_experiment_id="local_1",
        dataset_id="a_share_6y_daily",
        dataset_version="daily-pit-v1",
        quality_report_id="quality_1",
        provider_uri=tmp_path / "qlib_bin",
        recorder_uri=(tmp_path / "mlruns").resolve().as_uri(),
        experiment_name="xuanji-qlib-daily",
        recorder_name="local_1",
        handler="Alpha158",
        model_type="LightGBM",
        seed=42,
        segments={
            "train": ("2020-01-01", "2022-12-31"),
            "valid": ("2023-01-01", "2023-12-31"),
            "test": ("2024-01-01", "2024-12-31"),
        },
    )
    result = run_workflow(
        request,
        runtime=FakeRuntime(calls, tmp_path / "artifacts"),
    )
    assert calls == [
        "qlib.init", "R.start", "model.fit", "R.save_objects",
        "SignalRecord.generate", "SigAnaRecord.generate",
        "PortAnaRecord.generate",
    ]
    assert result.status == "succeeded"
    assert result.recorder_id == "recorder_1"
~~~

同一测试文件定义运行时协议使用的假实现：

~~~python
from contextlib import contextmanager


class FakeRuntime:
    def __init__(self, calls, artifact_root, fail_at=""):
        self.calls = calls
        self.artifact_root = artifact_root
        self.fail_at = fail_at
        self.recorder = type("Recorder", (), {
            "id": "recorder_1",
            "experiment_id": "experiment_1",
        })()

    def init(self, request):
        self.calls.append("qlib.init")

    def build_dataset(self, config):
        return object()

    def build_model(self, config):
        runtime = self
        class Model:
            def fit(self, dataset):
                runtime.calls.append("model.fit")
        return Model()

    @contextmanager
    def start(self, request):
        self.calls.append("R.start")
        yield self.recorder

    def save_model(self, model):
        self.calls.append("R.save_objects")

    def generate_signal(self, model, dataset, recorder):
        self.calls.append("SignalRecord.generate")

    def generate_signal_analysis(self, recorder):
        self.calls.append("SigAnaRecord.generate")

    def generate_portfolio_analysis(self, recorder, config):
        self.calls.append("PortAnaRecord.generate")
        if self.fail_at == "PortAnaRecord.generate":
            raise RuntimeError("portfolio record failed")

    def finish(self):
        return {
            "artifact_root": self.artifact_root,
            "metrics": {},
            "artifacts": [],
        }
~~~

再写 `fail_at="PortAnaRecord.generate"` 测试，断言整个 Workflow 失败，不能返回 succeeded。生产 `QlibRuntime` 必须实现上述同名方法，`run_workflow` 只依赖这组接口。

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_workflow_bridge.py -q
~~~

Expected: import fails.

- [ ] **Step 3: 实现请求、结果和生产运行时**

定义不可变 `WorkflowRequest`、`WorkflowResult` 和可注入 `QlibRuntime`。`WorkflowResult` 字段固定为 local_experiment_id、dataset_id、dataset_version、quality_report_id、handler、model_type、seed、qlib_experiment_id、recorder_id、status、artifact_root、metrics、artifacts、config_hash。生产顺序必须是：

~~~python
qlib.init(
    provider_uri=str(request.provider_uri),
    region=REG_CN,
    expression_cache=None,
    dataset_cache=None,
    exp_manager={
        "class": "MLflowExpManager",
        "module_path": "qlib.workflow.expm",
        "kwargs": {
            "uri": request.recorder_uri,
            "default_exp_name": request.experiment_name,
        },
    },
)
dataset = init_instance_by_config(dataset_config)
model = init_instance_by_config(model_config)
with R.start(
    experiment_name=request.experiment_name,
    recorder_name=request.recorder_name,
    uri=request.recorder_uri,
):
    recorder = R.get_recorder()
    R.log_params(
        local_experiment_id=request.local_experiment_id,
        dataset_id=request.dataset_id,
        dataset_version=request.dataset_version,
        quality_report_id=request.quality_report_id,
        handler=request.handler,
        model_type=request.model_type,
        seed=request.seed,
        config_hash=config_hash,
    )
    model.fit(dataset)
    R.save_objects(**{"params.pkl": model})
    SignalRecord(model, dataset, recorder).generate()
    SigAnaRecord(recorder, ana_long_short=True).generate()
    PortAnaRecord(
        recorder,
        config=port_config,
        risk_analysis_freq="day",
        indicator_analysis_freq="day",
    ).generate()
~~~

结果记录 recorder ID、Qlib experiment ID、本地 artifact root、metrics、artifact list 和 config hash。

- [ ] **Step 4: 切换训练入口**

`scripts/qlib_train.py` 保留 official-demo 数据下载和 `official_demo_smoke` 状态，但训练与 Record 生成也必须调用 Workflow 桥；one-year 和 six-year-walk-forward 同样构造 `WorkflowRequest`。正式主链不再调用 `quant/qlib/trainer.py::train_lightgbm`。滚动窗口继续由 `build_walk_forward_windows` 生成，每个窗口一个 Recorder，父级报告聚合 Recorder 指标。

- [ ] **Step 5: 单元和官方示例验证**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_workflow_bridge.py tests\test_qlib_train_entry.py -q
.\.venv-qlib\Scripts\python.exe scripts\qlib_train.py --preset official-demo
git status --short
git add quant\qlib\workflow_bridge.py scripts\qlib_train.py tests\test_qlib_workflow_bridge.py tests\test_qlib_train_entry.py
git commit -m "feat: run qlib official workflow and records"
~~~

Expected: 三类 Record 均生成；官方示例仍为 `official_demo_smoke`。若不是 Git 仓库，只登记 Task 6 检查点。

## Task 7: Recorder 产物校验和幂等导入

**Files:**
- Create: `quant/qlib/artifact_importer.py`
- Create: `tests/test_qlib_artifact_importer.py`
- Modify: `quant/qlib/registry.py`
- Modify: `scripts/qlib_train.py`

- [ ] **Step 1: 写入缺产物和幂等测试**

~~~python
def test_import_rejects_missing_portfolio_record(tmp_path):
    result = fake_workflow_result(
        tmp_path, omit="portfolio_analysis/port_analysis_1day.pkl"
    )
    with pytest.raises(RuntimeError, match="port_analysis_1day"):
        import_workflow_result(result, Registry(tmp_path / "meta.db"))


def test_import_is_idempotent_and_hashes_files(tmp_path):
    result = fake_workflow_result(tmp_path)
    store = Registry(tmp_path / "meta.db")
    first = import_workflow_result(result, store)
    second = import_workflow_result(result, store)
    assert first["id"] == second["id"]
    assert len(store.list_workflow_runs()) == 1
    assert all(len(value) == 64 for value in first["artifacts"].values())
~~~

同一测试文件定义：

~~~python
from quant.qlib.workflow_bridge import WorkflowResult


def fake_workflow_result(tmp_path, omit=""):
    root = tmp_path / "artifacts"
    required = (
        "params.pkl", "pred.pkl", "label.pkl",
        "sig_analysis/ic.pkl", "sig_analysis/ric.pkl",
        "portfolio_analysis/report_normal_1day.pkl",
        "portfolio_analysis/positions_normal_1day.pkl",
        "portfolio_analysis/port_analysis_1day.pkl",
    )
    for name in required:
        if name == omit:
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("artifact:" + name).encode("utf-8"))
    return WorkflowResult(
        local_experiment_id="local_1",
        dataset_id="a_share_6y_daily",
        dataset_version="daily-pit-v1",
        quality_report_id="quality_1",
        handler="Alpha158",
        model_type="LightGBM",
        seed=42,
        qlib_experiment_id="experiment_1",
        recorder_id="recorder_1",
        status="succeeded",
        artifact_root=root,
        metrics={"Rank IC": 0.03},
        artifacts=list(required),
        config_hash="a" * 64,
    )
~~~

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_artifact_importer.py -q
~~~

- [ ] **Step 3: 实现必需产物 manifest**

~~~python
REQUIRED_ARTIFACTS = (
    "params.pkl",
    "pred.pkl",
    "label.pkl",
    "sig_analysis/ic.pkl",
    "sig_analysis/ric.pkl",
    "portfolio_analysis/report_normal_1day.pkl",
    "portfolio_analysis/positions_normal_1day.pkl",
    "portfolio_analysis/port_analysis_1day.pkl",
)
~~~

`QlibRuntime.finish` 把 `recorder.get_local_dir()` 下的 `artifacts` 子目录作为 `artifact_root`。`import_workflow_result` 拒绝路径穿越，逐文件 SHA-256，标准化 Rank IC、Rank ICIR、long-short 年化收益/Sharpe 与官方组合指标，依次 upsert 旧 experiments 兼容记录和新 workflow_runs 控制记录。同一 recorder_id 再导入只更新摘要。

- [ ] **Step 4: 绑定成功边界**

`qlib_train.py` 只有在 Recorder 状态成功、全部 artifact 存在、哈希完成且本地导入成功后才标记 experiment succeeded。缺失时标记 incomplete，不创建 candidate。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_artifact_importer.py tests\test_qlib_registry.py tests\test_qlib_train_entry.py -q
git status --short
git add quant\qlib\artifact_importer.py quant\qlib\registry.py scripts\qlib_train.py tests\test_qlib_artifact_importer.py
git commit -m "feat: import qlib recorder artifacts idempotently"
~~~

若不是 Git 仓库，只登记 Task 7 检查点。

## Task 8: A 股规则回测桥

**Files:**
- Create: `quant/qlib/ashare_backtest.py`
- Create: `tests/test_qlib_ashare_backtest.py`
- Modify: `quant/backtest/engine.py:264-330,400-423,538-590`
- Modify: `tests/test_backtest_timing.py`

- [ ] **Step 1: 写入信号和市场规则测试**

~~~python
import pandas as pd


def sample_prediction():
    index = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2026-07-01"), "SH600000"),
            (pd.Timestamp("2026-07-01"), "SZ000001"),
            (pd.Timestamp("2026-07-02"), "SH600000"),
            (pd.Timestamp("2026-07-02"), "SZ000001"),
        ],
        names=["datetime", "instrument"],
    )
    return pd.Series([0.8, 0.2, 0.1, 0.9], index=index, name="score")


def test_signal_bundle_has_provenance_and_no_orders():
    bundle = build_signal_bundle(
        prediction=sample_prediction(),
        workflow_run_id="wf_1",
        dataset_version="daily-pit-v1",
        topk=1,
        n_drop=1,
    )
    assert len(bundle["signal_hash"]) == 64
    assert "orders" not in bundle

class CapturingSimulator:
    kwargs = {}

    def __init__(self, **kwargs):
        type(self).kwargs = kwargs

    def add_signals(self, signals):
        self.signals = signals

    def add_klines(self, klines):
        self.klines = klines

    def run(self):
        return {"metrics": {"sharpe": 1.0}}


def test_bridge_passes_all_market_rules_to_simulator():
    bundle = build_signal_bundle(
        sample_prediction(), "wf_1", "daily-pit-v1", topk=1, n_drop=1
    )
    result = run_ashare_backtest(
        signal_bundle=bundle,
        klines={
            "600000": pd.DataFrame([{
                "date": "2026-07-01", "open": 10, "high": 10.2,
                "low": 9.8, "close": 10.1, "amount": 1000000,
                "paused": 0, "tradable": 1,
            }]),
            "000001": pd.DataFrame([{
                "date": "2026-07-01", "open": 12, "high": 12.2,
                "low": 11.8, "close": 12.1, "amount": 1000000,
                "paused": 0, "tradable": 1,
            }]),
        },
        config=ASHARE_BACKTEST_V1,
        simulator_factory=CapturingSimulator,
    )
    assert CapturingSimulator.kwargs["enforce_t1"] is True
    assert CapturingSimulator.kwargs["enforce_limit"] is True
    assert CapturingSimulator.kwargs["stamp_tax_rate"] == 0.001
    assert CapturingSimulator.kwargs["max_volume_pct"] == 0.10
    assert result["engine"] == "xuanji_ashare"
~~~

在 `tests/test_backtest_timing.py` 增加独立停牌场景：两日 K 线的第二日 `paused=1, tradable=0`，第一日收盘生成的买单在第二日开盘被拒绝；断言 `fill_count == 0`、`suspended_rejected == 1`、event log 含 `suspended_rejected`。

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_ashare_backtest.py -q
~~~

- [ ] **Step 3: 实现固定 A 股配置和信号转换**

~~~python
ASHARE_BACKTEST_V1 = {
    "version": "ashare_backtest_v1",
    "initial_cash": 100_000_000.0,
    "commission_rate": 0.0003,
    "min_commission": 5.0,
    "stamp_tax_rate": 0.001,
    "transfer_fee_rate": 0.00001,
    "slippage_rate": 0.0001,
    "position_size_pct": 0.95,
    "allow_short": False,
    "enforce_limit": True,
    "max_volume_pct": 0.10,
    "enforce_t1": True,
}
~~~

`build_signal_bundle` 每日按 score 维持 topk/n_drop 集合，进入集合为 1、离开为 -1，其余为 0；代码去掉 SH/SZ/BJ 前缀。signal hash 覆盖数据版本、workflow run、日期、代码、score、signal、topk、n_drop。

- [ ] **Step 4: 复用 BacktestSimulator**

`run_ashare_backtest` 增加关键字参数 `simulator_factory=BacktestSimulator`，构造后调用 `add_signals`、`add_klines`、`run`，结果加入 engine、signal_hash 和 config_version。`BacktestSimulator.add_klines` 把输入的 paused/tradable 写入 bar map；`_execute_pending_orders` 在价格和涨跌停判断前拒绝 paused=1 或 tradable=0 的标的，累加 `suspended_rejected` 并写事件日志。缺少 amount/OHLC/测试区间价格时明确失败，不能用 0 补齐。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_ashare_backtest.py -q
.\.venv-qlib\Scripts\python.exe -m pytest tests -q -k "backtest and not workflow_slow"
git status --short
git add quant\qlib\ashare_backtest.py quant\backtest\engine.py tests\test_qlib_ashare_backtest.py tests\test_backtest_timing.py
git commit -m "feat: add a-share constrained qlib backtest"
~~~

若不是 Git 仓库，只登记 Task 8 检查点。

## Task 9: 双门禁与无订单影子信号

**Files:**
- Create: `quant/qlib/promotion_gate.py`
- Create: `quant/qlib/shadow_signal.py`
- Create: `tests/test_qlib_promotion_gate.py`
- Create: `tests/test_qlib_shadow_signal.py`
- Modify: `quant/qlib/evaluator.py:10-28`
- Modify: `quant/qlib/walk_forward.py:76-111`
- Modify: `scripts/qlib_runner.py:358-371`
- Modify: `tests/test_qlib_runner_actions.py`

- [ ] **Step 1: 写入硬门槛和差异审查测试**

~~~python
def passing_payload():
    return {
        "quality_passed": True,
        "signal_metrics": {
            "window_count": 4,
            "median_rank_ic": 0.03,
            "median_icir": 0.40,
            "positive_rank_ic_ratio": 0.75,
            "aggregate_after_cost_long_short": 0.05,
            "aggregate_sharpe": 1.00,
            "max_drawdown": -0.10,
            "worst_rank_ic": -0.01,
        },
        "official_backtest": {
            "after_cost_return": 0.08,
            "annual_return": 0.12,
            "sharpe": 1.10,
            "max_drawdown": -0.12,
            "annual_turnover": 2.0,
        },
        "ashare_backtest": {
            "after_cost_return": 0.06,
            "annual_return": 0.10,
            "sharpe": 1.00,
            "max_drawdown": -0.14,
            "annual_turnover": 2.2,
        },
        "divergence_reviewed": False,
    }


def test_candidate_requires_both_backtests():
    assert evaluate_promotion_gate(**passing_payload())["status"] == "candidate"


def test_official_backtest_failure_is_rejected():
    payload = passing_payload()
    payload["official_backtest"]["sharpe"] = 0.79
    result = evaluate_promotion_gate(**payload)
    assert result["status"] == "rejected"
    assert "official_sharpe_below_0_80" in result["reason_codes"]


def test_divergence_requires_review_but_review_cannot_override_hard_failure():
    payload = passing_payload()
    payload["official_backtest"]["annual_return"] = 0.18
    payload["ashare_backtest"]["annual_return"] = 0.10
    assert evaluate_promotion_gate(**payload)["status"] == "review_required"
    payload["official_backtest"]["sharpe"] = 0.20
    payload["divergence_reviewed"] = True
    assert evaluate_promotion_gate(**payload)["status"] == "rejected"
~~~

`tests/test_qlib_shadow_signal.py` 写入：

~~~python
def test_shadow_signal_has_provenance_and_no_order_fields(tmp_path):
    result = write_shadow_signal(
        output_dir=tmp_path,
        model_id="model_1",
        workflow_run_id="wf_1",
        dataset_version="daily-pit-v1",
        signal_hash="a" * 64,
        predictions=[{
            "date": "2026-08-03",
            "instrument": "SH600000",
            "score": 0.8,
            "rank": 1,
        }],
    )
    payload = json.loads(result["path"].read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xuanji_shadow_signal_v1"
    assert payload["workflow_run_id"] == "wf_1"
    assert payload["dataset_version"] == "daily-pit-v1"
    for forbidden in ("quantity", "price", "order_type", "side", "orders"):
        assert forbidden not in result["path"].read_text(encoding="utf-8")
~~~

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_promotion_gate.py tests\test_qlib_shadow_signal.py -q
~~~

- [ ] **Step 3: 实现单一 gate version**

~~~python
GATE_VERSION = "qlib_phase1_gate_v1"
SIGNAL_LIMITS = {
    "window_count": 4,
    "median_rank_ic": 0.02,
    "median_icir": 0.30,
    "positive_rank_ic_ratio": 0.70,
    "aggregate_sharpe": 0.80,
    "max_drawdown": -0.20,
    "worst_rank_ic": -0.03,
}
BACKTEST_LIMITS = {
    "after_cost_return": 0.0,
    "sharpe": 0.80,
    "max_drawdown": -0.20,
}
DIVERGENCE_LIMITS = {
    "annual_return_abs": 0.05,
    "max_drawdown_abs": 0.05,
    "turnover_relative": 0.25,
}
~~~

存在数据/信号/任一回测硬失败返回 rejected；无硬失败但差异超限且没有人工说明返回 review_required；全部通过返回 candidate。`evaluator.py` 与 `walk_forward.py` 删除重复阈值，调用统一 helper。

- [ ] **Step 4: 写影子信号并复核晋升**

`shadow_signal.py` 原子写入由 `model_id` 和 `trade_date` 组成的 `data/qlib/shadow_signals/{model_id}/{trade_date}.json`，schema 为 `xuanji_shadow_signal_v1`。`promote_shadow` 必须重新读取 model、workflow run、gate version、artifact hash；只有 model 和 gate 都是 candidate 才生成信号并更新为 shadow。人工只能解除差异审查，不能覆盖硬失败。

- [ ] **Step 5: 回归并提交检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_promotion_gate.py tests\test_qlib_shadow_signal.py tests\test_qlib_evaluator.py tests\test_qlib_walk_forward.py tests\test_qlib_runner_actions.py -q
node scripts\qlib_control_contract_tests.mjs
git status --short
git add quant\qlib\promotion_gate.py quant\qlib\shadow_signal.py quant\qlib\evaluator.py quant\qlib\walk_forward.py scripts\qlib_runner.py tests\test_qlib_promotion_gate.py tests\test_qlib_shadow_signal.py tests\test_qlib_runner_actions.py
git commit -m "feat: enforce dual qlib promotion gate"
~~~

若不是 Git 仓库，只登记 Task 9 检查点。

## Task 10: 固定动作、阶段心跳和陈旧任务恢复

**Files:**
- Modify: `quant/qlib/jobs.py:19-120`
- Modify: `quant/qlib/registry.py:66-80,123-200`
- Modify: `scripts/qlib_job_worker.py:393-467`
- Modify: `scripts/qlib_runner.py:29-90,268-372`
- Modify: `tests/test_qlib_jobs.py`
- Modify: `tests/test_qlib_job_worker.py`
- Modify: `tests/test_qlib_runner_actions.py`
- Modify: `scripts/qlib_control_contract_tests.mjs`

- [ ] **Step 1: 写入阶段和恢复测试**

~~~python
def test_dead_worker_is_persisted_as_interrupted(tmp_path):
    store = Registry(tmp_path / "meta.db")
    manager = JobManager(store)
    job = manager.create("workflow_baseline", heavy=True)
    manager.transition(
        job["id"], "running", pid=999999, stage="train", run_token="run_1"
    )
    recovered = manager.recover_stale_jobs(process_alive=lambda _: False)
    assert recovered == [job["id"]]
    saved = store.get_job(job["id"])
    assert saved["status"] == "interrupted"
    assert saved["stage"] == "train"


def test_progress_persists_stage_heartbeat_and_run_token(tmp_path):
    store = Registry(tmp_path / "meta.db")
    manager = JobManager(store)
    job = manager.create("workflow_baseline", heavy=True)
    manager.transition(job["id"], "running", pid=123, run_token="run_2")
    progress = job_progress_callback(store, job["id"], "run_2")
    progress(0.5, "train", "正在训练 LightGBM")
    saved = store.get_job(job["id"])
    assert saved["stage"] == "train"
    assert saved["heartbeat_at"]
    assert saved["run_token"] == "run_2"
~~~

- [ ] **Step 2: 运行并确认缺字段**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_jobs.py tests\test_qlib_job_worker.py tests\test_qlib_runner_actions.py -q
~~~

Expected: new assertions fail.

- [ ] **Step 3: 增量扩展 jobs**

`Registry._init_schema` 通过幂等 `_ensure_column` 增加：

~~~sql
stage TEXT NOT NULL DEFAULT 'queued'
heartbeat_at TEXT
run_token TEXT NOT NULL DEFAULT ''
~~~

`update_job` 和 `JobManager.transition` 允许这些字段。`job_progress_callback(store, job_id, run_token)` 返回签名为 `progress(value, stage, message)` 的闭包，每次以 `utc_now()` 写 heartbeat。`recover_stale_jobs` 只处理 running/cancelling、PID 已死且 run token 属于当前任务的行，更新为 interrupted，保留原 result，并写审计事件。

- [ ] **Step 4: 加入固定 Workflow 动作**

runner 新增且仅新增以下动作：

~~~text
workflow_baseline
workflow_monthly_walk_forward
workflow_quarterly_matrix
backtest_ashare
resolve_backtest_divergence
quality_reports
workflow_runs
backtests
schedule_status
~~~

前三个控制动作不接受任意 handler/model/YAML 路径。baseline 固定 Alpha158 + LightGBM；monthly 固定 Alpha158 + LightGBM 多窗口；quarterly 固定 Task 5 的 MODEL_MATRIX。`resolve_backtest_divergence` 只接受 workflow_run_id 和不超过 1000 字的 review_note。

worker 阶段固定为：

~~~python
STAGES = (
    "collect", "quality", "export", "dataset", "train",
    "signal_record", "signal_analysis", "portfolio_analysis",
    "local_backtest", "register", "gate", "report",
)
~~~

每次 progress 更新 stage、heartbeat、run token 和中文 message。

- [ ] **Step 5: 运行控制契约**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_jobs.py tests\test_qlib_job_worker.py tests\test_qlib_runner_actions.py -q
node scripts\qlib_control_contract_tests.mjs
git status --short
git add quant\qlib\jobs.py quant\qlib\registry.py scripts\qlib_job_worker.py scripts\qlib_runner.py tests\test_qlib_jobs.py tests\test_qlib_job_worker.py tests\test_qlib_runner_actions.py scripts\qlib_control_contract_tests.mjs
git commit -m "feat: harden qlib workflow job control"
~~~

Expected: Python 与 Node 契约通过，额外字段和非白名单 action 被拒绝。若不是 Git 仓库，只登记 Task 10 检查点。

## Task 11: 周、月、季完整调度

**Files:**
- Modify: `scripts/qlib_schedule.py:1-147`
- Create: `tests/test_qlib_schedule.py`
- Modify: `scripts/qlib_schedule_contract_tests.mjs`

- [ ] **Step 1: 写入调度顺序测试**

~~~python
def fake_dispatcher(calls):
    def dispatch(kind, params, progress):
        calls.append(kind)
        if kind.startswith("quality_"):
            return {
                "passed": True,
                "report_id": "quality_1",
                "dataset_version": "daily-pit-v1",
            }
        if kind.startswith("workflow_"):
            return {
                "status": "succeeded",
                "workflow_run_ids": ["wf_1"],
                "artifacts_complete": True,
            }
        if kind == "backtest_ashare":
            return {
                "status": "succeeded",
                "engines": ["qlib_official", "xuanji_ashare"],
                "gate_status": "candidate",
            }
        return {"status": "succeeded", "dataset_version": "daily-pit-v1"}
    return dispatch


def test_weekly_runs_quality_before_workflow():
    calls = []
    result = run_weekly(
        force=True,
        now=datetime(2026, 8, 8, 18, 30),
        dispatcher=fake_dispatcher(calls),
    )
    assert calls == [
        "collect_six_years", "quality_six_years", "export_six_years",
        "workflow_baseline", "backtest_ashare",
    ]
    assert result["status"] == "succeeded"


def test_monthly_and_quarterly_use_fixed_pipelines():
    monthly = []
    run_six_year_cycle(
        mode="monthly", force=True,
        now=datetime(2026, 9, 5, 18, 30),
        dispatcher=fake_dispatcher(monthly),
    )
    assert monthly == [
        "collect_six_years", "quality_six_years", "export_six_years",
        "workflow_monthly_walk_forward", "backtest_ashare",
    ]
    quarterly = []
    run_six_year_cycle(
        mode="quarterly", force=True,
        now=datetime(2026, 10, 3, 18, 30),
        dispatcher=fake_dispatcher(quarterly),
    )
    assert "workflow_quarterly_matrix" in quarterly
    assert quarterly[-1] == "backtest_ashare"
~~~

- [ ] **Step 2: 运行并确认当前顺序失败**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_schedule.py -q
~~~

- [ ] **Step 3: 重构为可注入固定流水线**

`run_weekly` 与 `run_six_year_cycle` 接受 `now` 和 `dispatcher` 注入。周任务增量补齐六年主数据，依次运行六年质量门禁、导出、baseline 和 A 股回测；月任务运行六年 gate、导出、walk-forward、A 股回测；季任务串行运行四个固定矩阵项，防止模型并行抢内存。

完整成功必须包括：质量通过、Recorder 完整、SignalRecord/SigAnaRecord/PortAnaRecord 存在、官方回测存在、A 股回测存在、gate 已计算、报告已生成。没有新交易日返回 `status="succeeded", no_op=True`。季度任一矩阵项失败返回 `partial_failed`，不计入连续成功。

- [ ] **Step 4: 记录连续成功**

每次计划任务写 `schedule_cycle_succeeded` 或 `schedule_cycle_failed` 审计事件，包含 mode、dataset version、workflow run IDs 和各阶段结果。`schedule_status` 只统计最近同 mode、真实完整周期的连续成功；skipped、no-op、partial_failed 不增加计数。

- [ ] **Step 5: 调度回归和检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_schedule.py -q
node scripts\qlib_schedule_contract_tests.mjs
git status --short
git add scripts\qlib_schedule.py tests\test_qlib_schedule.py scripts\qlib_schedule_contract_tests.mjs
git commit -m "feat: schedule complete qlib research cycles"
~~~

Expected: tests pass，scheduler 不自动晋升超过 candidate。若不是 Git 仓库，只登记 Task 11 检查点。

## Task 12: 真实能力目录、API 和中文七页签

**Files:**
- Create: `quant/qlib/capabilities.py`
- Create: `tests/test_qlib_capabilities.py`
- Create: `lib/qlib-types.ts`
- Modify: `scripts/qlib_runner.py:170-257,301-372`
- Modify: `server/routes/qlib.mjs:1-23`
- Modify: `components/QlibResearchPanel.tsx:1-228`
- Modify: `components/qlib/QlibOverview.tsx`
- Modify: `components/qlib/QlibDataPanel.tsx`
- Modify: `components/qlib/QlibTrainingPanel.tsx`
- Modify: `components/qlib/QlibExperimentsPanel.tsx`
- Modify: `components/qlib/QlibModelsPanel.tsx`
- Modify: `components/qlib/QlibBacktestPanel.tsx`
- Modify: `lib/workbench-state.mjs`
- Modify: `scripts/qlib_panel_contract_tests.mjs`
- Modify: `scripts/qlib_chinese_ui_contract_tests.mjs`

- [ ] **Step 1: 写入真实状态测试**

~~~python
def test_code_presence_does_not_mean_ready():
    catalog = build_capability_catalog(
        environment={"ready": True, "versions": {"pyqlib": "0.9.7"}},
        quality_report=None,
        latest_workflow=None,
        dependencies={"xgboost": False},
    )
    by_id = {item["id"]: item["status"] for item in catalog}
    assert by_id["data"] == "受限"
    assert by_id["workflow"] == "未接入"
    assert by_id["xgboost"] == "受限"
    assert by_id["deep_learning"] == "未接入"


def test_workflow_ready_requires_complete_recorder():
    catalog = build_capability_catalog(
        environment={"ready": True, "versions": {"pyqlib": "0.9.7"}},
        quality_report={"passed": True},
        latest_workflow={"status": "succeeded", "artifacts_complete": True},
        dependencies={"xgboost": True},
    )
    assert {item["id"]: item["status"] for item in catalog}["workflow"] == "可用"
~~~

- [ ] **Step 2: 运行并确认模块不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_capabilities.py -q
~~~

- [ ] **Step 3: 实现能力状态和 API**

`capabilities.py` 只输出 可用、受限、运行中、失败、未接入。深度学习、Meta、RL、高频第一阶段固定未接入。Workflow 必须有最近成功且 artifact 完整的 Recorder 才可用。

runner `status` 增加：

~~~python
{
    "environment": environment,
    "data_root": str(data_root()),
    "data_root_override": bool(os.environ.get("QLIB_DATA_ROOT", "").strip()),
    "registry": str(store.db_path),
    "active_job": active_job,
    "latest_job": latest_job,
    "six_year_quality": quality,
    "schedule": schedule_status,
    "safety_boundary": "offline_research_only",
    "checked_at": checked_at,
    "catalog": build_capability_catalog(
        environment, quality, latest_workflow, dependencies
    ),
}
~~~

`server/routes/qlib.mjs` 保持轻量请求 30 秒边界；错误返回中文前缀，日志不记录 token。

- [ ] **Step 4: 强类型和七页签展示**

`lib/qlib-types.ts` 写入下列公共契约；嵌套 metrics/config 使用 `Record<string, unknown>`，页面读取前通过数值格式化 helper 收窄：

~~~typescript
export type QlibCapabilityState = '可用' | '受限' | '运行中' | '失败' | '未接入';

export interface QlibGateResult {
  gate_version: string;
  status: 'candidate' | 'rejected' | 'review_required';
  passed: boolean;
  reason_codes: string[];
  checks: Record<string, unknown>;
}

export interface QlibWorkflowRun {
  id: string;
  experiment_id: string;
  qlib_experiment_id: string;
  recorder_id: string;
  dataset_version: string;
  quality_report_id: string;
  handler: 'Alpha158' | 'Alpha360';
  model_type: 'LightGBM' | 'XGBoost' | 'Linear';
  seed: number;
  config_hash: string;
  status: string;
  recorded_path: string;
  resolved_path: string;
  path_state: 'active' | 'mapped_legacy' | 'missing_historical' | 'rejected_frozen';
  artifacts: Record<string, string>;
  metrics: Record<string, unknown>;
  gate: QlibGateResult;
}

export interface QlibBacktestResult {
  id: string;
  workflow_run_id: string;
  engine: 'qlib_official' | 'xuanji_ashare';
  signal_hash: string;
  metrics: Record<string, unknown>;
  config: Record<string, unknown>;
}

export interface QlibDataset {
  id: string;
  kind: string;
  status: string;
  start_date: string;
  end_date: string;
  latest_date: string;
  instruments: number;
  rows: number;
  coverage: number;
  path: string;
  metadata: Record<string, unknown>;
}

export interface QlibJob {
  id: string;
  kind: string;
  status: string;
  stage: string;
  progress: number;
  heartbeat_at?: string;
  message: string;
}

export interface QlibStatus {
  data_root: string;
  data_root_override: boolean;
  active_job: QlibJob | null;
  latest_job: QlibJob | null;
  six_year_quality: Record<string, unknown> | null;
  schedule: { mode: string; consecutive_successes: number };
  catalog: Array<{ id: string; name: string; status: QlibCapabilityState; items: string[] }>;
  checked_at: string;
}
~~~

`QlibResearchPanel.tsx` 移除 ResearchState 的 any，并读取 quality_reports、workflow_runs、backtests、schedule_status。

各页显示：

- 总览：活动根、override、真实能力、连续计划成功次数。
- 数据：dataset version、最新交易日、新鲜度、gate version、失败原因；旧路径标注“历史记录，不是活动路径”。
- 训练：固定 baseline、月度 walk-forward、季度矩阵，不提供任意模型/YAML 输入。
- 实验：本地 ID、Qlib experiment ID、Recorder ID、handler、model、窗口、seed、config hash、artifact 完整性。
- 回测：Qlib 官方与 A 股规则并排显示收益、Sharpe、最大回撤、换手、成本和差异审查。
- 模型：显示 gate 结果；只有 candidate 启用人工影子晋升。
- 日志：显示 stage、heartbeat、interrupted/failed 中文状态。

- [ ] **Step 5: 更新中文契约**

`workbench-state.mjs` 增加全部新 action、stage、status 的中文名称。Node 契约断言源码含：

~~~javascript
for (const label of [
  'Recorder ID',
  '数据版本',
  'Qlib 官方回测',
  'A 股规则回测',
  '差异审查',
  '历史记录，不是活动路径',
]) {
  assert(sourceBundle.includes(label), 'Qlib UI missing label: ' + label);
}
~~~

并断言 deep_learning、meta、rl、high_frequency 不会标为 ready。

- [ ] **Step 6: 前后端回归和检查点**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_capabilities.py tests\test_qlib_runner_actions.py -q
node scripts\qlib_control_contract_tests.mjs
node scripts\qlib_panel_contract_tests.mjs
node scripts\qlib_chinese_ui_contract_tests.mjs
npx tsc --noEmit
npm run build
git status --short
git add quant\qlib\capabilities.py tests\test_qlib_capabilities.py lib\qlib-types.ts scripts\qlib_runner.py server\routes\qlib.mjs components\QlibResearchPanel.tsx components\qlib lib\workbench-state.mjs scripts\qlib_panel_contract_tests.mjs scripts\qlib_chinese_ui_contract_tests.mjs
git commit -m "feat: expose truthful qlib research state"
~~~

Expected: tests、TypeScript、Vite build 全部通过。若不是 Git 仓库，只登记 Task 12 检查点。

## Task 13: 只读验收器、操作手册和全量验证

**Files:**
- Create: `scripts/qlib_acceptance.py`
- Create: `tests/test_qlib_acceptance.py`
- Modify: `README.md`
- Modify: `docs/XUANJI_HANDOFF.md`
- Modify: `docs/QLIB_LOCAL_TRAINING.md`

- [ ] **Step 1: 写入失败关闭验收测试**

~~~python
def complete_acceptance_snapshot(tmp_path):
    artifacts = {
        name: "a" * 64 for name in (
            "params.pkl", "pred.pkl", "label.pkl",
            "sig_analysis/ic.pkl", "sig_analysis/ric.pkl",
            "portfolio_analysis/report_normal_1day.pkl",
            "portfolio_analysis/positions_normal_1day.pkl",
            "portfolio_analysis/port_analysis_1day.pkl",
        )
    }
    return {
        "data_root": str(tmp_path / "qlib"),
        "quality": {
            "passed": True,
            "gate_version": "qlib_phase1_gate_v1",
        },
        "workflow_runs": [
            {
                "id": "wf_alpha158_lgb",
                "handler": "Alpha158",
                "model_type": "LightGBM",
                "status": "succeeded",
                "artifacts": dict(artifacts),
            },
            {
                "id": "wf_alpha360_lgb",
                "handler": "Alpha360",
                "model_type": "LightGBM",
                "status": "succeeded",
                "artifacts": dict(artifacts),
            },
            {
                "id": "wf_alpha158_xgb",
                "handler": "Alpha158",
                "model_type": "XGBoost",
                "status": "succeeded",
                "artifacts": dict(artifacts),
            },
            {
                "id": "wf_alpha158_linear",
                "handler": "Alpha158",
                "model_type": "Linear",
                "status": "succeeded",
                "artifacts": dict(artifacts),
            },
        ],
        "backtests": [
            {"workflow_run_id": "wf_alpha158_lgb", "engine": "qlib_official", "signal_hash": "s" * 64},
            {"workflow_run_id": "wf_alpha158_lgb", "engine": "xuanji_ashare", "signal_hash": "s" * 64},
        ],
        "gate": {
            "gate_version": "qlib_phase1_gate_v1",
            "status": "candidate",
        },
        "shadow_signals": [
            {"schema_version": "xuanji_shadow_signal_v1", "has_orders": False}
        ],
        "schedule": {"mode": "weekly", "consecutive_successes": 2},
    }


def test_acceptance_rejects_missing_artifact(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["workflow_runs"][0]["artifacts"].pop("pred.pkl")
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "recorder_artifacts_incomplete" in result["reason_codes"]


def test_acceptance_requires_two_schedule_successes(tmp_path):
    snapshot = complete_acceptance_snapshot(tmp_path)
    snapshot["schedule"]["consecutive_successes"] = 1
    result = evaluate_acceptance(snapshot)
    assert result["passed"] is False
    assert "schedule_successes_below_2" in result["reason_codes"]


def test_complete_snapshot_passes(tmp_path):
    result = evaluate_acceptance(complete_acceptance_snapshot(tmp_path))
    assert result["passed"] is True
    assert result["gate_version"] == "qlib_phase1_gate_v1"
~~~

- [ ] **Step 2: 运行并确认验收器不存在**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_acceptance.py -q
~~~

- [ ] **Step 3: 实现只读验收器**

`scripts/qlib_acceptance.py` 只读打开 qlib_meta.db，检查活动数据根、六年质量、Alpha158/Alpha360、LightGBM/XGBoost/Linear、Recorder 和八个必需 artifacts、同 signal hash 的双回测、统一 gate、无订单 shadow artifact、最近同 mode 连续两次完整成功。

~~~python
def main() -> int:
    result = evaluate_current_workspace()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1
~~~

验收器不得采集、训练、晋升或写数据库。

- [ ] **Step 4: 更新 README、交接和中文操作手册**

`README.md` 增加 Qlib 官方主链和文件关系。`XUANJI_HANDOFF.md` 记录活动/冻结/旧路径、Recorder 与 qlib_meta 职责、周/月/季调度、candidate/review/shadow/paper/风控边界。`QLIB_LOCAL_TRAINING.md` 更新当前进度、Web 操作、CLI、恢复、失败原因和第二阶段范围。

手册中的安全 CLI 通过 Node API 授权边界，使用环境变量且不打印 token：

~~~powershell
$headers = @{ 'X-XuanJi-Token' = $env:XUANJI_API_TOKEN }
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8880/api/qlib' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{ action = 'status' } | ConvertTo-Json -Compress)

Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8880/api/qlib' `
  -Headers $headers -ContentType 'application/json' `
  -Body (@{ action = 'collect_six_years' } | ConvertTo-Json -Compress)

.\.venv-qlib\Scripts\python.exe scripts\qlib_schedule.py --mode monthly --force
.\.venv-qlib\Scripts\python.exe scripts\qlib_schedule.py --mode quarterly --force
.\.venv-qlib\Scripts\python.exe scripts\qlib_acceptance.py
~~~

- [ ] **Step 5: 运行 Qlib 定向回归**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_qlib_paths.py tests\test_qlib_failures.py tests\test_qlib_workflow_config.py tests\test_qlib_workflow_bridge.py tests\test_qlib_artifact_importer.py tests\test_qlib_ashare_backtest.py tests\test_qlib_promotion_gate.py tests\test_qlib_shadow_signal.py tests\test_qlib_capabilities.py tests\test_qlib_acceptance.py tests\test_qlib_registry.py tests\test_qlib_jobs.py tests\test_qlib_job_worker.py tests\test_qlib_schedule.py -q
node scripts\qlib_control_contract_tests.mjs
node scripts\qlib_schedule_contract_tests.mjs
node scripts\qlib_panel_contract_tests.mjs
node scripts\qlib_chinese_ui_contract_tests.mjs
~~~

Expected: selected Python tests and four Node contracts pass.

- [ ] **Step 6: 运行项目级回归**

~~~powershell
.\.venv-qlib\Scripts\python.exe -m pytest tests -q
npx tsc --noEmit
npm run build
node scripts\web_verify.mjs
~~~

Expected: Python suite only保留已记录 skip；TypeScript、Vite、Web verification pass。

- [ ] **Step 7: 执行受控离线验收**

先确认没有活动 Qlib job，再通过 Web 控制面依次执行六年采集、质量、导出、月度 walk-forward 和季度矩阵，不并行模型训练。然后运行：

~~~powershell
.\.venv-qlib\Scripts\python.exe scripts\qlib_acceptance.py
~~~

最终输出必须同时表明：

~~~text
passed: true
gate_version: qlib_phase1_gate_v1
quality: passed
handlers: Alpha158, Alpha360
models: LightGBM, XGBoost, Linear
record_types: SignalRecord, SigAnaRecord, PortAnaRecord
backtests: qlib_official, xuanji_ashare
schedule_consecutive_successes: 2
~~~

连续成功必须来自真实完整周期；手工改审计记录或重复导入同一 run 不计数。

- [ ] **Step 8: 文档检查点**

~~~powershell
git status --short
git add scripts\qlib_acceptance.py tests\test_qlib_acceptance.py README.md docs\XUANJI_HANDOFF.md docs\QLIB_LOCAL_TRAINING.md
git commit -m "docs: complete qlib workflow operations handoff"
~~~

若不是 Git 仓库，只登记 Task 13 检查点。

## 最终完成判定

只有 Task 1-13 全部完成、定向和项目级回归通过、`scripts/qlib_acceptance.py` 返回 0，并且真实调度连续成功两次，才可以宣称第一阶段完成。若六年采集、模型矩阵或连续调度尚未完成，状态必须写“代码实施完成，离线验收未完成”，不能写“Qlib 已 100% 投用”。

本计划不授权实盘交易、自动晋升、风控绕过、冻结备份写入，也不授权第二阶段深度学习、Meta、RL、高频或 RD-Agent 实施。
