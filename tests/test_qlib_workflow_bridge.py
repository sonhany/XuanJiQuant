from contextlib import contextmanager

import pytest

from quant.qlib.workflow_bridge import WorkflowRequest, run_workflow


class FakeRuntime:
    def __init__(self, calls, artifact_root, fail_at=""):
        self.calls = calls
        self.artifact_root = artifact_root
        self.fail_at = fail_at
        self.recorder = type(
            "Recorder",
            (),
            {"id": "recorder_1", "experiment_id": "experiment_1"},
        )()

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
            "metrics": {"Rank IC": 0.03},
            "artifacts": ["params.pkl", "pred.pkl"],
        }


def _request(tmp_path):
    return WorkflowRequest(
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


def test_workflow_generates_all_required_records(tmp_path):
    calls = []

    result = run_workflow(
        _request(tmp_path),
        runtime=FakeRuntime(calls, tmp_path / "artifacts"),
    )

    assert calls == [
        "qlib.init",
        "R.start",
        "model.fit",
        "R.save_objects",
        "SignalRecord.generate",
        "SigAnaRecord.generate",
        "PortAnaRecord.generate",
    ]
    assert result.status == "succeeded"
    assert result.recorder_id == "recorder_1"
    assert result.qlib_experiment_id == "experiment_1"
    assert result.metrics == {"Rank IC": 0.03}
    assert len(result.config_hash) == 64


def test_workflow_fails_when_required_record_generation_fails(tmp_path):
    calls = []

    with pytest.raises(RuntimeError, match="portfolio record failed"):
        run_workflow(
            _request(tmp_path),
            runtime=FakeRuntime(
                calls,
                tmp_path / "artifacts",
                fail_at="PortAnaRecord.generate",
            ),
        )

    assert calls[-1] == "PortAnaRecord.generate"
