"""Buy and hold: the benchmark every paper robot is compared against.

A paper result without a benchmark on the same symbol, over the same bars and with the
same fees, answers nothing: "+3%" is a loss in a month ETH gained 8%. This robot asks
for a long position on every closed bar; the session turns that into one entry (the
position plan ignores BUY while already long) and sizes it with the whole account
instead of a risk fraction, with no stop and no target.
"""

from __future__ import annotations

from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.domain.signals import Signal, SignalSide

HOLD_ROBOT = "hold"


class BuyAndHold:
    def __init__(self, *, instrument_id: str) -> None:
        self.instrument_id = instrument_id

    def on_bar(self, bar: OhlcvBar) -> Signal:
        return Signal(
            instrument_id=self.instrument_id,
            side=SignalSide.BUY,
            bar_ts_utc=bar.ts_utc,
            reason="buy and hold benchmark",
        )
