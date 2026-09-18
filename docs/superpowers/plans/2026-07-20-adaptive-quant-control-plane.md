# A股自适应量化控制平面 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变真实交易边界的前提下，为 XuanJiQuant 建立模型漂移监控、三状态市场识别、策略路由和四分之一凯利仓位裁剪，并默认以 shadow-only 方式运行。

**Architecture:** Qlib 独立环境负责研究快照和 HMM 训练，在线 Python 运行时只加载经过 schema、时间和哈希校验的不可变产物。新增 `quant/adaptive` 控制平面依次执行健康评估、状态推断、策略路由和仓位裁剪；只有人工批准的 `paper_guarded` 可以收紧模拟盘权重，最终仍经过现有 decision normalization、verifier 和 risk gateway。

**Tech Stack:** Python 3.11/3.14、pandas、NumPy、SciPy、scikit-learn、hmmlearn 0.3.3、SQLite KV、Qlib registry、Node.js、React 19、TypeScript、Vite、pytest。

---

## 0. 执行约束

- 当前工作目录不是 Git 仓库。每个任务以聚焦测试和文件清单作为检查点，不执行伪造的 Git 提交。
- 不安装依赖到系统 Python。`hmmlearn==0.3.3` 只加入 `requirements-qlib.txt`，由 `.venv-qlib` 使用。
- 不连接真实券商，不启用实盘自动下单。
- 默认 `activation_level=observe`。
- 在 Task 10 完成前，不允许任何新增模块修改 `ai:decision:latest`。
- 在 Task 12 完成并人工确认前，不允许启用 `paper_guarded`。

## 1. 文件结构

### 新建

```text
quant/adaptive/__init__.py
quant/adaptive/contracts.py
quant/adaptive/activation.py
quant/adaptive/snapshot.py
quant/adaptive/drift.py
quant/adaptive/health.py
quant/adaptive/regime.py
quant/adaptive/routing.py
quant/adaptive/sizing.py
quant/adaptive/control.py

quant/qlib/regime_model.py

scripts/adaptive_snapshot.py
scripts/adaptive_health.py
scripts/adaptive_regime.py
scripts/adaptive_runner.py

server/routes/adaptive.mjs

components/AdaptiveControlPanel.tsx

tests/test_adaptive_contracts.py
tests/test_adaptive_snapshot.py
tests/test_adaptive_drift.py
tests/test_adaptive_health.py
tests/test_adaptive_regime.py
tests/test_adaptive_routing.py
tests/test_adaptive_sizing.py
tests/test_adaptive_control.py
tests/test_adaptive_ai_loop.py

scripts/adaptive_api_contract_tests.mjs
scripts/adaptive_frontend_contract_tests.mjs
```

### 修改

```text
requirements-qlib.txt
quant/ai/promotion.py
quant/factor/ai_factor_loader.py
quant/ai/contracts.py
scripts/qlib_runner.py
scripts/qlib_job_worker.py
scripts/ai_loop.py
scripts/ai_verifier.py
scripts/paper_runner.py
server/router.mjs
components/StrategyPanel.tsx
components/DashboardPanel.tsx
README.md
docs/QLIB_LOCAL_TRAINING.md
```

---

### Task 1: 建立自适应配置、权限和输出契约

**Files:**
- Create: `quant/adaptive/__init__.py`
- Create: `quant/adaptive/contracts.py`
- Create: `quant/adaptive/activation.py`
- Test: `tests/test_adaptive_contracts.py`

- [ ] **Step 1: 写配置默认值和权限污染的失败测试**

```python
from quant.adaptive.activation import (
    DEFAULT_ADAPTIVE_CONFIG,
    activation_permissions,
    normalize_adaptive_config,
)
from quant.adaptive.contracts import sanitize_shadow_output


def test_adaptive_defaults_are_observe_only():
    cfg = normalize_adaptive_config({})
    assert cfg == DEFAULT_ADAPTIVE_CONFIG
    assert cfg["activation_level"] == "observe"
    assert cfg["kelly_fraction"] == 0.25
    assert cfg["allow_leverage"] is False
    assert cfg["allow_short"] is False


def test_shadow_output_cannot_gain_execution_authority():
    out = sanitize_shadow_output({
        "mode": "paper_guarded",
        "can_change_trade_policy": True,
        "can_trigger_order": True,
    })
    assert out["mode"] == "shadow_only"
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False


def test_only_paper_guarded_can_apply_weight_cuts():
    assert activation_permissions("observe")["apply_weight_cuts"] is False
    assert activation_permissions("route_shadow")["apply_weight_cuts"] is False
    assert activation_permissions("size_shadow")["apply_weight_cuts"] is False
    assert activation_permissions("paper_guarded")["apply_weight_cuts"] is True
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_contracts.py -q
```

Expected: FAIL，提示 `quant.adaptive` 或目标函数不存在。

- [ ] **Step 3: 实现最小配置和权限契约**

`quant/adaptive/activation.py`：

```python
from __future__ import annotations

from copy import deepcopy


ACTIVATION_LEVELS = (
    "observe",
    "route_shadow",
    "size_shadow",
    "paper_guarded",
)

DEFAULT_ADAPTIVE_CONFIG = {
    "enabled": True,
    "activation_level": "observe",
    "regime_states": 3,
    "kelly_fraction": 0.25,
    "allow_leverage": False,
    "allow_short": False,
    "min_regime_confidence": 0.65,
    "regime_confirmation_windows": 2,
    "drift_failure_windows": 3,
    "max_strategy_weight": 0.50,
    "max_adaptive_gross_exposure_pct": 80.0,
    "fallback_mode": "existing_policy",
    "human_approval_required": True,
}


def normalize_adaptive_config(value: dict | None) -> dict:
    out = deepcopy(DEFAULT_ADAPTIVE_CONFIG)
    source = value if isinstance(value, dict) else {}
    for key in out:
        if key in source:
            out[key] = source[key]
    if out["activation_level"] not in ACTIVATION_LEVELS:
        out["activation_level"] = "observe"
    out["regime_states"] = 3
    out["kelly_fraction"] = min(0.25, max(0.0, float(out["kelly_fraction"])))
    out["allow_leverage"] = False
    out["allow_short"] = False
    out["human_approval_required"] = True
    return out


def activation_permissions(level: str) -> dict:
    normalized = level if level in ACTIVATION_LEVELS else "observe"
    return {
        "publish_health": True,
        "publish_regime": True,
        "publish_route": normalized in {"route_shadow", "size_shadow", "paper_guarded"},
        "publish_sizing": normalized in {"size_shadow", "paper_guarded"},
        "apply_weight_cuts": normalized == "paper_guarded",
        "can_trigger_order": False,
        "can_change_trade_policy": False,
    }
```

`quant/adaptive/contracts.py`：

```python
from __future__ import annotations

from copy import deepcopy


def sanitize_shadow_output(value: dict | None) -> dict:
    out = deepcopy(value) if isinstance(value, dict) else {}
    out["mode"] = "shadow_only"
    out["can_change_trade_policy"] = False
    out["can_trigger_order"] = False
    return out


def require_schema(payload: dict, expected: str) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if payload.get("schema_version") != expected:
        raise ValueError(f"invalid schema_version: {payload.get('schema_version')}")
    return payload
```

`quant/adaptive/__init__.py`：

```python
"""Deterministic adaptive control plane for research and paper trading."""
```

