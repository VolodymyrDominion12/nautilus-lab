#!/usr/bin/env python3
"""Thin wrapper around `lab propose` — offline alpha proposals, research only.

The implementation lives in `nautilus_lab.interfaces.cli`, so this script and the CLI
command cannot drift apart. Kept as a documented entry point for the research loop
(research/README.md, docs/14-llm-model-u-torhivli.md).
"""

from __future__ import annotations

import sys
from collections.abc import Sequence

from nautilus_lab.interfaces.cli import main


def forward(argv: Sequence[str]) -> int:
    """Run `lab propose` with the given arguments."""
    return main(["propose", *argv])


if __name__ == "__main__":
    raise SystemExit(forward(sys.argv[1:]))
