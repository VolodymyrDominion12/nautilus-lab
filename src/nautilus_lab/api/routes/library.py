"""What the lab has produced and knows: strategy specs, reports, the research journal,
LLM alpha proposals and the hypothesis files they are saved in."""

from __future__ import annotations

import datetime
import glob
import json
import os
from datetime import UTC
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

from nautilus_lab.api.context import Lab
from nautilus_lab.api.journal_service import list_journal_entries, update_journal_decision
from nautilus_lab.api.requests import JournalPatchRequest, ProposeRequest
from nautilus_lab.application.run_alpha_proposal import ProposeJobConfig, execute_propose
from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.infrastructure.llm_client import LlmRequestError

router = APIRouter()


def strategy_spec_payload(data: dict[str, Any]) -> dict[str, Any]:
    """One spec file as the dashboard needs it.

    `wired_in_backtest`, `minimum_bars`, `grid_source`, `domain_module` and
    `strategy_class` live under `implementation:` in the spec schema — the same paths
    `specs/_validator.py` checks. Reading them from the top level made every robot report
    `wired_in_backtest: false` and `minimum_bars: 100`, so the UI labelled working robots
    as fail-closed and the research preflight would have blocked every run. The top-level
    fallback keeps an older-format spec readable instead of silently blank.
    """
    implementation = data.get("implementation")
    impl: dict[str, Any] = implementation if isinstance(implementation, dict) else {}

    def field(name: str, default: object = None) -> object:
        value = impl.get(name)
        if value is None:
            value = data.get(name)
        return default if value is None else value

    params = data.get("params")
    return {
        "name": data.get("name"),
        "title": data.get("title", ""),
        "domain_module": field("domain_module"),
        "strategy_class": field("strategy_class"),
        "backtest_adapter": impl.get("backtest_adapter"),
        "wired_in_backtest": bool(field("wired_in_backtest", False)),
        "minimum_bars": field("minimum_bars", 100),
        "grid_source": field("grid_source"),
        "signal_kind": impl.get("signal_kind"),
        "status": data.get("status", "candidate"),
        # Specs carry no free-text `summary`; `title` is the human one-liner.
        "summary": data.get("summary") or data.get("title", ""),
        "params": params if isinstance(params, list) else [],
        "hypothesis": data.get("hypothesis", ""),
        "invariants": data.get("invariants", []),
    }


@router.get("/api/strategies")
def get_strategies(ctx: Lab) -> dict[str, Any]:
    specs_dir = str(ctx.specs_dir)
    results = []
    failed: list[str] = []
    if not os.path.exists(specs_dir):
        return {"strategies": [], "failed_specs": []}

    for spec_file in sorted(glob.glob(os.path.join(specs_dir, "*.yaml"))):
        try:
            with open(spec_file) as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            # A spec that cannot be parsed is reported, not skipped: a silently missing
            # robot looks identical to one that was never written.
            failed.append(os.path.basename(spec_file))
            continue
        if not isinstance(data, dict) or not data.get("name"):
            failed.append(os.path.basename(spec_file))
            continue
        results.append(strategy_spec_payload(data))

    return {"strategies": results, "failed_specs": failed}


@router.get("/api/reports")
def get_reports(ctx: Lab) -> dict[str, Any]:
    reports_dir = str(ctx.reports_dir)
    if not os.path.exists(reports_dir):
        return {"reports": []}

    files = glob.glob(os.path.join(reports_dir, "*.html"))
    reports = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        mtime = os.path.getmtime(f)
        size = os.path.getsize(f)
        reports.append(
            {
                "filename": os.path.basename(f),
                "path": f,
                "url": f"/static_reports/{os.path.basename(f)}",
                "modified": datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "size_kb": round(size / 1024, 1),
            }
        )
    return {"reports": reports}


@router.get("/api/journal")
def get_journal() -> dict[str, Any]:
    return {"entries": list_journal_entries()}


@router.patch("/api/journal/{index}")
def patch_journal(index: int, req: JournalPatchRequest) -> dict[str, Any]:
    try:
        row = update_journal_decision(index, req.decision)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"entry": row}


@router.post("/api/propose")
def run_propose(req: ProposeRequest) -> dict[str, Any]:
    as_of = None
    if req.as_of:
        try:
            as_of = datetime.date.fromisoformat(req.as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid as_of date: {req.as_of}") from exc
    job = ProposeJobConfig(
        count=req.count,
        dry_run=req.dry_run,
        prompt=req.prompt,
        as_of=as_of,
        model=req.model,
        base_url=req.base_url,
        output_dir=req.output_dir,
        slug=req.slug,
        journal=req.journal,
    )
    try:
        return execute_propose(job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidHypothesisError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LlmRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/api/hypotheses")
def get_hypotheses(ctx: Lab) -> dict[str, Any]:
    hypotheses_dir = str(ctx.hypotheses_dir)
    if not os.path.exists(hypotheses_dir):
        return {"hypotheses": []}

    files = glob.glob(os.path.join(hypotheses_dir, "*.json"))
    items: list[dict[str, Any]] = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        mtime = os.path.getmtime(f)
        size = os.path.getsize(f)
        basename = os.path.basename(f)
        iso_mtime = datetime.datetime.fromtimestamp(mtime, tz=UTC).isoformat()
        item: dict[str, Any] = {
            "file": basename,
            "modified": iso_mtime,
            "size_kb": round(size / 1024, 1),
            "url": f"/static_hypotheses/{basename}",
        }
        try:
            with open(f, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                item["model"] = data.get("model", "unknown")
                item["as_of"] = data.get("as_of", "")
                item["count_parsed"] = data.get("count_parsed", 0)
                item["count_flagged"] = data.get("count_flagged", 0)
                review = data.get("review")
                if isinstance(review, dict):
                    item["review_status"] = review.get("status", "pending")
        except Exception:
            pass
        items.append(item)
    return {"hypotheses": items}


@router.get("/api/hypotheses/{filename}")
def get_hypothesis_detail(ctx: Lab, filename: str) -> dict[str, Any]:
    hypotheses_dir = str(ctx.hypotheses_dir)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    target = os.path.join(hypotheses_dir, filename)
    if not os.path.isfile(target):
        raise HTTPException(status_code=404, detail="hypothesis file not found")
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail="invalid hypothesis file format")
        return data
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="corrupt hypothesis JSON") from exc
