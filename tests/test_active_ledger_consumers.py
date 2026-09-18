from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_current_account_consumers_use_only_the_f5_projection():
    consumers = {
        "scripts/risk_runner.py": "load_active_account_projection",
        "scripts/alert_runner.py": "load_active_account_projection",
        "scripts/tick_collector.py": "load_active_account_projection",
        "scripts/daily_report.py": "load_active_account_projection",
        "quant/data/sync_service.py": "load_active_account_projection",
    }
    for path, required in consumers.items():
        source = _source(path)
        assert required in source, f"{path} must use the F5 account projection"
        assert 'cache.get("execution:state")' not in source


def test_legacy_execution_state_remains_audit_only():
    workbench = _source("server/routes/workbench.mjs")
    execution_route = _source("server/routes/execution.mjs")
    assert "execution_runner.py" not in workbench
    assert "execution_runner.py" not in execution_route
    assert "f5_paper_runner.py" in execution_route


def test_daily_report_declares_f5_account_authority():
    source = _source("scripts/daily_report.py")
    assert '"account_source": "f5_ledger"' in source
    assert 'out["account_source"] = "f5_ledger"' in source


def test_full_validation_checks_the_active_f5_ledger_not_legacy_cache():
    source = _source("scripts/full_validation.py")
    assert "scripts.f5_paper_runner" in source
    assert "scripts.execution_runner" not in source
    assert 'cache.get("execution:state")' not in source
    assert "ledger_authority" in source