- [ ] **Step 4: 运行测试并确认通过**

Run:

```powershell
python -m pytest tests\test_adaptive_contracts.py -q
```

Expected: `3 passed`。

- [ ] **Step 5: 检查点**

记录新增文件，并确认没有修改 `scripts/ai_loop.py`、`paper_trader.py` 或风控文件。

---

### Task 2: 建立 Qlib 只读研究快照桥接

**Files:**
- Create: `quant/adaptive/snapshot.py`
- Create: `scripts/adaptive_snapshot.py`
- Modify: `quant/qlib/registry.py`
- Test: `tests/test_adaptive_snapshot.py`

- [ ] **Step 1: 写原子快照、哈希和拒绝损坏产物的失败测试**

```python
import json

import pytest

from quant.adaptive.snapshot import (
    load_research_snapshot,
    write_research_snapshot,
)


def test_snapshot_round_trip_uses_hash_and_schema(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    payload = {
        "schema_version": "adaptive-research.v1",
        "generated_at": "2026-07-20T18:30:00+08:00",
        "dataset": {
            "id": "a_share_6y_daily",
            "latest_date": "2026-07-20",
            "quality_passed": True,
            "manifest_hash": "a" * 64,
        },
        "models": [],
    }
    written = write_research_snapshot(payload, latest)
    loaded = load_research_snapshot(latest)
    assert loaded["snapshot_sha256"] == written["snapshot_sha256"]
    assert loaded["dataset"]["quality_passed"] is True


def test_snapshot_rejects_tampering(tmp_path):
    latest = tmp_path / "adaptive-research-latest.json"
    write_research_snapshot({
        "schema_version": "adaptive-research.v1",
        "generated_at": "2026-07-20T18:30:00+08:00",
        "dataset": {"quality_passed": True},
        "models": [],
    }, latest)
    raw = json.loads(latest.read_text(encoding="utf-8"))
    raw["dataset"]["quality_passed"] = False
    latest.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        load_research_snapshot(latest)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_snapshot.py -q
```

Expected: FAIL，目标模块不存在。

- [ ] **Step 3: 实现规范化 JSON、SHA-256 和原子替换**

`quant/adaptive/snapshot.py`：

```python
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from .contracts import require_schema


def _canonical(payload: dict) -> bytes:
    clean = dict(payload)
    clean.pop("snapshot_sha256", None)
    return json.dumps(
        clean,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def write_research_snapshot(payload: dict, path: Path) -> dict:
    out = require_schema(dict(payload), "adaptive-research.v1")
    out["snapshot_sha256"] = hashlib.sha256(_canonical(out)).hexdigest()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temp, target)
    return out


def load_research_snapshot(path: Path) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    require_schema(payload, "adaptive-research.v1")
    expected = str(payload.get("snapshot_sha256") or "")
    actual = hashlib.sha256(_canonical(payload)).hexdigest()
    if expected != actual:
        raise ValueError("snapshot hash mismatch")
    return payload
```

`scripts/adaptive_snapshot.py` 必须从 `qlib_meta.db` 读取 `datasets/models/experiments`，
构建固定 schema，并写入 `runtime_exports`。不得导入 `quant.data.cache`：

```python
def build_snapshot(store, quality_report: dict) -> dict:
    models = store.list_models(500)
    experiments = {row["id"]: row for row in store.list_experiments(500)}
    return {
        "schema_version": "adaptive-research.v1",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "id": "a_share_6y_daily",
            "latest_date": quality_report.get("latest_date"),
            "quality_passed": bool(quality_report.get("passed")),
            "manifest_hash": quality_report.get("manifest_hash", ""),
        },
        "models": [
            {
                **model,
                "walk_forward_metrics": (
                    experiments.get(model["experiment_id"], {}).get("metrics") or {}
                ),
            }
            for model in models
        ],
    }
```

在 `quant/qlib/registry.py` 增加只读 `get_model(model_id)` 和
`get_experiment(experiment_id)`，只接受已有 ID，不接受表名或 SQL。

- [ ] **Step 4: 运行聚焦测试和 Qlib 注册表测试**

Run:

```powershell
python -m pytest tests\test_adaptive_snapshot.py tests\test_qlib_registry.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 验证跨库边界**

Run:

```powershell
rg -n "quant\.data\.cache|data[/\\\\]quant\.db" scripts\adaptive_snapshot.py quant\adaptive\snapshot.py
```

Expected: 无匹配。

---

### Task 3: 实现漂移统计

**Files:**
- Create: `quant/adaptive/drift.py`
- Test: `tests/test_adaptive_drift.py`

- [ ] **Step 1: 写 PSI、KS、缺失率和无效输入测试**

```python
import math

from quant.adaptive.drift import compare_numeric_distributions


def test_equal_distributions_have_low_drift():
    out = compare_numeric_distributions(
        reference=[1, 2, 3, 4, 5] * 20,
        current=[1, 2, 3, 4, 5] * 20,
    )
    assert out["available"] is True
    assert out["psi"] < 0.01
    assert out["ks_stat"] == 0


def test_shifted_distributions_raise_drift():
    out = compare_numeric_distributions(
        reference=list(range(100)),
        current=list(range(100, 200)),
    )
    assert out["psi"] >= 0.25
    assert out["ks_stat"] >= 0.9


def test_missing_and_non_finite_values_are_reported():
    out = compare_numeric_distributions(
        reference=[1, 2, None, float("nan")],
        current=[None, float("inf"), 2, 3],
    )
    assert math.isclose(out["reference_missing_rate"], 0.5)
    assert math.isclose(out["current_missing_rate"], 0.5)
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_drift.py -q
```

Expected: FAIL，函数不存在。

- [ ] **Step 3: 实现确定性分箱 PSI 和 KS**

```python
from __future__ import annotations

import math

import numpy as np
from scipy.stats import ks_2samp


def _finite(values):
    rows = []
    total = 0
    for value in values or []:
        total += 1
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            rows.append(number)
    return np.asarray(rows, dtype=float), total


def compare_numeric_distributions(reference, current, bins: int = 10) -> dict:
    ref, ref_total = _finite(reference)
    cur, cur_total = _finite(current)
    if len(ref) < 2 or len(cur) < 2:
        return {
            "available": False,
            "reason": "insufficient_samples",
            "reference_count": len(ref),
            "current_count": len(cur),
        }
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        edges = np.asarray([-np.inf, np.inf])
    else:
        edges[0], edges[-1] = -np.inf, np.inf
    ref_hist = np.histogram(ref, bins=edges)[0] / len(ref)
    cur_hist = np.histogram(cur, bins=edges)[0] / len(cur)
    epsilon = 1e-6
    psi = float(np.sum(
        (cur_hist - ref_hist)
        * np.log((cur_hist + epsilon) / (ref_hist + epsilon))
    ))
    ks = ks_2samp(ref, cur, alternative="two-sided", mode="auto")
    return {
        "available": True,
        "psi": round(max(0.0, psi), 6),
        "ks_stat": round(float(ks.statistic), 6),
        "ks_pvalue": round(float(ks.pvalue), 6),
        "reference_count": len(ref),
        "current_count": len(cur),
        "reference_missing_rate": (ref_total - len(ref)) / max(ref_total, 1),
        "current_missing_rate": (cur_total - len(cur)) / max(cur_total, 1),
    }
```

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_drift.py -q
```

Expected: `3 passed`。

