from __future__ import annotations

import pytest

from nautilus_lab.domain.errors import InvalidRiskError
from nautilus_lab.domain.risk_overlay import RiskOverlay
from nautilus_lab.domain.stop_cooldown import StopCooldown


def test_cooldown_blocks_entries_for_exactly_n_bars() -> None:
    cooldown = StopCooldown(bars=3)
    assert not cooldown.active
    cooldown.trip()
    blocked = []
    for _ in range(5):
        blocked.append(cooldown.active)  # what the entry gate sees on this bar
        cooldown.tick()
    assert blocked == [True, True, True, False, False]


def test_zero_bars_never_blocks() -> None:
    cooldown = StopCooldown(bars=0)
    cooldown.trip()
    assert not cooldown.active


def test_a_new_stop_restarts_the_window() -> None:
    cooldown = StopCooldown(bars=2)
    cooldown.trip()
    cooldown.tick()
    cooldown.trip()
    assert cooldown.remaining == 2


def test_negative_bars_are_rejected() -> None:
    with pytest.raises(InvalidRiskError, match="stop_cooldown_bars"):
        StopCooldown(bars=-1)
    with pytest.raises(InvalidRiskError, match="stop_cooldown_bars"):
        RiskOverlay(stop_cooldown_bars=-1)


def test_overlay_repr_is_unchanged_when_cooldown_is_off() -> None:
    # repr feeds the preregistration hash: the default must not move it.
    assert "stop_cooldown" not in repr(RiskOverlay())
    assert "stop_cooldown" not in repr(RiskOverlay(use_chandelier_stop=True))
    assert "stop_cooldown_bars=6" in repr(RiskOverlay(stop_cooldown_bars=6))


def test_settings_wiring() -> None:
    from nautilus_lab.infrastructure.settings import Settings

    settings = Settings(stop_cooldown_bars=12)
    assert settings.risk_overlay().stop_cooldown_bars == 12
    assert Settings().risk_overlay().stop_cooldown_bars == 0
