from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from nautilus_lab.application.journal import JournalEntry, record_run
from nautilus_lab.application.propose_alphas import (
    endpoint_host_of,
    load_prompt_template,
    propose_alphas,
    render_prompt,
    summarise,
    write_artifact,
)
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import (
    alpha_proposal_request,
    journal_paths,
    llm_completer,
    settings,
)


@dataclass(frozen=True, slots=True)
class ProposeJobConfig:
    count: int = 5
    dry_run: bool = True
    prompt: str = "01-generate-alphas.md"
    as_of: date | None = None
    model: str | None = None
    base_url: str | None = None
    output_dir: str | None = None
    slug: str | None = None
    journal: bool = False


def execute_propose(job: ProposeJobConfig, cfg: Settings | None = None) -> dict[str, Any]:
    resolved = cfg or settings()
    request = alpha_proposal_request(
        resolved,
        prompt=job.prompt,
        count=job.count,
        as_of=job.as_of,
        output_dir=job.output_dir,
        slug=job.slug,
    )
    template = load_prompt_template(Path(request.prompt_file))
    model = job.model or resolved.llm_model

    if job.dry_run:
        as_of = job.as_of or datetime.now(UTC).date()
        return {
            "status": "dry_run",
            "message": (
                f"Rendered {request.prompt_file}; no network call. "
                f"Model {model} would be used when dry_run=false."
            ),
            "prompt": render_prompt(template, count=request.count, as_of=as_of),
            "model": model,
            "count": job.count,
        }

    if not (resolved.llm_api_key or "").strip():
        msg = (
            "LLM_API_KEY is not set, so propose fails closed. Set it in .env, or use dry_run=true."
        )
        raise ValueError(msg)

    run = propose_alphas(
        completer=llm_completer(resolved, model=job.model, base_url=job.base_url),
        template=template,
        model=model,
        endpoint_host=endpoint_host_of(job.base_url or resolved.llm_base_url),
        prompt_file=request.prompt_file,
        count=request.count,
        as_of=request.as_of,
    )
    path = write_artifact(run, output_dir=Path(request.output_dir), slug=request.slug)
    if job.journal or resolved.journal_enabled:
        markdown_path, jsonl_path = journal_paths(resolved)
        record_run(
            markdown_path=markdown_path,
            jsonl_path=jsonl_path,
            entry=JournalEntry(
                created_at=datetime.now(UTC),
                source="lab propose",
                subject=f"proposal {model}",
                gates="not run yet (proposal only)",
                reason=f"awaiting review: {path}",
                artifact=str(path),
            ),
        )

    return {
        "status": "success",
        "artifact_path": str(path),
        "summary": summarise(run),
        "model": model,
        "count_requested": run.count_requested,
        "count_parsed": len(run.hypotheses),
        "hypotheses": [item.as_dict() for item in run.hypotheses],
    }