- [ ] **Step 5: 检查点**

确认该模块不读取数据库、不写缓存、不导入 LLM 或执行模块。

---

### Task 4: 实现模型健康状态与运行时隔离

**Files:**
- Create: `quant/adaptive/health.py`
- Create: `scripts/adaptive_health.py`
- Modify: `quant/factor/ai_factor_loader.py`
- Modify: `quant/ai/promotion.py`
- Test: `tests/test_adaptive_health.py`
- Test: `tests/test_ai_data_factor_adaptation.py`
- Test: `tests/test_promotion.py`

- [ ] **Step 1: 写连续窗口、隔离和恢复失败测试**

```python
from quant.adaptive.health import (
    evaluate_health_state,
    runtime_eligible,
)


def test_single_failure_moves_to_watch_only():
    out = evaluate_health_state(
        previous="healthy",
        recent_windows=[{"hard_failure": False, "drift_failed": True}],
        failure_windows=3,
    )
    assert out["health_state"] == "watch"


def test_three_failures_quarantine_model():
    rows = [{"hard_failure": False, "drift_failed": True}] * 3
    out = evaluate_health_state(
        previous="degraded",
        recent_windows=rows,
        failure_windows=3,
    )
    assert out["health_state"] == "quarantined"
    assert runtime_eligible("approved", out["health_state"]) is False


def test_hard_data_failure_quarantines_immediately():
    out = evaluate_health_state(
        previous="healthy",
        recent_windows=[{"hard_failure": True, "drift_failed": False}],
        failure_windows=3,
    )
    assert out["health_state"] == "quarantined"
```

扩展 `test_ai_data_factor_adaptation.py`：

```python
def test_factor_loader_excludes_quarantined_approved_factor(monkeypatch):
    fake = FakeCache({
        "ai:factor:approved": [{
            "name": "bad_factor",
            "promotion_state": "approved",
            "dsl": {"type": "column", "name": "close"},
        }],
        "adaptive:model_health:bad_factor": {
            "health_state": "quarantined",
        },
    })
    monkeypatch.setattr(ai_factor_loader, "_cache", lambda: fake)
    assert ai_factor_loader.get_approved_factors(fake) == []
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_health.py tests\test_ai_data_factor_adaptation.py -q
```

Expected: 新测试失败。

- [ ] **Step 3: 实现正交健康状态**

`quant/adaptive/health.py`：

```python
from __future__ import annotations


HEALTH_STATES = ("healthy", "watch", "degraded", "quarantined")
ELIGIBLE_PROMOTION_STATES = (
    "paper_active",
    "production_candidate",
    "approved",
)


def evaluate_health_state(
    *,
    previous: str,
    recent_windows: list[dict],
    failure_windows: int,
) -> dict:
    prior = previous if previous in HEALTH_STATES else "watch"
    rows = [row for row in recent_windows if isinstance(row, dict)]
    if any(row.get("hard_failure") is True for row in rows[-1:]):
        state = "quarantined"
        reason = "hard_failure"
    else:
        streak = 0
        for row in reversed(rows):
            if row.get("drift_failed") is True:
                streak += 1
            else:
                break
        if streak >= max(1, int(failure_windows)):
            state = "quarantined" if prior == "degraded" else "degraded"
            reason = "consecutive_drift_failures"
        elif streak:
            state = "watch" if prior == "healthy" else prior
            reason = "single_window_warning"
        elif prior == "degraded":
            state = "watch"
            reason = "recovering"
        elif prior == "quarantined":
            state = "quarantined"
            reason = "manual_revalidation_required"
        else:
            state = "healthy"
            reason = "healthy"
    return {"health_state": state, "reason": reason}


def runtime_eligible(promotion_state: str, health_state: str) -> bool:
    return (
        promotion_state in ELIGIBLE_PROMOTION_STATES
        and health_state != "quarantined"
    )
```

修改 `ai_factor_loader.get_approved_factors()`：读取
`adaptive:model_health:<factor_name>`，`quarantined` 时跳过。

保留 `promotion_state=approved` 的历史审批语义；在
`quant/ai/promotion.py` 的输出中增加：

```python
from quant.adaptive.health import runtime_eligible


record["runtime_eligible"] = runtime_eligible(
    state,
    str((cache.get(f"adaptive:model_health:{name}") or {}).get("health_state") or "watch"),
)
```

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_health.py tests\test_ai_data_factor_adaptation.py tests\test_promotion.py -q
```

Expected: 全部通过，原有批准状态测试保持通过。

- [ ] **Step 5: 验证批准状态与运行资格分离**

运行一个批准但隔离的假对象，确认：

```text
promotion_state=approved
health_state=quarantined
runtime_eligible=false
```

---

### Task 5: 在 Qlib 环境训练三状态 HMM

**Files:**
- Modify: `requirements-qlib.txt`
- Create: `quant/qlib/regime_model.py`
- Create: `scripts/adaptive_regime.py`
- Modify: `scripts/qlib_runner.py`
- Modify: `scripts/qlib_job_worker.py`
- Test: `tests/test_adaptive_regime.py`
- Test: `tests/test_qlib_runner_actions.py`

- [ ] **Step 1: 写训练、语义映射和产物哈希失败测试**

```python
import numpy as np
import pandas as pd

from quant.qlib.regime_model import (
    map_hidden_states,
    train_regime_model,
)


def regime_frame():
    index = pd.date_range("2020-01-01", periods=360, freq="B")
    return pd.DataFrame({
        "ret_20": np.r_[
            np.full(120, 0.05),
            np.zeros(120),
            np.full(120, -0.06),
        ],
        "realized_vol_20": np.r_[
            np.full(120, 0.10),
            np.full(120, 0.18),
            np.full(120, 0.35),
        ],
        "breadth": np.r_[
            np.full(120, 0.70),
            np.full(120, 0.50),
            np.full(120, 0.25),
        ],
    }, index=index)


def test_three_states_map_to_stable_semantics(tmp_path):
    artifact = train_regime_model(
        regime_frame(),
        feature_names=["ret_20", "realized_vol_20", "breadth"],
        output_path=tmp_path / "regime.joblib",
        random_state=7,
    )
    assert set(artifact["state_mapping"].values()) == {
        "risk_on", "range", "stress",
    }
    assert len(artifact["artifact_sha256"]) == 64


def test_state_mapping_uses_return_and_volatility():
    mapping = map_hidden_states({
        0: {"ret_20": 0.04, "realized_vol_20": 0.10},
        1: {"ret_20": 0.00, "realized_vol_20": 0.18},
        2: {"ret_20": -0.05, "realized_vol_20": 0.35},
    })
    assert mapping == {0: "risk_on", 1: "range", 2: "stress"}
