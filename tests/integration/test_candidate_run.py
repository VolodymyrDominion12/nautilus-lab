"""The candidate path: pre-register the walk-forward, then judge the whole gate.

Two things were impossible from the dashboard before this (docs/35 §3): promising the test
terms before measuring (`--register` existed only in the CLI), and reaching a verdict with
*every* check measured. The gate needs `folds` from a walk-forward and `pbo`/`dsr` from an
overfitting audit, and no single `lab research` invocation produced both — so a dashboard
cell could be REJECT or INCOMPLETE and never PROMOTE, whatever its numbers said.

These tests use a temporary catalog and a seeded synthetic series, so they stay cheap: the
point is the wiring and the verdict, not the numbers.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.catalog.singleton import clear_singleton_instances

from nautilus_lab.api.research_runner import ResearchJobConfig, execute_research
from nautilus_lab.domain.bars import OhlcvBar
from nautilus_lab.infrastructure.nautilus.parquet_catalog import NautilusParquetCatalog
from nautilus_lab.infrastructure.nautilus.synthetic_bars import (
    synthetic_ohlcv,
    synthetic_regime_ohlcv,
)

BAR_TYPE = "ETH/USDT.SIM-1-HOUR-LAST-EXTERNAL"
BAR_TYPE_4H = "ETH/USDT.SIM-4-HOUR-LAST-EXTERNAL"


def _bars_across_days(count: int, *, step: timedelta, seed: int) -> list[OhlcvBar]:
    """Seeded synthetic prices, re-stamped `step` apart so the series crosses days.

    The generators step by one minute, so any series they produce sits inside a single day
    and leaves the gate's DSR unmeasurable — it is recomputed from the walk-forward's OOS
    *daily* returns. Real catalogs span months; this fixture has to do the same.
    """
    origin = datetime(2024, 1, 1, tzinfo=UTC)
    bars = synthetic_ohlcv(instrument_id="ETH/USDT.SIM", count=count, seed=seed)
    return [replace(bar, ts_utc=origin + step * index) for index, bar in enumerate(bars)]


def _gate_checks(result: dict[str, object]) -> dict[str, str]:
    gate = result.get("promotion_gate")
    assert isinstance(gate, dict), "every candidate run must carry a verdict"
    return {str(check["name"]): str(check["status"]) for check in gate["checks"]}


@pytest.mark.integration
def test_a_registered_walk_forward_is_measured_after_its_terms_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Register and run inside one job, and still read `preregistered=pass`.

    The gate refuses a registration dated at or after the run's start (`LATE`), so the
    instant the measurement begins has to be taken *after* the terms are on disk. Taking it
    once, at job start, silently produced `registered after the run` and a failed check —
    which is exactly what the first version of this code did.
    """
    clear_singleton_instances(ParquetDataCatalog)
    monkeypatch.setenv("PREREGISTRATIONS_DIR", str(tmp_path / "preregistrations"))
    monkeypatch.setenv("TRIALS_LEDGER_PATH", str(tmp_path / "trials.jsonl"))
    bars = synthetic_regime_ohlcv(instrument_id="ETH/USDT.SIM", count=600, seed=13)
    NautilusParquetCatalog(tmp_path / "catalog").write(bars, bar_type=BAR_TYPE)

    result, log = execute_research(
        ResearchJobConfig(
            robot="ema",
            source="catalog",
            folds=2,
            catalog_path=str(tmp_path / "catalog"),
            instrument_id="ETH/USDT.SIM",
            bar_interval="1h",
            register="H: ema 10/20 beats buy&hold in every OOS fold?",
        )
    )

    assert "preregistration written:" in log
    checks = _gate_checks(result)
    assert checks["preregistered"] == "pass", log
    # The registration went to the configured store, not to the tracked research/ tree.
    written = list((tmp_path / "preregistrations").glob("*.json"))
    assert len(written) == 1
    # The rest of the gate is measured from the same run: folds are known, pbo is not.
    assert checks["folds"] != "not measured"
    assert checks["pbo"] == "not measured", "the audit is a separate half, not run here"


@pytest.mark.integration
def test_promote_also_measures_the_overfitting_half(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`promote` runs the audit too, so `pbo` and `dsr` stop reading `not measured`.

    Without that half the verdict can never be PROMOTE, and a reader cannot tell "the
    selection did not survive the audit" from "the audit never ran". The gate recomputes
    DSR from the walk-forward's OOS daily returns against the audit's trial Sharpes, so it
    needs both halves *and* windows long enough to have daily returns — hence a catalog
    series here rather than synthetic minutes.
    """
    clear_singleton_instances(ParquetDataCatalog)
    monkeypatch.setenv("TRIALS_LEDGER_PATH", str(tmp_path / "trials.jsonl"))
    bars = _bars_across_days(600, step=timedelta(hours=4), seed=17)
    NautilusParquetCatalog(tmp_path / "catalog").write(bars, bar_type=BAR_TYPE_4H)

    result, log = execute_research(
        ResearchJobConfig(
            robot="ema",
            source="catalog",
            catalog_path=str(tmp_path / "catalog"),
            instrument_id="ETH/USDT.SIM",
            bar_interval="4h",
            folds=2,
            promote=True,
            # DSR needs >= 8 observations (block returns); fewer blocks leave it undefined
            # and the gate then reads it as not measured — honest, but weaker tested.
            pbo_blocks=8,
        )
    )

    assert "note: promote without register" in log, "an unregistered candidate says so"
    assert result.get("pbo") is not None, "the audit report must be in the payload"
    checks = _gate_checks(result)
    assert checks["pbo"] != "not measured"
    assert checks["dsr"] != "not measured", log
    assert checks["preregistered"] == "not measured", "no registration was made"


@pytest.mark.integration
def test_the_request_payload_names_the_hypothesis_without_shadowing_pydantic() -> None:
    """`register` is `BaseModel.register`; the request field is `preregister` on purpose.

    A field named `register` made pydantic warn on every import and would have shadowed the
    model's own method — a name that fights the framework for no gain (the CLI flag stays
    `--register`, which is the documented terminal interface).
    """
    from nautilus_lab.api.requests import ResearchRunRequest

    request = ResearchRunRequest(robot="ema", preregister="H: ema beats buy&hold?")
    assert request.preregister == "H: ema beats buy&hold?"
    assert not hasattr(request, "register") or callable(request.register)


def _refusal(job: ResearchJobConfig) -> str:
    """The job's error message: `execute_research` reports failures, it does not raise."""
    result, _ = execute_research(job)
    assert result["is_error"] is True, "this combination must be refused before it runs"
    return str(result["error_message"])


@pytest.mark.integration
def test_the_candidate_switches_refuse_combinations_that_cannot_promote() -> None:
    """Each refusal names the reason: a run that cannot be promoted must not look like one."""
    assert "register needs folds" in _refusal(ResearchJobConfig(robot="ema", register="H", folds=1))
    assert "register is for catalog data" in _refusal(
        ResearchJobConfig(robot="ema", source="synthetic", register="H", folds=2)
    )
    assert "register describes the walk-forward" in _refusal(
        ResearchJobConfig(robot="ema", register="H", folds=2, pbo=True)
    )
    assert "promote already runs the pbo audit" in _refusal(
        ResearchJobConfig(robot="ema", promote=True, pbo=True)
    )
    assert "promote needs folds" in _refusal(ResearchJobConfig(robot="ema", promote=True, folds=1))
    assert "not a full-sample run" in _refusal(
        ResearchJobConfig(robot="ema", promote=True, folds=2, full_sample=True)
    )
