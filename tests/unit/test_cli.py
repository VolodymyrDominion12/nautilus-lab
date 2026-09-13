import pytest

from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.cli import main
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


def test_cli_paper_is_not_wired() -> None:
    assert main(["paper"]) == 1


def test_research_request_uses_settings_risk() -> None:
    cfg = Settings()
    request = research_request(cfg, bar_count=100)

    assert request.instrument_id == "ETH/USDT.SIM"
    assert request.bar_count == 100
    assert request.fast_ema == cfg.fast_ema
