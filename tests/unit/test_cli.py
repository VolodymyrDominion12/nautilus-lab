import pytest

from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName, require_backtest_support
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.cli import main, parse_utc
from nautilus_lab.interfaces.composition import research_request


def test_settings_default_mode_is_research(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    monkeypatch.delenv("LIVE_ENABLED", raising=False)
    cfg = Settings()

    assert cfg.trading_mode is TradingMode.RESEARCH
    assert cfg.live_enabled is False
    assert cfg.risk_limits().risk_per_trade == cfg.risk_per_trade


def test_cli_live_fails_closed() -> None:
    assert main(["live"]) == 1


def test_cli_paper_logs_hypothetical_orders() -> None:
    assert main(["paper", "--bars", "200"]) == 0


def test_research_request_uses_settings_risk() -> None:
    cfg = Settings()
    request = research_request(cfg, bar_count=100)

    assert request.instrument_id == "ETH/USDT.SIM"
    assert request.bar_count == 100
    assert request.robot is RobotName.REGIME
    assert request.fast_ema == cfg.fast_ema
    assert request.source is BarOrigin.CATALOG
    assert "HOUR" in request.bar_type


def test_parse_utc_date_is_midnight_utc() -> None:
    parsed = parse_utc("2024-06-01")
    assert parsed.tzinfo is not None
    assert parsed.hour == 0


def test_cli_walk_forward_dates_must_be_complete() -> None:
    assert main(["research", "--is-start", "2024-01-01"]) == 1


def test_cli_research_synthetic_runs() -> None:
    assert main(["research", "--synthetic", "--bars", "200"]) == 0


def test_cli_research_synthetic_tearsheet(tmp_path: pytest.TempPathFactory) -> None:
    t_path = str(tmp_path) + "/tearsheet.html"
    assert main(["research", "--synthetic", "--bars", "200", "--tearsheet", t_path]) == 0


def test_cli_research_synthetic_optuna() -> None:
    assert (
        main(
            [
                "research",
                "--synthetic",
                "--bars",
                "800",
                "--walk-forward",
                "--optuna",
                "--trials",
                "2",
                "--notify",
            ]
        )
        == 0
    )


def test_cli_scan_triangular() -> None:
    assert main(["scan", "--triangular"]) == 0


def test_cli_scan_missing_flag_fails() -> None:
    assert main(["scan"]) == 1


@pytest.mark.parametrize("robot", ["funding", "ml_obi", "glft", "tri_scan"])
def test_cli_robot_without_adapter_fails_closed(robot: str) -> None:
    """A robot with no engine adapter must fail loudly instead of running regime."""
    assert main(["research", "--robot", robot, "--synthetic", "--bars", "200"]) == 1


@pytest.mark.parametrize("robot", ["regime", "ema", "pairs"])
def test_cli_wired_robots_are_supported(robot: str) -> None:
    for item in RobotName:
        if item.value == robot:
            require_backtest_support(item)
            return
    raise AssertionError(f"unknown robot {robot}")
