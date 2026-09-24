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
    # Use synthetic bars: without a populated catalog the taker-flow Parquet may have
    # taker_buy_base_volume > bar.volume which causes validate_bar to raise.
    assert main(["paper", "--bars", "200", "--source", "synthetic"]) == 0


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


@pytest.mark.parametrize("robot", ["funding", "glft", "tri_scan"])
def test_cli_robot_without_adapter_fails_closed(robot: str) -> None:
    """A robot with no engine adapter must fail loudly instead of running regime."""
    assert main(["research", "--robot", robot, "--synthetic", "--bars", "200"]) == 1


def test_cli_meta_label_without_model_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta-label must not silently fall back to an untrained heuristic."""
    # The lab's own .env may point at a real trained booster; the fail-closed contract is
    # "no model path -> refuse", so clear both model paths instead of trusting ambient config.
    monkeypatch.setenv("META_LABEL_MODEL_PATH", "")
    monkeypatch.setenv("FORMULAIC_MODEL_PATH", "")
    assert main(["research", "--robot", "meta_label", "--synthetic", "--bars", "200"]) == 1


@pytest.mark.parametrize("folds", ["0", "-3"])
def test_cli_rejects_a_non_positive_fold_count(folds: str) -> None:
    """`--folds 0` used to fall through to the single split and report one window."""
    assert main(["research", "--synthetic", "--bars", "200", "--folds", folds]) == 1


def test_cli_multi_window_rejects_an_explicit_window() -> None:
    """Multi-window derives its own windows; mixing in explicit dates must fail closed."""
    assert (
        main(
            [
                "research",
                "--synthetic",
                "--bars",
                "600",
                "--folds",
                "2",
                "--is-start",
                "2024-01-01",
                "--is-end",
                "2024-06-01",
                "--oos-start",
                "2024-06-01",
                "--oos-end",
                "2024-12-01",
            ]
        )
        == 1
    )


@pytest.mark.parametrize("robot", ["regime", "ema", "pairs", "ml_obi"])
def test_cli_wired_robots_are_supported(robot: str) -> None:
    for item in RobotName:
        if item.value == robot:
            require_backtest_support(item)
            return
    raise AssertionError(f"unknown robot {robot}")
