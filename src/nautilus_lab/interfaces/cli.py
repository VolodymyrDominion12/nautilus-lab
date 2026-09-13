from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from nautilus_lab.application.risk import require_simulated_mode
from nautilus_lab.domain.errors import LiveTradingDisabledError, PaperTradingNotReadyError
from nautilus_lab.domain.regime import RobotName
from nautilus_lab.domain.trading_mode import TradingMode
from nautilus_lab.interfaces.composition import research_request, research_use_case, settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lab",
        description="Research-first trading robots on NautilusTrader.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    research = sub.add_parser("research", help="Run a simulated backtest (default path)")
    research.add_argument("--bars", type=int, default=3000, help="Number of 1-minute bars")
    research.add_argument(
        "--robot",
        choices=("regime", "ema"),
        default=None,
        help="regime = trend/range switcher (default), ema = simple crossover",
    )
    sub.add_parser("paper", help="Paper trading (not wired yet)")
    sub.add_parser("live", help="Live trading (always fail closed)")
    args = parser.parse_args(list(argv) if argv is not None else None)

    cfg = settings()
    try:
        if args.command == "research":
            robot = RobotName(args.robot) if args.robot is not None else None
            report = research_use_case().execute(
                research_request(cfg, bar_count=args.bars, robot=robot)
            )
            print(
                f"fills={report.fills} positions={report.positions} ending={report.ending_balance}"
            )
            print(report.notes)
            return 0
        if args.command == "paper":
            require_simulated_mode(TradingMode.PAPER)
        if args.command == "live":
            require_simulated_mode(TradingMode.LIVE)
    except (LiveTradingDisabledError, PaperTradingNotReadyError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
