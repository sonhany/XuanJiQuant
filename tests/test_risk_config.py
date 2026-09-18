from quant.risk.config import DEFAULT_RISK_CONFIG, load_risk_config, normalize_risk_config


class FakeCache:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key):
        return self.data.get(key)


def test_normalize_risk_config_maps_legacy_fields_and_clamps_values():
    cfg = normalize_risk_config({
        "position_size_pct": 0.4,
        "max_positions": 7,
        "risk": {
            "max_gross_exposure_pct": 120,
            "max_daily_turnover_pct": -3,
            "kill_switch": True,
        },
    })

    assert cfg["kill_switch"] is True
    assert cfg["max_position_pct"] == 0.4
    assert cfg["max_position_count"] == 7
    assert cfg["max_gross_exposure_pct"] == 100.0
    assert cfg["max_daily_turnover_pct"] == 0.0
    assert cfg["max_position_loss_pct"] == 8.0


def test_load_risk_config_uses_manifest_autonomous_and_paper_precedence():
    cache = FakeCache({
        "ai:manifest:metrics": {
            "max_single_position_pct": 0.18,
            "max_daily_turnover": 0.22,
        },
        "ai:autonomous:config": {
            "risk": {
                "max_position_pct": 0.16,
                "max_gross_exposure_pct": 88,
            },
        },
        "paper:config": {
            "risk": {
                "max_position_pct": 0.12,
                "max_daily_loss_pct": 4,
            },
        },
    })

    cfg = load_risk_config(cache)

    assert DEFAULT_RISK_CONFIG["max_position_pct"] == 0.2
    assert cfg["max_position_pct"] == 0.12
    assert cfg["max_gross_exposure_pct"] == 88.0
    assert cfg["max_daily_turnover_pct"] == 22.0
    assert cfg["max_daily_loss_pct"] == 4.0


def test_position_loss_limit_is_loaded_from_the_authoritative_risk_config():
    cache = FakeCache({
        "paper:config": {
            "risk": {
                "max_position_loss_pct": 6.5,
            },
        },
    })

    cfg = load_risk_config(cache)

    assert cfg["max_position_loss_pct"] == 6.5
    assert cfg["_hard_limits_source"] == "quant/risk/hard_limits.json"


def test_downstream_risk_snapshots_can_tighten_but_never_relax_global_limits():
    cache = FakeCache({
        "ai:autonomous:config": {
            "risk": {
                "max_position_pct": 0.10,
                "max_gross_exposure_pct": 80,
                "max_position_count": 8,
                "min_cash_buffer_pct": 5,
                "kill_switch": True,
            },
        },
        "paper:config": {
            "risk": {
                "max_position_pct": 0.20,
                "max_gross_exposure_pct": 95,
                "max_position_count": 10,
                "min_cash_buffer_pct": 2,
                "kill_switch": False,
            },
        },
    })

    cfg = load_risk_config(cache)

    assert cfg["max_position_pct"] == 0.10
    assert cfg["max_gross_exposure_pct"] == 80.0
    assert cfg["max_position_count"] == 8
    assert cfg["min_cash_buffer_pct"] == 5.0
    assert cfg["kill_switch"] is True


def test_explicit_execution_config_cannot_relax_cached_global_risk():
    cache = FakeCache({
        "ai:autonomous:config": {
            "risk": {
                "max_position_pct": 0.12,
                "max_daily_turnover_pct": 25,
            },
        },
    })

    cfg = load_risk_config(cache, {
        "risk": {
            "max_position_pct": 0.20,
            "max_daily_turnover_pct": 35,
        },
    })

    assert cfg["max_position_pct"] == 0.12
    assert cfg["max_daily_turnover_pct"] == 25.0
