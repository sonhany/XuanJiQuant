from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from quant.strategy.f4_alpha_contracts import build_v2_candidate_registry
from quant.strategy.f4_candidate_factory import canonical_payload_hash
from quant.strategy.f4_qlib_adapter import QlibAlphaUnavailable, fit_qlib_window
from quant.strategy.walk_forward import F4Window


def _candidate(alpha_id: str = "Q1"):
    return next(
        candidate
        for candidate in build_v2_candidate_registry()
        if candidate.alpha_spec.alpha_id == alpha_id
    )


def _window(window_id: str = "wf-01") -> F4Window:
    return F4Window(
        window_id=window_id,
        train_dates=tuple(pd.date_range("2020-01-02", periods=4, freq="B")),
        valid_dates=tuple(pd.date_range("2021-01-04", periods=2, freq="B")),
        test_dates=tuple(pd.date_range("2021-08-02", periods=2, freq="B")),
        purge_bars=20,
        embargo_bars=5,
    )


def _rows(segment: str) -> pd.DataFrame:
    dates = {
        "valid": ("2021-01-04", "2021-01-05"),
        "test": ("2021-08-02", "2021-08-03"),
    }[segment]
    return pd.DataFrame(
        [
            {"date": date, "instrument": instrument, "score": score}
            for date, score in zip(dates, (0.1, 0.2), strict=True)
            for instrument in ("SH600000", "SZ000001")
        ]
    )


def _qlib_series(segment: str) -> pd.Series:
    rows = _rows(segment)
    index = pd.MultiIndex.from_arrays(
        [pd.to_datetime(rows["date"]), rows["instrument"]],
        names=["datetime", "instrument"],
    )
    return pd.Series(rows["score"].to_numpy(), index=index, name="score")


class FakeWindowRuntime:
    def __init__(
        self,
        *,
        validation_rows: pd.DataFrame | pd.Series | None = None,
        expected_valid=None,
        fail_at: str = "",
        recorder_id_suffix: str = "",
        recorder_identity_suffix: str = "",
    ) -> None:
        self.validation_rows = (
            validation_rows.copy()
            if validation_rows is not None
            else _qlib_series("valid")
        )
        self.expected_valid = expected_valid
        self.fail_at = fail_at
        self.recorder_id_suffix = recorder_id_suffix
        self.recorder_identity_suffix = recorder_identity_suffix
        self.fit_segments: list[str] = []
        self.predicted_segments: list[str] = []
        self.expected_identity_segments: list[str] = []
        self.rule_fallback_calls = 0
        self.initialized = 0
        self.recorder_events: list[tuple[str, str, str]] = []
        self.active_recorder_id = ""

    def init_window(self, request):
        self.initialized += 1
        if self.fail_at == "dependency":
            raise ImportError("qlib missing")

    def build_dataset(self, config):
        return {"config": config}

    def build_model(self, config):
        return {"config": config, "fitted": False}

    @contextmanager
    def start_window_recorder(self, request, *, recorder_identity):
        recorder_id = (
            f"recorder-{request.window_id}-{request.candidate_id[:8]}"
            f"{self.recorder_id_suffix}"
        )
        actual_identity = f"{recorder_identity}{self.recorder_identity_suffix}"
        self.active_recorder_id = recorder_id
        self.recorder_events.append(("start", recorder_id, actual_identity))
        try:
            yield type(
                "WindowRecorder",
                (),
                {"id": recorder_id, "identity": actual_identity},
            )()
        finally:
            self.recorder_events.append(("finish", recorder_id, actual_identity))
            self.active_recorder_id = ""

    @contextmanager
    def resume_window_recorder(self, request, *, recorder_id, recorder_identity):
        self.active_recorder_id = recorder_id
        self.recorder_events.append(("resume", recorder_id, recorder_identity))
        try:
            yield type(
                "WindowRecorder",
                (),
                {"id": recorder_id, "identity": recorder_identity},
            )()
        finally:
            self.recorder_events.append(("finish", recorder_id, recorder_identity))
            self.active_recorder_id = ""

    def fit_model(self, model, dataset, *, segment):
        assert self.active_recorder_id
        self.fit_segments.append(segment)
        if self.fail_at == "fit":
            raise RuntimeError("fit failed")
        model["fitted"] = True

    def save_window_model(self, model, path):
        assert self.active_recorder_id
        path.write_bytes(b"deterministic-window-model")

    def load_window_model(self, path, config):
        assert self.active_recorder_id
        assert path.read_bytes() == b"deterministic-window-model"
        return {"config": config, "fitted": True}

    def predict_segment(self, model, dataset, *, segment):
        assert self.active_recorder_id
        self.predicted_segments.append(segment)
        if self.fail_at == f"dependency_predict_{segment}":
            raise ImportError("prediction dependency missing")
        if self.fail_at == f"predict_{segment}":
            raise RuntimeError("prediction failed")
        return (
            self.validation_rows.copy()
            if segment == "valid"
            else _qlib_series("test")
        )

    def expected_prediction_identities(self, dataset, *, segment):
        self.expected_identity_segments.append(segment)
        if segment == "valid" and self.expected_valid is not None:
            return tuple(self.expected_valid)
        rows = self.validation_rows if segment == "valid" else _qlib_series("test")
        if isinstance(rows.index, pd.MultiIndex):
            return tuple(rows.index.tolist())
        return tuple(zip(rows["date"], rows["instrument"], strict=True))


