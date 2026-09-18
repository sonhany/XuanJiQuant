from pathlib import Path


def test_environment_contract_uses_isolated_python(tmp_path):
    from quant.qlib.environment import inspect_environment

    venv_dir = tmp_path / ".venv-qlib"
    warehouse = tmp_path / "warehouse"
    result = inspect_environment(venv_dir=venv_dir, data_root=warehouse)

    assert result["system_python_required"] == "3.11"
    assert result["inherits_system_site_packages"] is False
    assert result["venv_dir"] == str(venv_dir.resolve())
    assert result["data_root"] == str(warehouse.resolve())


def test_environment_reports_expected_python311_path():
    from quant.qlib.environment import SYSTEM_PYTHON

    assert SYSTEM_PYTHON == Path(
        r"C:\Users\HYSHEN\AppData\Local\Programs\Python\Python311\python.exe"
    )


def test_qlib_environment_declares_akshare():
    source = Path("requirements-qlib.txt").read_text(encoding="utf-8").lower()

    assert "akshare==1.18.60" in source


def test_setup_script_imports_and_reports_hmmlearn():
    source = Path("scripts/setup_qlib_env.ps1").read_text(
        encoding="utf-8"
    ).lower()

    assert "import qlib, lightgbm, pandas, pyarrow, hmmlearn" in source
    assert "import xgboost" in source
    assert "'hmmlearn':hmmlearn.__version__" in source
    assert "'xgboost':xgboost.__version__" in source
