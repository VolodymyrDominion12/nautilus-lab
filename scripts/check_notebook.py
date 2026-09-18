"""Execute the generated research notebook's code cells, so drift is caught by machine.

Why this exists. `notebooks/strategy_research_guide.ipynb` is a generated artifact:
its cells are written as Python string literals by
`scripts/generate_research_notebook.py`. Nothing in the project could see that
code. `mypy` does not read notebooks, and linting the generated `.ipynb` only ever
reported unused imports — so when the notebook's embedded code drifted away from
the real API it went unnoticed, and the committed notebook referenced
`pnl_percent`, `fill_count`, `pbo_request`, `JournalRecord` and
`record_journal_entry`, none of which have ever existed in `src/`.

Running the cells is the check that actually holds. It needs no kernel and no new
dependency, because the notebook uses no cell magics — only plain Python — so a
single `exec` per cell reproduces what a kernel would do for this content.

The notebook is generated, so the robust fix for a failure here is to repair
`scripts/generate_research_notebook.py` and regenerate, not to hand-edit the
`.ipynb`: hand edits are lost the next time the generator runs.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

DEFAULT_NOTEBOOK = Path("notebooks/strategy_research_guide.ipynb")

# Smoke-sized overrides for the notebook's demo parameters. The notebook defaults
# to a full-fidelity run (3000 bars, 4 folds, 8 blocks), which takes over 40
# minutes — far too slow for a gate. These smaller values still exercise every
# cell and every code path, including the grid search, the multi-window
# walk-forward and the CSCV audit, but finish in minutes. They are big enough to
# clear the robot's `minimum_bars` warm-up: 1200 bars over 2 folds leaves 840
# in-sample and 360 out-of-sample, and 4 blocks are 300 bars each.
SMOKE_PARAMETERS = {
    "LAB_NOTEBOOK_BARS": "1200",
    "LAB_NOTEBOOK_FOLDS": "2",
    "LAB_NOTEBOOK_BLOCKS": "4",
}


def suppress_interactive_display() -> None:
    """Stop `Figure.show()` from trying to display anything.

    This gate runs headless. An unpatched `fig.show()` blocks indefinitely waiting
    on a browser renderer — the process sits at ~1% CPU forever instead of
    finishing, which is a hang, not a slow test. Nothing about *rendering* is being
    verified here anyway; the point is that the cell's code executes.
    """
    try:
        from plotly.basedatatypes import BaseFigure
    except ImportError:
        return

    def _no_show(self: object, *args: object, **kwargs: object) -> None:
        traces = getattr(self, "data", ())
        print(f"    (display suppressed: figure with {len(traces)} traces)")

    BaseFigure.show = _no_show  # type: ignore[method-assign]


def execute_notebook(path: Path) -> int:
    """Run every code cell in one shared namespace. Returns a process exit code."""
    notebook = json.loads(path.read_text(encoding="utf-8"))
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        print(f"{path}: no 'cells' list; is this a notebook?", file=sys.stderr)
        return 1

    # `setdefault`, so an explicit environment always wins over the smoke defaults.
    for name, value in SMOKE_PARAMETERS.items():
        os.environ.setdefault(name, value)
    suppress_interactive_display()

    # One namespace for all cells, exactly like a kernel session.
    namespace: dict[str, object] = {"__name__": "__notebook__"}
    executed = 0
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict) or cell.get("cell_type") != "code":
            continue
        source = "".join(cell.get("source", []))
        if not source.strip():
            continue
        # Progress is flushed before each cell: without it a hanging cell is
        # indistinguishable from a slow one in CI logs.
        print(f"  cell {index}: running…", flush=True)
        try:
            exec(compile(source, f"{path}:cell {index}", "exec"), namespace)
        except Exception:  # deliberately broad: any cell failure is the finding
            print(f"\n{path}: cell {index} raised:", file=sys.stderr)
            traceback.print_exc()
            return 1
        executed += 1

    if executed == 0:
        print(f"{path}: no non-empty code cells found", file=sys.stderr)
        return 1
    print(f"{path}: {executed} code cells executed cleanly")
    return 0


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT_NOTEBOOK
    if not path.exists():
        print(f"{path}: not found. Generate it with scripts/generate_research_notebook.py")
        return 1
    return execute_notebook(path)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