def _fit(tmp_path, *, runtime=None, candidate=None, window=None):
    return fit_qlib_window(
        candidate=candidate or _candidate(),
        window=window or _window(),
        provider_uri=tmp_path / "provider",
        artifact_root=tmp_path / "artifacts",
        runtime=runtime or FakeWindowRuntime(),
    )


def test_real_window_runtime_uses_project_local_sqlite_tracking_backend(
    tmp_path, monkeypatch
):
    mlflow = pytest.importorskip("mlflow")
    import qlib

    from quant.qlib.workflow_bridge import QlibRuntime, WindowWorkflowRequest

    provider = tmp_path / "data" / "qlib" / "qlib_bin" / "a_share_6y_daily"
    provider.mkdir(parents=True)
    calls = {}

    class FakeClient:
        def get_experiment_by_name(self, name):
            calls["lookup"] = name
            return None

        def create_experiment(self, name, *, artifact_location):
            calls["created"] = (name, artifact_location)

    def client(*, tracking_uri):
        calls["tracking_uri"] = tracking_uri
        return FakeClient()

    monkeypatch.setattr(mlflow.tracking, "MlflowClient", client)
    monkeypatch.setattr(qlib, "init", lambda **kwargs: calls.setdefault("qlib", kwargs))
    request = WindowWorkflowRequest(
        candidate_id="candidate-1",
        window_id="wf-01",
        alpha_spec_hash="a" * 64,
        provider_uri=provider,
        artifact_root=tmp_path / "artifacts",
        handler="Alpha158",
        model_type="LightGBM",
        seed=20260808,
        segments={
            "train": ("2020-01-02", "2020-12-31"),
            "valid": ("2021-01-04", "2021-06-30"),
            "test": ("2021-07-01", "2021-12-31"),
        },
        minimum_coverage=0.95,
        allowed_segment_dates=(
            ("valid", ("2021-01-04",)),
            ("test", ("2021-07-01",)),
        ),
    )

    QlibRuntime().init_window(request)

    database = (tmp_path / "data" / "qlib" / "mlflow.db").resolve()
    expected_uri = f"sqlite:///{database.as_posix()}"
    artifact_root = (
        tmp_path / "data" / "qlib" / "mlruns" / "xuanji-f4-window-v2"
    ).resolve()
    assert calls["tracking_uri"] == expected_uri
    assert calls["lookup"] == "xuanji-f4-window-v2"
    assert calls["created"] == (
        "xuanji-f4-window-v2",
        artifact_root.as_uri(),
    )
    assert calls["qlib"]["exp_manager"]["kwargs"] == {
        "uri": expected_uri,
        "default_exp_name": "xuanji-f4-window-v2",
    }


def _verified_lock(artifact) -> dict[str, object]:
    core = {
        "factory_run_id": "factory-v2-test",
        "window_id": artifact.window_id,
        "candidate_id": artifact.candidate_id,
        "alpha_spec_hash": artifact.alpha_spec_hash,
        "alpha_fit_hash": artifact.config_hash,
        "model_artifact_hash": artifact.model_sha256,
        "portfolio_policy_hash": "a" * 64,
        "validation_leaderboard_hash": "b" * 64,
        "selection_scope": "current_window_validation_only",
        "test_scope": "locked_winner_only",
    }
    return {
        **core,
        "lock_hash": canonical_payload_hash(core),
        "promotion_state": "research_only",
        "execution_authority": False,
    }


