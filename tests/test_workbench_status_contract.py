from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _compose(payload: dict) -> dict:
    script = f"""
import {{ composeWorkbenchStatus }} from './server/routes/workbench.mjs';
console.log(JSON.stringify(composeWorkbenchStatus({json.dumps(payload, ensure_ascii=False)})));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout)


def _compose_fast(payload: dict) -> dict:
    script = f"""
import {{ composeFastWorkbenchStatus }} from './server/routes/workbench.mjs';
console.log(JSON.stringify(composeFastWorkbenchStatus({json.dumps(payload, ensure_ascii=False)})));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout)


def test_router_exposes_only_read_only_workbench_status():
    source = (ROOT / "server" / "router.mjs").read_text(encoding="utf-8")
    assert "handleWorkbench" in source
    assert "'/api/workbench': new Set(['status'])" in source
    assert "'/api/workbench': handleWorkbench" in source


def test_workbench_reads_single_f5_ledger_risk_health_alerts_and_context():
    source = (ROOT / "server" / "routes" / "workbench.mjs").read_text(encoding="utf-8")
    assert "execution_runner.py" not in source
    assert "risk_runner.py" in source
    assert "alert_runner.py" in source
    assert "paper_runner.py" in source
    assert "f5_paper_runner.py" in source
    assert "{ action: 'account' }" in source
    assert "strategy_runner.py" in source
    assert "{ action: 'research_selection' }" in source


def test_composed_status_is_deterministic_and_exposes_active_intraday_simulation():
    status = _compose({
        "activeLedger": {
            "ledger_authority": "f5",
            "account": {"total_assets": 1_020_000, "total_pnl_pct": 2.0},
            "positions": [{"symbol": "600000", "market_value": 100_000}],
            "equity_history": [{"date": "2026-08-12", "equity": 1_020_000}],
        },
        "risk": {"max_drawdown_pct": -2.0, "volatility_pct": 20.0, "concentration_pct": 30.0},
        "alerts": {"business_active": 0, "business_critical_active": 0},
        "health": {"overall": "healthy"},
        "globalContext": {
            "sentiment": {
                "sentiment_score": 72,
                "confidence": 0.5,
                "sources": [{"source": "cboe", "status": "live"}],
            }
        },
        "paperStatus": {
            "enabled": True,
            "kill_switch": False,
            "execution_mode": "paper_intraday",
            "paper_execution_authority": True,
            "latest_run": {"status": "completed"},
        },
        "targetPortfolio": {
            "selection_date": "20260825",
            "selection_status": "experimental_research_portfolio",
            "positions": [
                {"code": "600000", "name": "浦发银行", "target_weight": 0.095}
            ],
            "promotion_state": "research_only",
            "execution_authority": False,
        },
    })

    assert status["account"]["total_assets"] == 1_020_000
    assert status["positions"][0]["symbol"] == "600000"
    assert status["ledger_authority"] == "f5"
    assert status["risk"]["level"] == "low"
    assert status["overall_risk"]["source"] == "deterministic_risk_summary"
    assert status["sentiment"]["sentiment_regime"] == "positive"
    assert status["automatic_execution"] == {
        "enabled": True,
        "reason": "completed",
        "label": "盘中自动模拟交易已启用",
    }
    assert status["trade_permission"]["allowed"] is True
    assert status["trade_permission"]["scope"] == "experimental_paper"
    assert status["trade_permission"]["live_execution_authority"] is False
    assert status["target_portfolio"]["positions"][0]["name"] == "浦发银行"
    assert status["target_portfolio"]["execution_authority"] is False


def test_prepared_experimental_run_reports_intraday_automation_ready_before_first_fill():
    status = _compose({
        "paperStatus": {
            "enabled": True,
            "kill_switch": False,
            "execution_mode": "paper_daily",
            "paper_execution_authority": True,
            "execution_lane": "experimental_paper",
            "latest_run": {
                "status": "prepared",
                "execution_lane": "experimental_paper",
                "intended_session": "20260821",
            },
        },
    })

    assert status["automatic_execution"] == {
        "enabled": True,
        "reason": "prepared",
        "label": "盘中自动模拟交易已启用",
    }
    assert status["trade_permission"]["allowed"] is True
    assert status["trade_permission"]["scope"] == "experimental_paper"


def test_current_readiness_takes_priority_over_stale_historical_run():
    status = _compose({
        "paperStatus": {
            "enabled": True,
            "kill_switch": False,
            "execution_mode": "paper_intraday",
            "execution_lane": "experimental_paper",
            "reason_code": "outside_intraday_window",
            "paper_execution_authority": False,
            "latest_run": {"status": "blocked", "execution_lane": "blocked"},
            "current_readiness": {
                "execution_lane": "experimental_paper",
                "reason_code": "outside_intraday_window",
                "paper_execution_ready": True,
                "market_window_allowed": False,
            },
        },
    })

    assert status["automatic_execution"]["enabled"] is True
    assert status["automatic_execution"]["reason"] == "outside_intraday_window"
    assert status["trade_permission"]["scope"] == "experimental_paper"


def test_risk_thresholds_are_explicit_and_do_not_grant_trade_authority():
    medium = _compose({"risk": {"volatility_pct": 31}, "alerts": {}})
    high = _compose({"risk": {"concentration_pct": 70}, "alerts": {}})

    assert medium["risk"]["level"] == "medium"
    assert high["risk"]["level"] == "high"
    assert medium["trade_permission"]["allowed"] is False
    assert high["trade_permission"]["allowed"] is False


def test_workbench_contains_no_agent_control_plane_vocabulary():
    source = (ROOT / "server" / "routes" / "workbench.mjs").read_text(encoding="utf-8").lower()
    for token in ("agent_runtime", "agent_control", "ai_scheduler", "waiting_agent"):
        assert token not in source


def test_moving_f5_snapshot_keeps_risk_when_ledger_positions_and_equity_match():
    status = _compose_fast(
        {
            "activeLedger": {
                "ledger_authority": "f5",
                "ledger": "data/paper/f5_ledger.db",
                "account": {
                    "market_snapshot_id": "account-snapshot",
                    "total_equity": 1_000_000,
                    "position_count": 10,
                    "valuation_as_of": "2026-09-10T09:43:10+08:00",
                },
                "positions": [{"code": f"{index:06d}"} for index in range(10)],
            },
            "risk": {
                "market_snapshot_id": "risk-snapshot",
                "ledger_authority": "f5",
                "ledger": "data/paper/f5_ledger.db",
                "total_equity": 1_000_500,
                "position_count": 10,
                "calculated_at": "2026-09-10T09:43:14+08:00",
                "volatility_pct": 20,
            },
            "slow": {},
        }
    )

    assert status["risk"] is not None
    assert status["overall_risk"]["level"] == "low"
    assert status["freshness"]["consistent"] is True


def test_moving_f5_snapshot_rejects_material_equity_drift():
    status = _compose_fast(
        {
            "activeLedger": {
                "ledger_authority": "f5",
                "ledger": "data/paper/f5_ledger.db",
                "account": {
                    "market_snapshot_id": "account-snapshot",
                    "total_equity": 1_000_000,
                    "position_count": 10,
                },
                "positions": [{"code": f"{index:06d}"} for index in range(10)],
            },
            "risk": {
                "market_snapshot_id": "risk-snapshot",
                "ledger_authority": "f5",
                "ledger": "data/paper/f5_ledger.db",
                "total_equity": 1_010_000,
                "position_count": 10,
                "volatility_pct": 20,
            },
            "slow": {},
        }
    )

    assert status["risk"] is None
    assert status["freshness"]["consistent"] is False