```

- [ ] **Step 2: 添加隔离依赖并确认测试先因模块缺失失败**

在 `requirements-qlib.txt` 增加：

```text
hmmlearn==0.3.3
```

先运行：

```powershell
.venv-qlib\Scripts\python.exe -m pytest tests\test_adaptive_regime.py -q
```

Expected: FAIL，`quant.qlib.regime_model` 不存在。

如果 `.venv-qlib` 尚未安装新增依赖，按项目现有安装脚本更新该隔离环境，
不得使用系统 Python 安装。

- [ ] **Step 3: 实现标准化、GaussianHMM、语义映射和不可变产物**

核心实现：

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler


def map_hidden_states(state_means: dict[int, dict[str, float]]) -> dict[int, str]:
    ordered = sorted(
        state_means,
        key=lambda state: (
            state_means[state].get("ret_20", 0),
            -state_means[state].get("realized_vol_20", 0),
        ),
        reverse=True,
    )
    return {
        ordered[0]: "risk_on",
        ordered[1]: "range",
        ordered[2]: "stress",
    }


def train_regime_model(
    frame: pd.DataFrame,
    *,
    feature_names: list[str],
    output_path: Path,
    random_state: int = 7,
) -> dict:
    clean = frame[feature_names].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 252:
        raise ValueError("regime training requires at least 252 rows")
    scaler = StandardScaler()
    values = scaler.fit_transform(clean)
    model = GaussianHMM(
        n_components=3,
        covariance_type="diag",
        n_iter=300,
        random_state=random_state,
    )
    states = model.fit_predict(values)
    means = {
        int(state): {
            name: float(clean.loc[states == state, name].mean())
            for name in feature_names
        }
        for state in range(3)
    }
    artifact = {
        "schema_version": "adaptive-regime-model.v1",
        "feature_names": feature_names,
        "scaler": scaler,
        "model": model,
        "state_mapping": map_hidden_states(means),
        "state_means": means,
        "training_start": clean.index.min().isoformat(),
        "training_end": clean.index.max().isoformat(),
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, target)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        "schema_version": artifact["schema_version"],
        "path": str(target),
        "artifact_sha256": digest,
        "state_mapping": artifact["state_mapping"],
    }
```

`scripts/qlib_runner.py` 新增固定动作 `train_regime`；不得接受文件路径参数。
`scripts/qlib_job_worker.py` 将 `train_regime` 映射到固定函数，产物固定写入：

```text
C:\Users\HYSHEN\XuanJiQuant\data\qlib\models\regime\regime-latest.joblib
C:\Users\HYSHEN\XuanJiQuant\data\qlib\models\regime\regime-latest.json
```

- [ ] **Step 4: 运行聚焦测试**

Run:

```powershell
.venv-qlib\Scripts\python.exe -m pytest tests\test_adaptive_regime.py tests\test_qlib_runner_actions.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 验证 Qlib 安全边界**

Run:

```powershell
rg -n "quant\.data\.cache|data[/\\\\]quant\.db|subprocess.*request|shell=True" quant\qlib\regime_model.py scripts\adaptive_regime.py
```

Expected: 无跨库写入和动态命令执行。

---

### Task 6: 实现运行时状态推断、置信度和防抖

**Files:**
- Create: `quant/adaptive/regime.py`
- Extend: `tests/test_adaptive_regime.py`

- [ ] **Step 1: 写低置信度、确认窗口、stress紧急收紧测试**

```python
from quant.adaptive.regime import confirm_regime


def test_low_confidence_keeps_confirmed_state():
    out = confirm_regime(
        confirmed_state="range",
        recent_predictions=[{"state": "risk_on", "confidence": 0.50}],
        min_confidence=0.65,
        confirmation_windows=2,
    )
    assert out["state"] == "range"
    assert out["changed"] is False


def test_two_confident_windows_switch_state():
    rows = [
        {"state": "risk_on", "confidence": 0.80},
        {"state": "risk_on", "confidence": 0.78},
    ]
    out = confirm_regime(
        confirmed_state="range",
        recent_predictions=rows,
        min_confidence=0.65,
        confirmation_windows=2,
    )
    assert out["state"] == "risk_on"
    assert out["changed"] is True


def test_stress_can_only_tighten_and_never_grant_trade_permission():
    out = confirm_regime(
        confirmed_state="range",
        recent_predictions=[{"state": "stress", "confidence": 0.95}],
        min_confidence=0.65,
        confirmation_windows=2,
        emergency_stress_threshold=0.90,
    )
    assert out["state"] == "stress"
    assert out["can_change_trade_policy"] is False
    assert out["can_trigger_order"] is False
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_regime.py -q
```

Expected: 新增测试失败。

- [ ] **Step 3: 实现产物验证、概率映射和状态确认**

```python
def confirm_regime(
    *,
    confirmed_state: str,
    recent_predictions: list[dict],
    min_confidence: float,
    confirmation_windows: int,
    emergency_stress_threshold: float = 0.90,
) -> dict:
    current = confirmed_state if confirmed_state in {
        "risk_on", "range", "stress"
    } else "range"
    rows = [row for row in recent_predictions if isinstance(row, dict)]
    latest = rows[-1] if rows else {}
    candidate = latest.get("state")
    confidence = float(latest.get("confidence") or 0)
    changed = False
    reason = "hold"
    if candidate == "stress" and confidence >= emergency_stress_threshold:
        current, changed, reason = "stress", current != "stress", "stress_emergency"
    elif confidence >= min_confidence:
        tail = rows[-max(1, confirmation_windows):]
        if len(tail) >= confirmation_windows and all(
            row.get("state") == candidate
            and float(row.get("confidence") or 0) >= min_confidence
            for row in tail
        ):
            changed = candidate != current
            current = candidate
            reason = "confirmed_transition" if changed else "confirmed_hold"
    return {
        "schema_version": "adaptive-regime.v1",
        "state": current,
        "confidence": confidence,
        "changed": changed,
        "reason": reason,
        "mode": "shadow_only",
        "can_change_trade_policy": False,
        "can_trigger_order": False,
    }
```

加载 joblib 前必须校验固定目录、文件 SHA-256、schema 和特征顺序。

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_regime.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 检查点**

确认状态输出只包含 shadow 权限，不调用风险网关或下单模块。

---

### Task 7: 实现策略状态绩效路由

**Files:**
- Create: `quant/adaptive/routing.py`
- Test: `tests/test_adaptive_routing.py`

- [ ] **Step 1: 写隔离策略、权重上限和非 winner-take-all 测试**

```python
from quant.adaptive.routing import route_strategies


def strategies():
    return [
        {
            "strategy_id": "trend",
            "health_state": "healthy",
            "regime_metrics": {
                "risk_on": {"after_cost_score": 1.2, "samples": 80},
            },
        },
        {
            "strategy_id": "mean_reversion",
            "health_state": "healthy",
            "regime_metrics": {
                "risk_on": {"after_cost_score": 0.6, "samples": 80},
            },
        },
        {
            "strategy_id": "bad",
            "health_state": "quarantined",
            "regime_metrics": {
                "risk_on": {"after_cost_score": 9.0, "samples": 80},
            },
        },
    ]


def test_router_excludes_quarantined_and_caps_weights():
    out = route_strategies(
        strategies(),
        regime_probabilities={"risk_on": 0.8, "range": 0.1, "stress": 0.1},
        max_strategy_weight=0.50,
    )
    weights = {row["strategy_id"]: row["weight"] for row in out["strategy_weights"]}
    assert "bad" not in weights
    assert max(weights.values()) <= 0.50
    assert 0 < sum(weights.values()) < 1
    assert out["cash_weight"] > 0
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_routing.py -q
```

Expected: FAIL。

- [ ] **Step 3: 实现概率加权、样本收缩和现金保留**

```python
from __future__ import annotations


def _evidence_multiplier(samples: int) -> float:
    return min(1.0, max(0.0, int(samples)) / 60.0)


