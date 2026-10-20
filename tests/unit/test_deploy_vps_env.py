"""`deploy/vps.env.example` is the file a server `.env` is copied from (docs/26 §4).

Two defects made the template lie, and both were silent:

* it carried `MAKER_FEE`/`TAKER_FEE`, which are not `Settings` fields at all —
  pydantic's ``extra="ignore"`` drops them, so the server looked configured while the
  live session paid whatever ``SPOT_*`` said;
* it did not carry `REGIME_RANGE_ALLOW_SHORT`, whose code default is ``true`` (a range leg
  that shorts the upper band) — i.e. a VPS copied from the template traded a different
  rulebook than the H3 research run it was supposed to rehearse (docs/32 §2).

The assertions below keep both from coming back, and are also the reason the template is
allowed to leave research-only keys out: what is absent there is absent on purpose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _template() -> dict[str, str]:
    dotenv = pytest.importorskip("dotenv")
    raw = dotenv.dotenv_values(DEPLOY / "vps.env.example")
    return {key: ("" if value is None else value) for key, value in raw.items()}


def _settings_fields() -> set[str]:
    from nautilus_lab.infrastructure.settings import Settings

    return {name.lower() for name in Settings.model_fields}


def test_every_key_is_a_settings_field() -> None:
    """A typo in the template is not an error at runtime: it is a setting that never acts."""
    unknown = sorted({key.lower() for key in _template()} - _settings_fields())
    assert not unknown, f"vps.env.example sets keys Settings does not have: {unknown}"


def test_fee_aliases_are_gone_and_the_real_schedule_is_there() -> None:
    template = _template()
    assert "MAKER_FEE" not in template, "MAKER_FEE is not a Settings field; it is dropped"
    assert "TAKER_FEE" not in template, "TAKER_FEE is not a Settings field; it is dropped"
    for key in ("SPOT_MAKER_FEE", "SPOT_TAKER_FEE", "USDM_MAKER_FEE", "USDM_TAKER_FEE"):
        assert key in template, f"{key} is the fee the engine actually pays"


def test_the_regime_rulebook_that_reaches_live_sessions_is_spelled_out() -> None:
    """`true` is the code default, and it is a different rulebook than H3."""
    template = _template()
    assert template.get("REGIME_RANGE_ALLOW_SHORT") == "false"
    for key in ("REGIME_CONFIRMATION_BARS", "REGIME_MIN_HOLD_BARS"):
        assert key in template, key


def test_the_template_ships_no_secrets_and_no_llm_keys() -> None:
    template = _template()
    for key in ("EXCHANGE_API_KEY", "EXCHANGE_API_SECRET", "API_TOKEN"):
        assert template.get(key, "") == "", f"{key} must stay empty in a template"
    assert not [key for key in template if key.startswith("LLM_")], (
        "the offline LLM loop runs on the workstation; its key never belongs on a VPS"
    )


def test_the_template_boots_a_paper_server_with_a_persistent_portfolio() -> None:
    template = _template()
    assert template.get("LAB_ROLE") == "paper"
    assert template.get("TRADING_MODE") == "paper"
    # Without these the sessions live in memory and vanish on every deploy (docs/26 §8).
    for key in ("LIVE_PAPER_JOURNAL", "LIVE_PAPER_SESSIONS_DIR", "LIVE_PAPER_PORTFOLIO"):
        assert template.get(key), f"{key} is what makes the ledger survive a restart"
    # Same-origin bundle: the origin must be exactly the page's address, so the template
    # carries a sample and the operator replaces it (docs/26 §4).
    assert "API_ALLOWED_ORIGINS" in template
    assert "API_TOKEN" in template


def test_the_declared_portfolio_only_names_robots_the_terminal_can_build() -> None:
    yaml = pytest.importorskip("yaml")
    from nautilus_lab.api.paper_streamer import LIVE_PAPER_ROBOTS

    raw: Any = yaml.safe_load((DEPLOY / "paper_portfolio.yaml").read_text(encoding="utf-8"))
    declared = {str(session["robot"]) for session in raw["sessions"]}
    assert declared <= set(LIVE_PAPER_ROBOTS), (
        f"not live-capable: {sorted(declared - set(LIVE_PAPER_ROBOTS))}"
    )


def test_the_portfolio_has_a_hold_benchmark_for_each_traded_market() -> None:
    """Every non-`hold` session is compared with buy & hold on its own symbol+interval."""
    yaml = pytest.importorskip("yaml")

    raw: Any = yaml.safe_load((DEPLOY / "paper_portfolio.yaml").read_text(encoding="utf-8"))
    defaults = raw.get("defaults", {})
    benchmarks = {
        (str(s["symbol"]), str(s.get("interval", defaults.get("interval"))))
        for s in raw["sessions"]
        if str(s["robot"]) == "hold"
    }
    traded = {
        (str(s["symbol"]), str(s.get("interval", defaults.get("interval"))))
        for s in raw["sessions"]
        if str(s["robot"]) != "hold"
    }
    assert traded <= benchmarks, f"no `hold` benchmark for: {sorted(traded - benchmarks)}"
