from pathlib import Path

import pytest

from quant.qlib.paths import PathResolution, data_root, resolve_recorded_path


def test_default_root_is_active_project(monkeypatch):
    monkeypatch.delenv("QLIB_DATA_ROOT", raising=False)
    assert data_root() == Path(r"C:\Users\HYSHEN\XuanJiQuant\data\qlib")


@pytest.mark.parametrize(
    "value",
    [
        r"C:\XuanJiQuant-QlibData",
        r"C:\AlphaCouncil-QlibData",
        r"C:\Users\HYSHEN\AlphaCouncil2-AI\data\qlib",
    ],
)
def test_rejects_obsolete_and_frozen_active_roots(monkeypatch, value):
    monkeypatch.setenv("QLIB_DATA_ROOT", value)
    with pytest.raises(ValueError, match="活动 Qlib 数据根"):
        data_root()


def test_dedicated_override_outside_project_is_allowed(monkeypatch, tmp_path):
    dedicated = tmp_path / "dedicated-qlib"
    monkeypatch.setenv("QLIB_DATA_ROOT", str(dedicated))
    assert data_root() == dedicated.resolve()


def test_legacy_record_is_mapped_without_rewrite(monkeypatch, tmp_path):
    active = tmp_path / "qlib"
    target = active / "models" / "m1" / "model.pkl"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"model")
    monkeypatch.setenv("QLIB_DATA_ROOT", str(active))

    result = resolve_recorded_path(
        r"C:\AlphaCouncil-QlibData\models\m1\model.pkl"
    )

    assert result == PathResolution(
        recorded_path=r"C:\AlphaCouncil-QlibData\models\m1\model.pkl",
        resolved_path=str(target.resolve()),
        path_state="mapped_legacy",
        resolution_reason="旧外部数据根已映射到当前活动数据根",
    )


def test_missing_legacy_target_is_not_fabricated(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path / "qlib"))
    result = resolve_recorded_path(
        r"C:\AlphaCouncil-QlibData\models\missing.pkl"
    )
    assert result.path_state == "missing_historical"
    assert result.resolved_path == ""


def test_frozen_record_is_visible_but_not_resolved(monkeypatch, tmp_path):
    monkeypatch.setenv("QLIB_DATA_ROOT", str(tmp_path / "qlib"))
    result = resolve_recorded_path(
        r"C:\Users\HYSHEN\AlphaCouncil2-AI\data\qlib\models\old.pkl"
    )
    assert result.path_state == "rejected_frozen"
    assert result.resolved_path == ""
    assert result.recorded_path.endswith("old.pkl")