def route_strategies(
    strategies: list[dict],
    *,
    regime_probabilities: dict[str, float],
    max_strategy_weight: float,
) -> dict:
    scored = []
    for row in strategies:
        if row.get("health_state") == "quarantined":
            continue
        score = 0.0
        evidence = 0.0
        for regime in ("risk_on", "range", "stress"):
            metrics = (row.get("regime_metrics") or {}).get(regime) or {}
            probability = max(0.0, float(regime_probabilities.get(regime) or 0))
            multiplier = _evidence_multiplier(metrics.get("samples", 0))
            score += probability * max(
                0.0,
                float(metrics.get("after_cost_score") or 0),
            ) * multiplier
            evidence += probability * multiplier
        if score > 0:
            scored.append({
                "strategy_id": row["strategy_id"],
                "score": score,
                "evidence": evidence,
                "health_state": row.get("health_state", "watch"),
            })
    total_score = sum(row["score"] for row in scored)
    gross_budget = min(0.80, max(0.0, total_score / (1.0 + total_score)))
    weights = []
    remaining = gross_budget
    for row in sorted(scored, key=lambda item: item["score"], reverse=True):
        raw = gross_budget * row["score"] / max(total_score, 1e-12)
        weight = min(float(max_strategy_weight), raw, remaining)
        if weight > 0:
            weights.append({**row, "weight": round(weight, 6)})
            remaining -= weight
    used = sum(row["weight"] for row in weights)
    return {
        "schema_version": "adaptive-routing.v1",
        "strategy_weights": weights,
        "cash_weight": round(max(0.0, 1.0 - used), 6),
        "mode": "shadow_only",
        "can_trigger_order": False,
    }
```

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_routing.py -q
```

Expected: 通过。

- [ ] **Step 5: 增加性质检查**

增加参数化测试，覆盖空策略、全隔离、全零分数、状态概率缺失，始终满足：

```text
0 <= strategy weight <= 0.50
0 <= total strategy weight <= 0.80
cash_weight = 1 - total strategy weight
```

---

### Task 8: 实现四分之一凯利和确定性仓位裁剪

**Files:**
- Create: `quant/adaptive/sizing.py`
- Test: `tests/test_adaptive_sizing.py`

- [ ] **Step 1: 写凯利边界、硬上限和减仓通道测试**

```python
from quant.adaptive.sizing import (
    fractional_kelly_cap,
    size_target_weights,
)


def test_fractional_kelly_is_quarter_and_non_negative():
    assert fractional_kelly_cap(0.02, 0.04, 0.25) == 0.125
    assert fractional_kelly_cap(-0.02, 0.04, 0.25) == 0.0
    assert fractional_kelly_cap(0.02, 0.0, 0.25) == 0.0


def test_sizing_can_only_cut_proposed_weights():
    out = size_target_weights(
        proposed=[{"code": "600519", "target_weight": 0.20}],
        estimates={
            "600519": {
                "expected_after_cost_excess_return": 0.01,
                "variance": 0.04,
                "liquidity_cap": 0.08,
                "sample_count": 120,
            },
        },
        regime_gross_cap=0.60,
        adaptive_gross_cap=0.80,
        hard_max_position_pct=0.20,
        hard_max_gross_exposure=0.95,
        kelly_fraction=0.25,
    )
    assert out["sized_weights"][0]["target_weight"] <= 0.08
    assert out["sized_weights"][0]["target_weight"] <= 0.20


def test_invalid_estimate_blocks_new_position_but_not_sell():
    out = size_target_weights(
        proposed=[
            {"code": "600519", "target_weight": 0.10, "current_weight": 0.0},
            {"code": "000001", "target_weight": 0.0, "current_weight": 0.10},
        ],
        estimates={},
        regime_gross_cap=0.60,
        adaptive_gross_cap=0.80,
        hard_max_position_pct=0.20,
        hard_max_gross_exposure=0.95,
        kelly_fraction=0.25,
    )
    by_code = {row["code"]: row for row in out["sized_weights"]}
    assert by_code["600519"]["target_weight"] == 0
    assert by_code["000001"]["target_weight"] == 0
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_sizing.py -q
```

Expected: FAIL。

- [ ] **Step 3: 实现收缩估计和逐级上限**

```python
from __future__ import annotations

import math


def fractional_kelly_cap(
    expected_after_cost_excess_return: float,
    variance: float,
    fraction: float = 0.25,
) -> float:
    mu = float(expected_after_cost_excess_return)
    var = float(variance)
    if not math.isfinite(mu) or not math.isfinite(var) or mu <= 0 or var <= 0:
        return 0.0
    return max(0.0, mu / var * min(0.25, max(0.0, float(fraction))))


def size_target_weights(
    proposed: list[dict],
    *,
    estimates: dict[str, dict],
    regime_gross_cap: float,
    adaptive_gross_cap: float,
    hard_max_position_pct: float,
    hard_max_gross_exposure: float,
    kelly_fraction: float,
) -> dict:
    gross_cap = min(
        max(0.0, float(regime_gross_cap)),
        max(0.0, float(adaptive_gross_cap)),
        max(0.0, float(hard_max_gross_exposure)),
    )
    sized, cuts, total = [], [], 0.0
    for row in proposed:
        code = str(row.get("code") or "").split(".")[0]
        proposed_weight = max(0.0, float(row.get("target_weight") or 0))
        current_weight = max(0.0, float(row.get("current_weight") or 0))
        estimate = estimates.get(code) or {}
        if proposed_weight < current_weight:
            weight = proposed_weight
            reason = "risk_reducing_target"
        elif int(estimate.get("sample_count") or 0) < 60:
            weight = current_weight
            reason = "insufficient_samples"
        else:
            kelly_cap = fractional_kelly_cap(
                estimate.get("expected_after_cost_excess_return", 0),
                estimate.get("variance", 0),
                kelly_fraction,
            )
            weight = min(
                proposed_weight,
                kelly_cap,
                max(0.0, float(estimate.get("liquidity_cap") or 0)),
                max(0.0, float(hard_max_position_pct)),
                max(0.0, gross_cap - total),
            )
            reason = "adaptive_caps"
        weight = round(max(0.0, weight), 6)
        sized.append({**row, "code": code, "target_weight": weight})
        total += weight
        if weight < proposed_weight:
            cuts.append({
                "code": code,
                "from": proposed_weight,
                "to": weight,
                "reason": reason,
            })
    return {
        "schema_version": "adaptive-sizing.v1",
        "kelly_fraction": min(0.25, max(0.0, float(kelly_fraction))),
        "sized_weights": sized,
        "gross_exposure": round(total, 6),
        "cash_target_pct": round(max(0.0, 1.0 - total) * 100, 2),
        "cuts": cuts,
        "mode": "shadow_only",
        "can_increase_hard_limit": False,
        "can_trigger_order": False,
    }
```

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_sizing.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 增加随机边界测试**

固定随机种子生成100组权重和估计，断言：

```text
sized_weight <= proposed_weight
sized_weight <= hard_max_position_pct
sum(sized_weights) <= hard_max_gross_exposure
all weights >= 0
```

The caller must normalize the existing
`RiskConfig.max_gross_exposure_pct` value before calling
`size_target_weights()`: divide the percentage by `100.0`
(`95 -> 0.95`). The adaptive sizing module accepts only `0..1`
fractions and must not accept mixed percentage/fraction units.

---

### Task 9: 组合 P0-P3 控制器与运行状态