def test_qlib_window_fits_train_and_does_not_predict_test_before_lock(tmp_path):
    runtime = FakeWindowRuntime()

    artifact = _fit(tmp_path, runtime=runtime)

    assert runtime.fit_segments == ["train"]
    assert runtime.predicted_segments == ["valid"]
    assert runtime.expected_identity_segments == ["valid"]
    assert artifact.validation_coverage == pytest.approx(1.0)
    assert artifact.instruments == "market"
    assert len(artifact.alpha_spec_hash) == 64
    assert len(artifact.config_hash) == 64
    assert len(artifact.model_sha256) == 64
    assert len(artifact.validation_prediction_sha256) == 64
    assert artifact.promotion_state == "research_only"
    assert artifact.execution_authority is False
    assert artifact.recorder_id.startswith("recorder-wf-01-")
    assert artifact.recorder_identity
    assert runtime.recorder_events == [
        ("start", artifact.recorder_id, artifact.recorder_identity),
        ("finish", artifact.recorder_id, artifact.recorder_identity),
    ]
    assert artifact.model_path.is_relative_to((tmp_path / "artifacts").resolve())
    assert artifact.validation_prediction_path.is_relative_to(
        (tmp_path / "artifacts").resolve()
    )


def test_locked_test_prediction_verifies_lock_and_only_predicts_test(tmp_path):
    runtime = FakeWindowRuntime()
    artifact = _fit(tmp_path, runtime=runtime)
    lock = _verified_lock(artifact)

    result = artifact.predict_test(lock=lock, runtime=runtime)

    assert runtime.fit_segments == ["train"]
    assert runtime.predicted_segments == ["valid", "test"]
    assert runtime.expected_identity_segments == ["valid", "test"]
    assert result.segment == "test"
    assert result.coverage == pytest.approx(1.0)
    assert result.lock_hash == lock["lock_hash"]
    assert result.promotion_state == "research_only"
    assert result.execution_authority is False
    assert runtime.recorder_events[-2:] == [
        ("resume", artifact.recorder_id, artifact.recorder_identity),
        ("finish", artifact.recorder_id, artifact.recorder_identity),
    ]


def test_test_prediction_requires_verified_lock(tmp_path):
    runtime = FakeWindowRuntime()
    artifact = _fit(tmp_path, runtime=runtime)

    with pytest.raises(QlibAlphaUnavailable, match="qlib_test_lock_invalid"):
        artifact.predict_test(lock={"lock_hash": "forged"}, runtime=runtime)

    assert runtime.predicted_segments == ["valid"]
    assert runtime.expected_identity_segments == ["valid"]


@pytest.mark.parametrize(
    "missing_field",
    ["factory_run_id", "portfolio_policy_hash", "validation_leaderboard_hash"],
)
def test_self_consistent_lock_missing_required_spec9_field_is_rejected(
    tmp_path, missing_field
):
    runtime = FakeWindowRuntime()
    artifact = _fit(tmp_path, runtime=runtime)
    lock = _verified_lock(artifact)
    lock.pop(missing_field)
    core = {
        key: value
        for key, value in lock.items()
        if key not in {"lock_hash", "promotion_state", "execution_authority"}
    }
    lock["lock_hash"] = canonical_payload_hash(core)

    with pytest.raises(QlibAlphaUnavailable, match="qlib_test_lock_invalid"):
        artifact.predict_test(lock=lock, runtime=runtime)

    assert runtime.predicted_segments == ["valid"]


def test_test_prediction_rejects_model_file_tampering(tmp_path):
    runtime = FakeWindowRuntime()
    artifact = _fit(tmp_path, runtime=runtime)
    artifact.model_path.write_bytes(b"tampered")

    with pytest.raises(QlibAlphaUnavailable, match="qlib_model_hash_mismatch"):
        artifact.predict_test(lock=_verified_lock(artifact), runtime=runtime)

    assert runtime.predicted_segments == ["valid"]


def test_validation_prediction_identity_must_be_unique(tmp_path):
    duplicated = pd.concat([_rows("valid"), _rows("valid").iloc[[0]]], ignore_index=True)

    with pytest.raises(
        QlibAlphaUnavailable, match="qlib_prediction_identity_duplicate"
    ):
        _fit(tmp_path, runtime=FakeWindowRuntime(validation_rows=duplicated))


def test_standard_qlib_multiindex_series_is_normalized(tmp_path):
    artifact = _fit(
        tmp_path,
        runtime=FakeWindowRuntime(validation_rows=_qlib_series("valid")),
    )

    written = pd.read_csv(artifact.validation_prediction_path)
    assert list(written.columns) == ["date", "instrument", "score"]
    assert written["date"].tolist() == [
        "2021-01-04",
        "2021-01-04",
        "2021-01-05",
        "2021-01-05",
    ]


