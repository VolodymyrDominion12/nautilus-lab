from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass
from typing import Any, TextIO, cast

from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.application.run_paper import RunPaperResearch
from nautilus_lab.domain.bars import BarOrigin
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.interfaces.composition import research_request, research_use_case, settings


@dataclass(frozen=True, slots=True)
class PaperRunConfig:
    robot: str = "regime"
    bars: int = 500
    source: str = "synthetic"


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


def execute_paper(job: PaperRunConfig) -> tuple[dict[str, Any], str]:
    buffer = io.StringIO()
    original = cast(TextIO, sys.stdout)
    sys.stdout = _Tee(original, buffer)
    cfg = settings()
    try:
        require_simulated_mode(cfg.trading_mode)
        bar_origin = BarOrigin.SYNTHETIC if job.source == "synthetic" else BarOrigin.CATALOG
        request = research_request(
            cfg,
            bar_count=job.bars,
            robot=RobotName(job.robot),
            source=bar_origin,
        )
        bars = research_use_case(cfg)._feed.load(request)
        logger = RunPaperResearch().execute(request, bars)
        orders = [
            {
                "ts": order.ts_utc.isoformat(),
                "instrument_id": order.instrument_id,
                "side": str(order.side),
                "qty": str(order.qty),
                "reason": order.description,
            }
            for order in logger.orders
        ]
        print(f"paper_orders={len(logger.orders)} (no exchange submission)")
        for order in logger.orders[:20]:
            print(
                f"{order.ts_utc.isoformat()} {order.instrument_id} "
                f"{order.side} qty={order.qty} reason={order.description}"
            )
        return (
            {
                "is_finished": True,
                "is_error": False,
                "robot": job.robot,
                "order_count": len(logger.orders),
                "orders": orders,
                "disclaimer": "Paper mode logs hypothetical orders only; no position state.",
            },
            buffer.getvalue(),
        )
    except Exception as exc:
        traceback.print_exc()
        return (
            {"is_finished": True, "is_error": True, "error_message": str(exc)},
            buffer.getvalue(),
        )
    finally:
        sys.stdout = original
