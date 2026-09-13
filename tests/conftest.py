from decimal import Decimal

import pytest

from nautilus_lab.domain.risk import RiskLimits


@pytest.fixture
def default_limits() -> RiskLimits:
    return RiskLimits(
        risk_per_trade=Decimal("0.005"),
        stop_pct=Decimal("0.01"),
        max_daily_loss=Decimal("0.02"),
        max_drawdown=Decimal("0.06"),
    )