@pytest.mark.parametrize("column_name", ["score", "prediction"])
def test_standard_qlib_single_column_multiindex_dataframe_is_normalized(
    tmp_path, column_name
):
    frame = _qlib_series("valid").rename(column_name).to_frame()

    artifact = _fit(
        tmp_path,
        runtime=FakeWindowRuntime(validation_rows=frame),
    )

    assert artifact.validation_coverage == pytest.approx(1.0)


def test_qlib_multiindex_dataframe_rejects_ambiguous_value_columns(tmp_path):
    frame = _qlib_series("valid").to_frame()
    frame["other"] = frame["score"]

    with pytest.raises(QlibAlphaUnavailable, match="qlib_prediction_payload_invalid"):
        _fit(tmp_path, runtime=FakeWindowRuntime(validation_rows=frame))


@pytest.mark.parametrize(
    "index_names", [(None, None), ("date", "symbol"), ("instrument", "datetime")]
)
def test_qlib_prediction_rejects_anonymous_or_wrong_multiindex(
    tmp_path, index_names
):
    series = _qlib_series("valid")
    series.index = series.index.set_names(index_names)

    with pytest.raises(QlibAlphaUnavailable, match="qlib_prediction_payload_invalid"):
        _fit(tmp_path, runtime=FakeWindowRuntime(validation_rows=series))


def test_validation_coverage_uses_expected_eligible_identity_denominator(tmp_path):
    rows = _rows("valid").iloc[:3].copy()
    expected = tuple(zip(_rows("valid")["date"], _rows("valid")["instrument"], strict=True))

    with pytest.raises(
        QlibAlphaUnavailable,
        match=r"qlib_prediction_coverage_insufficient.*actual=0\.750000.*required=0\.950000",
    ):
        _fit(
            tmp_path,
            runtime=FakeWindowRuntime(
                validation_rows=rows,
                expected_valid=expected,
            ),
        )


def test_validation_identity_date_must_belong_to_bound_window_segment(tmp_path):
    outside = _rows("valid")
    outside["date"] = ["1999-01-04", "1999-01-04", "1999-01-05", "1999-01-05"]

    with pytest.raises(
        QlibAlphaUnavailable, match="qlib_prediction_segment_identity_invalid"
    ):
        _fit(tmp_path, runtime=FakeWindowRuntime(validation_rows=outside))


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_validation_prediction_is_rejected(tmp_path, bad_score):
    rows = _rows("valid")
    rows.loc[0, "score"] = bad_score

    with pytest.raises(QlibAlphaUnavailable, match="qlib_prediction_nonfinite"):
        _fit(tmp_path, runtime=FakeWindowRuntime(validation_rows=rows))


def test_prediction_failure_does_not_call_rule_fallback(tmp_path):
    runtime = FakeWindowRuntime(fail_at="predict_valid")

    with pytest.raises(QlibAlphaUnavailable, match="qlib_prediction_failed"):
        _fit(tmp_path, runtime=runtime)

    assert runtime.rule_fallback_calls == 0
    assert runtime.predicted_segments == ["valid"]


def test_validation_dependency_failure_uses_dependency_reason_code(tmp_path):
    runtime = FakeWindowRuntime(fail_at="dependency_predict_valid")

    with pytest.raises(QlibAlphaUnavailable, match="qlib_dependency_unavailable"):
        _fit(tmp_path, runtime=runtime)

    assert runtime.rule_fallback_calls == 0


@pytest.mark.parametrize(
    ("fail_at", "reason_code"),
    [
        ("dependency", "qlib_dependency_unavailable"),
        ("fit", "qlib_training_failed"),
    ],
)
def test_dependency_and_training_failures_have_stable_codes(
    tmp_path, fail_at, reason_code
):
    with pytest.raises(QlibAlphaUnavailable, match=reason_code):
        _fit(tmp_path, runtime=FakeWindowRuntime(fail_at=fail_at))


def test_only_preregistered_qlib_candidate_is_accepted(tmp_path):
    candidate = _candidate()
    forged = replace(
        candidate,
        alpha_spec=replace(candidate.alpha_spec, seed=candidate.alpha_spec.seed + 1),
    )
    runtime = FakeWindowRuntime()

    with pytest.raises(QlibAlphaUnavailable, match="qlib_candidate_unregistered"):
        _fit(tmp_path, runtime=runtime, candidate=forged)

    assert runtime.initialized == 0