**Files:**
- Create: `quant/adaptive/control.py`
- Create: `scripts/adaptive_runner.py`
- Create: `scripts/adaptive_health.py`
- Test: `tests/test_adaptive_control.py`

- [ ] **Step 1: 写四种激活等级的行为测试**

```python
from quant.adaptive.control import run_adaptive_control


def inputs():
    return {
        "health": {"models": [], "summary": {"quarantined": 0}},
        "regime": {
            "state": "range",
            "confidence": 0.8,
            "probabilities": {"risk_on": 0.1, "range": 0.8, "stress": 0.1},
        },
        "routing": {"strategy_weights": [], "cash_weight": 1.0},
        "sizing": {
            "sized_weights": [{"code": "600519", "target_weight": 0.05}],
            "cuts": [{"code": "600519", "from": 0.1, "to": 0.05}],
        },
    }


def test_observe_never_applies_weights():
    out = run_adaptive_control(
        config={"activation_level": "observe"},
        proposed_weights=[{"code": "600519", "target_weight": 0.1}],
        precomputed=inputs(),
    )
    assert out["applied_weights"] is None


def test_size_shadow_preserves_original_decision():
    out = run_adaptive_control(
        config={"activation_level": "size_shadow"},
        proposed_weights=[{"code": "600519", "target_weight": 0.1}],
        precomputed=inputs(),
    )
    assert out["applied_weights"] is None
    assert out["shadow_weights"][0]["target_weight"] == 0.05


def test_paper_guarded_only_applies_cuts():
    out = run_adaptive_control(
        config={"activation_level": "paper_guarded"},
        proposed_weights=[{"code": "600519", "target_weight": 0.1}],
        precomputed=inputs(),
        approval={"approved": True, "scope": "paper_guarded"},
    )
    assert out["applied_weights"][0]["target_weight"] == 0.05
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_control.py -q
```

Expected: FAIL。

- [ ] **Step 3: 实现控制器和人工批准校验**

```python
from __future__ import annotations

from .activation import activation_permissions, normalize_adaptive_config


def run_adaptive_control(
    *,
    config: dict,
    proposed_weights: list[dict],
    precomputed: dict,
    approval: dict | None = None,
) -> dict:
    cfg = normalize_adaptive_config(config)
    permissions = activation_permissions(cfg["activation_level"])
    sizing = precomputed.get("sizing") or {}
    shadow_weights = sizing.get("sized_weights") or []
    approved = (
        isinstance(approval, dict)
        and approval.get("approved") is True
        and approval.get("scope") == "paper_guarded"
    )
    applied = None
    if permissions["apply_weight_cuts"] and approved:
        proposed_map = {
            str(row.get("code")): float(row.get("target_weight") or 0)
            for row in proposed_weights
        }
        if all(
            float(row.get("target_weight") or 0)
            <= proposed_map.get(str(row.get("code")), 0) + 1e-12
            for row in shadow_weights
        ):
            applied = shadow_weights
    return {
        "schema_version": "adaptive-control.v1",
        "activation_level": cfg["activation_level"],
        "health": precomputed.get("health"),
        "regime": precomputed.get("regime"),
        "routing": precomputed.get("routing"),
        "sizing": sizing,
        "shadow_weights": shadow_weights if permissions["publish_sizing"] else [],
        "applied_weights": applied,
        "mode": "paper_guarded" if applied is not None else "shadow_only",
        "can_trigger_order": False,
        "can_change_trade_policy": False,
    }
```

`scripts/adaptive_runner.py` 仅允许固定动作：

```text
status
config
set_activation
run_health
run_control
```

`set_activation` 需要本机控制授权；进入 `paper_guarded` 时要求请求包含
`confirm="ENABLE_PAPER_GUARDED"`，并写审计事件。

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_control.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 验证默认缓存状态**

首次运行 `status` 时应返回：

```json
{
  "activation_level": "observe",
  "mode": "shadow_only",
  "can_trigger_order": false
}
```

---

### Task 10: 接入 AI 闭环但默认不改变决策

**Files:**
- Modify: `scripts/ai_loop.py`
- Modify: `quant/ai/contracts.py`
- Modify: `scripts/ai_verifier.py`
- Test: `tests/test_adaptive_ai_loop.py`
- Test: `tests/test_ai_verifier.py`

- [ ] **Step 1: 写 observe、size_shadow 和 guarded 集成失败测试**

```python
def test_observe_adds_adaptive_context_without_changing_targets(monkeypatch):
    from scripts import ai_loop

    original = [{"code": "600519", "target_weight": 0.10}]
    adaptive = {
        "activation_level": "observe",
        "applied_weights": None,
        "shadow_weights": [],
        "can_trigger_order": False,
    }
    out = ai_loop._apply_adaptive_result(
        {"target_weights": original},
        adaptive,
    )
    assert out["target_weights"] == original
    assert out["adaptive"]["activation_level"] == "observe"


def test_guarded_rejects_weight_increase():
    from scripts import ai_loop

    original = [{"code": "600519", "target_weight": 0.10}]
    adaptive = {
        "activation_level": "paper_guarded",
        "applied_weights": [{"code": "600519", "target_weight": 0.15}],
    }
    out = ai_loop._apply_adaptive_result(
        {"target_weights": original},
        adaptive,
    )
    assert out["target_weights"] == original
    assert "adaptive_weight_increase_rejected" in out["reason_codes"]
```

- [ ] **Step 2: 运行测试并确认失败**

Run:

```powershell
python -m pytest tests\test_adaptive_ai_loop.py tests\test_ai_verifier.py -q
```

Expected: 新测试失败。

- [ ] **Step 3: 增加四个闭环步骤和决策裁剪**

在 `scripts/ai_loop.py` 增加小函数，不把逻辑继续堆入 `run_loop()`：

```python
def _apply_adaptive_result(decision: dict, adaptive: dict | None) -> dict:
    out = dict(decision)
    result = adaptive if isinstance(adaptive, dict) else {}
    out["adaptive"] = result
    out.setdefault("reason_codes", [])
    applied = result.get("applied_weights")
    if not isinstance(applied, list):
        return out
    original = {
        str(row.get("code")): float(row.get("target_weight") or 0)
        for row in out.get("target_weights") or []
        if isinstance(row, dict)
    }
    if any(
        float(row.get("target_weight") or 0)
        > original.get(str(row.get("code")), 0) + 1e-12
        for row in applied
        if isinstance(row, dict)
    ):
        out["reason_codes"].append("adaptive_weight_increase_rejected")
        return out
    out["target_weights"] = applied
    out["reason_codes"].append("adaptive_weight_cuts_applied")
    return out
```

运行顺序：

```text
Step 1.5 health
Step 1.6 regime
Step 6.65 routing
Step 6.75 sizing/control
```

`quant/ai/contracts.py` 允许可选 `adaptive` 对象，但 normalization 必须强制：

```python
adaptive["can_trigger_order"] = False
adaptive["can_change_trade_policy"] = False
```

`ai_verifier.py` 增加检查：

- applied weight 不得高于原权重。
- adaptive 不能新增原目标中不存在的代码。
- adaptive 权限字段必须为 false。
- `paper_guarded` 必须有批准审计引用。

- [ ] **Step 4: 运行测试**

Run:

