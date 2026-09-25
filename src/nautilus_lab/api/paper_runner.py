from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from typing import Any, TextIO, cast

from nautilus_lab.application.dtos import PaperSessionReport
from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_paper import require_paper_support
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.interfaces.composition import paper_request, paper_use_case, settings


@dataclass(frozen=True, slots=True)
class PaperRunConfig:
    robot: str = "regime"
    bars: int = 2000
    source: str = "catalog"


class _Tee(io.TextIOBase):
    def __init__(self, original: TextIO, buffer: io.StringIO) -> None:
        self._original = original
        self._buffer = buffer

    def write(self, text: str) -> int:
        self._original.write(text)
        self._buffer.write(text)
        return len(text)

    def flush(self) -> None:
        self._original.flush()


def session_payload(report: PaperSessionReport) -> dict[str, Any]:
    """JSON body for the dashboard. Decimals stay strings; no float rounding."""
    return {
        "is_finished": True,
        "is_error": False,
        "robot": report.robot.value,
        "instrument_id": report.instrument_id,
        "mode": report.mode.value,
        "source": report.source,
        "bars": report.bar_count,
        "window_start": None if report.window_start is None else report.window_start.isoformat(),
        "window_end": None if report.window_end is None else report.window_end.isoformat(),
        "starting_equity": str(report.starting_equity),
        "ending_equity": None if report.ending_equity is None else str(report.ending_equity),
        "net_pnl": str(report.net_pnl),
        "realized_pnl": str(report.realized_pnl),
        "unrealized_pnl": str(report.unrealized_pnl),
        "fees_paid": str(report.fees_paid),
        "traded_notional": str(report.traded_notional),
        "order_count": len(report.fills),
        "position_count": len(report.positions),
        "open_position": (
            None
            if report.open_position is None
            else {
                "side": report.open_position.side,
                "qty": str(report.open_position.qty),
                "entry_price": str(report.open_position.entry_price),
            }
        ),
        "risk_breaches": [
            {"reason": reason, "count": count} for reason, count in report.risk_breaches
        ],
        "orders": [
            {
                "ts": fill.ts_utc.isoformat(),
                "instrument_id": fill.instrument_id,
                "side": fill.side,
                "qty": str(fill.qty),
                "price": str(fill.price),
                "commission": str(fill.commission),
                "liquidity": fill.liquidity,
                "reason": f"{fill.liquidity.lower() or 'fill'} fill against the simulated venue",
            }
            for fill in report.fills
        ],
        "disclaimer": (
            "Paper session: orders were filled by the simulated venue against closed bars. "
            "No exchange was contacted and no order was submitted."
        ),
    }


def execute_paper(job: PaperRunConfig) -> tuple[dict[str, Any], str]:
    buffer = io.StringIO()
    original = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original, buffer)
    cfg = settings()
    try:
        require_simulated_mode(cfg.trading_mode)
        robot = RobotName(job.robot)
        require_paper_support(robot)
        bar_origin = BarOrigin.SYNTHETIC if job.source == "synthetic" else BarOrigin.CATALOG
        request = paper_request(cfg, bar_count=job.bars, robot=robot, source=bar_origin)
        report = paper_use_case(cfg).execute(request)
        payload = session_payload(report)
        print(report.summary_line())
        for order in payload["orders"][:20]:
            print(
                f"{order['ts']} {order['instrument_id']} {order['side']} "
                f"qty={order['qty']} px={order['price']} fee={order['commission']}"
            )
        return payload, buffer.getvalue()
    except Exception as exc:  # noqa: BLE001 — job boundary: the error goes into the result file
        traceback.print_exc()
        return (
            {"is_finished": True, "is_error": True, "error_message": str(exc)},
            buffer.getvalue(),
        )
    finally:
        sys.stdout = original