def test_artifact_path_cannot_escape_root_through_window_identity(tmp_path):
    runtime = FakeWindowRuntime()

    with pytest.raises(QlibAlphaUnavailable, match="qlib_artifact_path_invalid"):
        _fit(tmp_path, runtime=runtime, window=_window("../escape"))

    assert runtime.initialized == 0


@pytest.mark.parametrize(
    "target_name", ["validation_predictions.csv", "fit_manifest.json"]
)
def test_preexisting_artifact_symlink_cannot_escape_root(tmp_path, target_name):
    candidate = _candidate()
    artifact_root = tmp_path / "artifacts"
    run_root = artifact_root / "wf-01" / candidate.candidate_id
    run_root.mkdir(parents=True)
    outside = tmp_path / f"outside-{target_name}"
    outside.write_text("do-not-overwrite", encoding="utf-8")
    link = run_root / target_name
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(QlibAlphaUnavailable, match="qlib_artifact_path_invalid"):
        _fit(
            tmp_path,
            runtime=FakeWindowRuntime(),
            candidate=candidate,
        )

    assert outside.read_text(encoding="utf-8") == "do-not-overwrite"


@pytest.mark.parametrize(
    "target_name", ["validation_predictions.csv", "fit_manifest.json"]
)
def test_resolved_artifact_target_escape_is_rejected_without_symlink_privilege(
    tmp_path, monkeypatch, target_name
):
    candidate = _candidate()
    artifact_root = (tmp_path / "artifacts").resolve()
    target = Path(
        str(artifact_root / "wf-01" / candidate.candidate_id / target_name)
    )
    outside = (tmp_path / f"outside-{target_name}").resolve()
    real_resolve = Path.resolve

    def resolve_with_escape(path, *args, **kwargs):
        lexical = Path(str(path))
        if lexical == target:
            return outside
        return real_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve_with_escape)

    with pytest.raises(QlibAlphaUnavailable, match="qlib_artifact_path_invalid"):
        _fit(tmp_path, runtime=FakeWindowRuntime(), candidate=candidate)


def test_each_window_uses_an_independent_recorder_identity(tmp_path):
    runtime = FakeWindowRuntime()
    first = _fit(tmp_path, runtime=runtime, window=_window("wf-01"))
    second = _fit(tmp_path, runtime=runtime, window=_window("wf-02"))

    assert first.recorder_id != second.recorder_id
    assert first.recorder_identity != second.recorder_identity
    assert [event[0] for event in runtime.recorder_events] == [
        "start",
        "finish",
        "start",
        "finish",
    ]


def test_runtime_recorder_id_is_audit_only_and_not_in_deterministic_config_hash(
    tmp_path,
):
    first = fit_qlib_window(
        candidate=_candidate(),
        window=_window(),
        provider_uri=tmp_path / "provider",
        artifact_root=tmp_path / "artifacts-a",
        runtime=FakeWindowRuntime(recorder_id_suffix="-random-a"),
    )
    second = fit_qlib_window(
        candidate=_candidate(),
        window=_window(),
        provider_uri=tmp_path / "provider",
        artifact_root=tmp_path / "artifacts-b",
        runtime=FakeWindowRuntime(recorder_id_suffix="-random-b"),
    )

    assert first.recorder_id != second.recorder_id
    assert first.recorder_identity == second.recorder_identity
    assert first.config_hash == second.config_hash
    assert _verified_lock(first)["alpha_fit_hash"] == _verified_lock(second)[
        "alpha_fit_hash"
    ]
    first_manifest = json.loads(first.fit_manifest_path.read_text(encoding="utf-8"))
    second_manifest = json.loads(second.fit_manifest_path.read_text(encoding="utf-8"))
    assert first_manifest["recorder_id"] == first.recorder_id
    assert second_manifest["recorder_id"] == second.recorder_id


def test_runtime_recorder_identity_must_match_stable_request_identity(tmp_path):
    with pytest.raises(QlibAlphaUnavailable, match="qlib_recorder_identity_invalid"):
        _fit(
            tmp_path,
            runtime=FakeWindowRuntime(recorder_identity_suffix="-forged"),
        )


def test_repeated_fit_uses_stable_identity_and_atomic_files(tmp_path):
    first = _fit(tmp_path, runtime=FakeWindowRuntime())
    second = _fit(tmp_path, runtime=FakeWindowRuntime())

    assert first.config_hash == second.config_hash
    assert first.model_sha256 == second.model_sha256
    assert (
        first.validation_prediction_sha256
        == second.validation_prediction_sha256
    )
    assert not list((tmp_path / "artifacts").rglob("*.tmp"))