```powershell
python -m pytest tests\test_adaptive_ai_loop.py tests\test_ai_verifier.py tests\test_decision_reader_binding.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 验证默认 observe 行为**

对相同输入分别在接入前基线和 `observe` 下运行决策 normalization，断言：

```text
target_weights 完全一致
trade_policy 完全一致
trade_allowed 完全一致
仅新增 adaptive 审计上下文
```

---

### Task 11: 接入模拟盘读取链路并保持 risk gateway 最终裁决

**Files:**
- Modify: `scripts/paper_runner.py`
- Modify: `scripts/paper/decision_reader.py`
- Modify: `scripts/paper_trader.py`
- Test: `tests/test_decision_reader_binding.py`
- Test: `tests/test_execution_reliability.py`
- Test: `tests/test_risk_gateway.py`

- [ ] **Step 1: 写受保护权重不绕过风险网关的测试**

```python
def test_adaptive_weights_still_pass_through_existing_risk_gateway(monkeypatch):
    decision = {
        "trade_policy": "normal",
        "trade_allowed": True,
        "target_weights": [{"code": "600519", "target_weight": 0.05}],
        "adaptive": {
            "activation_level": "paper_guarded",
            "can_trigger_order": False,
            "can_change_trade_policy": False,
        },
    }
    loaded = load_valid_decision(FakeCache({"ai:decision:latest": decision}))
    assert loaded["target_weights"][0]["target_weight"] == 0.05
    assert loaded["adaptive"]["can_trigger_order"] is False
```

保留并运行现有风险测试，确保超仓、T+1、涨跌停和熔断仍拒单。

- [ ] **Step 2: 运行测试并确认新增测试失败**

Run:

```powershell
python -m pytest tests\test_decision_reader_binding.py tests\test_execution_reliability.py tests\test_risk_gateway.py -q
```

- [ ] **Step 3: 扩展决策读取但不新增执行分支**

`decision_reader.py` 只保留经过 normalization 的 `adaptive` 字段：

```python
adaptive = decision.get("adaptive")
if isinstance(adaptive, dict):
    decision["adaptive"] = {
        **adaptive,
        "can_trigger_order": False,
        "can_change_trade_policy": False,
    }
```

不要在 `paper_trader.py` 新增“adaptive order”路径。它继续只读取最终
`target_weights`，并经过：

```text
portfolio_rebalancer
-> check_paper_order
-> quant.risk.gateway
-> execution runner
```

- [ ] **Step 4: 运行风险与执行回归**

Run:

```powershell
python -m pytest tests\test_decision_reader_binding.py tests\test_execution_reliability.py tests\test_execution_fill_risk.py tests\test_risk_gateway.py -q
```

Expected: 全部通过。

- [ ] **Step 5: 运行纸盘规则验证**

Run:

```powershell
python scripts\verify_paper_rules.py
```

Expected: 所有现有规则和新增 adaptive 边界通过。

---

### Task 12: 增加 API、激活控制和只读状态

**Files:**
- Create: `server/routes/adaptive.mjs`
- Modify: `server/router.mjs`
- Create: `scripts/adaptive_api_contract_tests.mjs`
- Test: `tests/test_adaptive_control.py`

- [ ] **Step 1: 写路由白名单失败契约**

```javascript
import assert from 'node:assert/strict';
import fs from 'node:fs';

const router = fs.readFileSync('server/router.mjs', 'utf8');
const route = fs.readFileSync('server/routes/adaptive.mjs', 'utf8');

assert(router.includes("'/api/adaptive'"));
assert(router.includes("'status'"));
assert(router.includes("'history'"));
assert(!router.includes("'/api/adaptive': new Set(['set_activation'"));
assert(route.includes("new PersistentRunner('adaptive_runner.py')"));
console.log('adaptive api contract tests passed');
```

- [ ] **Step 2: 运行契约并确认失败**

Run:

```powershell
node scripts\adaptive_api_contract_tests.mjs
```

Expected: FAIL，路由文件不存在。

- [ ] **Step 3: 实现 API**

`server/routes/adaptive.mjs`：

```javascript
import { PersistentRunner } from '../persistent_runner.mjs';
import { json, log, readBody } from '../http-utils.mjs';

const runner = new PersistentRunner('adaptive_runner.py');

export async function handleAdaptive(req, res) {
  const body = await readBody(req);
  log('INFO', `[Adaptive] action=${body.action || 'status'}`);
  try {
    const result = await runner.call(body, 30000);
    return json(res, result.success ? 200 : 400, result);
  } catch (error) {
    return json(res, 500, {
      success: false,
      error: `Adaptive runner error: ${error.message}`,
    });
  }
}
```

`server/router.mjs`：

```javascript
'/api/adaptive': new Set(['status', 'history']),
```

控制动作 `set_activation` 不进入只读集合，继续使用现有本机、JSON、token
授权。路由不得接受 shell、路径、模型文件名或任意命令。

- [ ] **Step 4: 运行契约和安全测试**

Run:

```powershell
node scripts\adaptive_api_contract_tests.mjs
node scripts\security_regression_tests.mjs
node scripts\lazy_runner_contract_tests.mjs
```

Expected: 全部通过。

- [ ] **Step 5: 手工 API 边界验证**

验证：

```text
status 无 token 可读
set_activation 无 token 返回 403
非法 activation_level 返回 400
paper_guarded 缺少确认短语返回 400
合法本机 token + 确认短语只更新激活配置，不执行交易
```

---

### Task 13: 增加策略页诊断和驾驶舱摘要

**Files:**
- Create: `components/AdaptiveControlPanel.tsx`
- Modify: `components/StrategyPanel.tsx`
- Modify: `components/DashboardPanel.tsx`
- Create: `scripts/adaptive_frontend_contract_tests.mjs`

- [ ] **Step 1: 写前端职责契约失败测试**

```javascript
import assert from 'node:assert/strict';
import fs from 'node:fs';

const strategy = fs.readFileSync('components/StrategyPanel.tsx', 'utf8');
const dashboard = fs.readFileSync('components/DashboardPanel.tsx', 'utf8');
const panel = fs.readFileSync('components/AdaptiveControlPanel.tsx', 'utf8');

assert(strategy.includes('AdaptiveControlPanel'));
assert(panel.includes('/api/adaptive'));
assert(panel.includes('模型健康'));
assert(panel.includes('市场状态'));
assert(panel.includes('策略路由'));
assert(panel.includes('仓位裁剪'));
assert(panel.includes('ENABLE_PAPER_GUARDED'));
assert(dashboard.includes('adaptive'));
assert(!dashboard.includes('ENABLE_PAPER_GUARDED'));
console.log('adaptive frontend contract tests passed');
```

- [ ] **Step 2: 运行契约并确认失败**

Run:

```powershell
node scripts\adaptive_frontend_contract_tests.mjs
```

Expected: FAIL。

- [ ] **Step 3: 实现策略页诊断组件**

`AdaptiveControlPanel.tsx` 必须提供：

- 当前激活等级和 `shadow-only` 状态。
- 健康模型统计和模型表。
- 三状态概率条。
- 策略路由权重。
- 原始权重和裁剪权重对比。
- 最近降级原因。
- 激活等级分段控件。
- `paper_guarded` 二次确认对话框，要求输入
  `ENABLE_PAPER_GUARDED`。

请求函数：

```tsx
async function adaptiveApi(body: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}/api/adaptive`, {
    method: 'POST',
    headers: jsonHeaders(),
    body: JSON.stringify(body),
  });
  const payload = await response.json();
  if (!response.ok || !payload?.success) {
    throw new Error(payload?.error || `HTTP ${response.status}`);
  }
  return payload.data;
}
```

