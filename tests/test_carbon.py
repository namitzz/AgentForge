from agentforge.budget import BudgetManager
from agentforge.carbon import CarbonReport, CarbonSettings, estimate_energy_wh
from agentforge.config import Config


def test_energy_scales_with_calls_and_chars():
    s = CarbonSettings()
    assert estimate_energy_wh(0, 0, s) == 0.0
    # 4,000 chars = 1,000 input tokens -> 0.25 Wh; 1 call -> 1,000 output tokens -> 0.6 Wh
    assert abs(estimate_energy_wh(1, 4_000, s) - 0.85) < 1e-9


def test_saved_is_planned_minus_used():
    r = CarbonReport.from_budget(
        CarbonSettings(), ai_calls=1, chars_sent=4_000,
        planned_ai_calls=3, planned_chars_sent=12_000,
    )
    assert r.saved_calls == 2 and r.saved_chars == 8_000
    assert abs(r.used_co2e_g + r.saved_co2e_g - r.planned_co2e_g) < 1e-9
    assert round(r.saved_pct) == 67


def test_dry_run_saves_everything(base_config):
    b = BudgetManager(base_config)
    b.set_dry_run(True)
    b.record_planned(ai_calls=3, chars=8_200)
    snap = b.snapshot()
    carbon = snap.to_dict()["carbon"]
    assert carbon["used"]["co2e_g"] == 0
    assert carbon["saved"]["ai_calls"] == 3
    assert carbon["saved"]["co2e_g"] > 0
    assert carbon["saved_pct"] == 100.0
    assert "Estimated carbon:" in "\n".join(snap.estimate_summary())
    joined = "\n".join(snap.human_summary())
    assert "Carbon used:" in joined and "Carbon saved:" in joined


def test_config_overrides_and_disable():
    cfg = Config.from_dict({"carbon": {"grid_intensity_g_per_kwh": 100, "enabled": False}})
    assert cfg.carbon.grid_intensity_g_per_kwh == 100
    b = BudgetManager(cfg)
    b.record_call("claude", "planner", 1_000)
    snap = b.snapshot()
    assert snap.to_dict()["carbon"] is None
    assert "Carbon" not in "\n".join(snap.human_summary())


def test_cli_version_flag():
    # The plugin's slash commands detect the CLI with `agentforge --version`.
    from typer.testing import CliRunner
    from agentforge import __version__
    from agentforge.main import app
    res = CliRunner().invoke(app, ["--version"])
    assert res.exit_code == 0
    assert __version__ in res.output