在 `StrategyPanel` 增加 `adaptive` tab，渲染独立组件，不继续扩大主文件内部逻辑。

驾驶舱只增加紧凑摘要：

```text
自适应等级
当前状态和置信度
健康/观察/隔离模型数
最近降级原因
```

驾驶舱不提供激活按钮。

- [ ] **Step 4: 运行前端契约和构建**

Run:

```powershell
node scripts\adaptive_frontend_contract_tests.mjs
node scripts\control_surface_layout_contract_tests.mjs
npm run build
```

Expected: 契约通过，Vite build exit 0。

- [ ] **Step 5: 浏览器验证**

通过 in-app browser 检查：

- 1440px 桌面。
- 1024px 窄桌面。
- 390px 移动宽度。
- 标签文字不溢出。
- 表格可以横向滚动但页面本身无横向溢出。
- 驾驶舱没有重复模型详情。
- 默认明确显示 `observe / shadow-only`。
- 未输入确认短语时不能选择 `paper_guarded`。
- 控制台无 error。

---

### Task 14: 更新 README 和运行手册

**Files:**
- Modify: `README.md`
- Modify: `docs/QLIB_LOCAL_TRAINING.md`
- Reference: `docs/superpowers/specs/2026-07-20-adaptive-quant-control-plane-design.md`

- [ ] **Step 1: 增加 README 契约检查**

在 `scripts/adaptive_api_contract_tests.mjs` 中增加：

```javascript
const readme = fs.readFileSync('README.md', 'utf8');
assert(readme.includes('自适应控制平面'));
assert(readme.includes('observe'));
assert(readme.includes('paper_guarded'));
assert(readme.includes('四分之一凯利'));
assert(readme.includes('不能设置 trade_allowed=true'));
```

- [ ] **Step 2: 运行并确认失败**

Run:

```powershell
node scripts\adaptive_api_contract_tests.mjs
```

- [ ] **Step 3: 更新文档**

README 必须简要说明：

- P0-P3 职责。
- Qlib 与运行时数据库隔离。
- `promotion_state` 与 `health_state` 区别。
- 三状态模型和低置信度降级。
- 四分之一凯利只能裁剪。
- 四级激活权限。
- `paper_guarded` 不等于实盘。
- 常用状态和训练命令。

`docs/QLIB_LOCAL_TRAINING.md` 增加：

```powershell
# 安装/更新隔离依赖
powershell -ExecutionPolicy Bypass -File scripts\setup_qlib_env.ps1

# 提交市场状态训练任务
'{"action":"train_regime"}' |
  .venv-qlib\Scripts\python.exe scripts\qlib_runner.py

# 导出研究快照
.venv-qlib\Scripts\python.exe scripts\adaptive_snapshot.py
```

明确 `hmmlearn` 只存在于 Qlib 环境。

- [ ] **Step 4: 运行文档契约**

Run:

```powershell
node scripts\adaptive_api_contract_tests.mjs
```

Expected: 通过。

- [ ] **Step 5: 检查交接完整性**

确认后续模型只需按顺序阅读：

```text
README.md
设计规格
本实施计划
docs/QLIB_LOCAL_TRAINING.md
```

即可理解运行、边界、验证和激活流程。

---

### Task 15: 全量验证和默认安全状态

**Files:**
- Verify all files changed in Tasks 1-14

- [ ] **Step 1: 运行全部新增 Python 测试**

Run:

```powershell
python -m pytest `
  tests\test_adaptive_contracts.py `
  tests\test_adaptive_snapshot.py `
  tests\test_adaptive_drift.py `
  tests\test_adaptive_health.py `
  tests\test_adaptive_regime.py `
  tests\test_adaptive_routing.py `
  tests\test_adaptive_sizing.py `
  tests\test_adaptive_control.py `
  tests\test_adaptive_ai_loop.py -q
```

Expected: 全部通过。

- [ ] **Step 2: 运行 Qlib 隔离环境测试**

Run:

```powershell
.venv-qlib\Scripts\python.exe -m pytest `
  tests\test_adaptive_regime.py `
  tests\test_qlib_registry.py `
  tests\test_qlib_jobs.py `
  tests\test_qlib_runner_actions.py `
  tests\test_qlib_walk_forward.py -q
```

Expected: 全部通过。

- [ ] **Step 3: 运行核心交易安全回归**

Run:

```powershell
python -m pytest `
  tests\test_ai_verifier.py `
  tests\test_decision_reader_binding.py `
  tests\test_execution_reliability.py `
  tests\test_execution_fill_risk.py `
  tests\test_risk_gateway.py `
  tests\test_risk_config.py `
  tests\test_promotion.py `
  tests\test_ai_data_factor_adaptation.py -q
python scripts\verify_paper_rules.py
```

Expected: 全部通过。

- [ ] **Step 4: 运行 Node 契约、安全检查和构建**

Run:

```powershell
node scripts\adaptive_api_contract_tests.mjs
node scripts\adaptive_frontend_contract_tests.mjs
node scripts\control_surface_layout_contract_tests.mjs
node scripts\security_regression_tests.mjs
node scripts\lazy_runner_contract_tests.mjs
npm run build
```

Expected: 全部 exit 0；若只有现有 Vite chunk-size warning，记录为非阻塞警告。

- [ ] **Step 5: 运行只读/影子烟雾验证**

验证以下运行状态，不触发模拟交易：

```text
adaptive status.activation_level == observe
adaptive status.mode == shadow_only
adaptive can_trigger_order == false
ai:decision:latest 的 target_weights 在 observe 下与基线一致
Qlib snapshot 路径在 C:\Users\HYSHEN\XuanJiQuant\data\qlib
Qlib 代码未写 data\quant.db
```

- [ ] **Step 6: 浏览器最终验证**

打开：

```text
http://127.0.0.1:8888/
```

检查驾驶舱摘要和策略运行自适应页。不得在最终验证中：

- 保存 `paper_guarded`。
- 启动调度器。
- 执行模拟订单。
- 修改风险阈值。

- [ ] **Step 7: 生成实施结果记录**

在最终报告中列出：

- 修改文件。
- 新增测试数量和通过结果。
- Qlib 依赖状态。
- 默认激活等级。
- 浏览器验证结果。
- 未解决风险。
- `paper_guarded` 仍需人工批准的明确说明。

---

## 2. 任务依赖

```text
Task 1
  -> Task 2
  -> Task 3
  -> Task 4
  -> Task 5
  -> Task 6
  -> Task 7
  -> Task 8
  -> Task 9
  -> Task 10
  -> Task 11
  -> Task 12
  -> Task 13
  -> Task 14
  -> Task 15
```

Task 3 和 Task 5 可以在 Task 2 完成后并行，但 Task 9 之前必须全部完成。

## 3. 计划自检

- 设计规格 P0 对应 Task 2-4。
- 设计规格 P1 对应 Task 5-6。
- 设计规格 P2 对应 Task 7。
- 设计规格 P3 对应 Task 8。
- 激活和权限对应 Task 1、9、12。
- AI 闭环、verifier、risk gateway 对应 Task 10-11。
- 前端与审计入口对应 Task 12-13。
- README 和 Qlib 手册对应 Task 14。
- 回测、影子、安全和浏览器验证对应 Task 15。
- 计划中不存在未定义的实现占位。
