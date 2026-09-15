"""Offline alpha-proposal loop: prompt -> LLM -> validated hypotheses -> artifact.

This is the only place in the project that talks to a language model, and it runs
outside the backtest: the model proposes, the artifact is recorded, a human decides,
and only then does anything reach `domain/`. The hot path never calls this module
(docs/14-llm-model-u-torhivli.md, section 1).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import urlparse

from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES
from nautilus_lab.domain.hypothesis import Hypothesis, parse_hypotheses
from nautilus_lab.domain.ports import ChatCompleter

ARTIFACT_VERSION = 1

SYSTEM_PROMPT = (
    "You are a quantitative researcher in a research lab. You propose testable "
    "hypotheses, never trade recommendations. You do not know and must not use "
    "anything that became known after the stated as-of date. Answer with valid JSON "
    "only, with no text around it."
)

REQUIRED_PLACEHOLDERS: tuple[str, ...] = ("{{FEATURES}}", "{{COUNT}}", "{{AS_OF}}")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class AlphaProposalRequest:
    prompt_file: str = "research/prompts/01-generate-alphas.md"
    output_dir: str = "research/hypotheses"
    count: int = 5
    as_of: date | None = None
    slug: str | None = None


@dataclass(frozen=True, slots=True)
class AlphaProposalRun:
    """One model call, fully attributed: the artifact is the unit of reproducibility."""

    created_at: datetime
    model: str
    endpoint_host: str
    prompt_file: str
    prompt_sha256: str
    as_of: date
    count_requested: int
    hypotheses: tuple[Hypothesis, ...]
    raw_response: str

    @property
    def flagged(self) -> tuple[Hypothesis, ...]:
        """Proposals referring to identifiers that are not real features."""
        return tuple(item for item in self.hypotheses if item.unknown_identifiers())

    def as_dict(self) -> dict[str, object]:
        return {
            "version": ARTIFACT_VERSION,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "model": self.model,
            "endpoint_host": self.endpoint_host,
            "as_of": self.as_of.isoformat(),
            "prompt_file": self.prompt_file,
            "prompt_sha256": self.prompt_sha256,
            "feature_contract": list(FEATURE_NAMES),
            "count_requested": self.count_requested,
            "count_parsed": len(self.hypotheses),
            "count_flagged": len(self.flagged),
            "hypotheses": [item.as_dict() for item in self.hypotheses],
            "raw_response": self.raw_response,
            "review": {
                "status": "pending",
                "note": "",
                "gates": {
                    "purged_cv": None,
                    "walk_forward_oos": None,
                    "buy_and_hold_oos": None,
                },
            },
        }


def load_prompt_template(path: Path) -> str:
    """Read a prompt template. Fail closed: a missing or empty file is an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise InvalidHypothesisError(f"prompt template not found: {path}") from exc
    if not text.strip():
        raise InvalidHypothesisError(f"prompt template is empty: {path}")
    return text


def prompt_sha256(template: str) -> str:
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def render_prompt(template: str, *, count: int, as_of: date) -> str:
    """Fill the documented placeholders. A template missing one is a hard error."""
    if count < 1:
        raise ValueError("count must be >= 1")
    missing = [item for item in REQUIRED_PLACEHOLDERS if item not in template]
    if missing:
        raise InvalidHypothesisError(
            f"prompt template must contain {', '.join(REQUIRED_PLACEHOLDERS)}; "
            f"missing {', '.join(missing)}"
        )
    rendered = template.replace("{{FEATURES}}", ", ".join(FEATURE_NAMES))
    rendered = rendered.replace("{{COUNT}}", str(count))
    return rendered.replace("{{AS_OF}}", as_of.isoformat())


def extract_json_block(text: str) -> object:
    """Decode the first JSON object/array in a model response, fences included."""
    body = _strip_code_fence(text)
    decoder = json.JSONDecoder()
    for index, char in enumerate(body):
        if char not in "[{":
            continue
        try:
            parsed, _ = decoder.raw_decode(body[index:])
        except json.JSONDecodeError:
            continue
        value: object = parsed
        return value
    raise InvalidHypothesisError("model response contains no JSON object or array")


def propose_alphas(
    *,
    completer: ChatCompleter,
    template: str,
    model: str,
    endpoint_host: str,
    prompt_file: str,
    count: int = 5,
    as_of: date | None = None,
    now: datetime | None = None,
) -> AlphaProposalRun:
    """Call the model once and validate what comes back. Network lives in the caller."""
    resolved_as_of = as_of or (now or datetime.now(UTC)).astimezone(UTC).date()
    user_prompt = render_prompt(template, count=count, as_of=resolved_as_of)
    response = completer.complete(system=SYSTEM_PROMPT, user=user_prompt)
    hypotheses = parse_hypotheses(extract_json_block(response))
    return AlphaProposalRun(
        created_at=now or datetime.now(UTC),
        model=model,
        endpoint_host=endpoint_host,
        prompt_file=prompt_file,
        prompt_sha256=prompt_sha256(template),
        as_of=resolved_as_of,
        count_requested=count,
        hypotheses=hypotheses,
        raw_response=response,
    )


def artifact_slug(run: AlphaProposalRun) -> str:
    """Deterministic base name: same prompt + model + date reproduce the same slug."""
    model_slug = _SLUG_RE.sub("-", run.model.lower()).strip("-") or "model"
    return f"{run.as_of.isoformat()}-{model_slug}-{run.prompt_sha256[:8]}"


def write_artifact(
    run: AlphaProposalRun,
    *,
    output_dir: Path,
    slug: str | None = None,
) -> Path:
    """Write the run as JSON, never overwriting an earlier run of the same call."""
    output_dir.mkdir(parents=True, exist_ok=True)
    base = slug or artifact_slug(run)
    path = output_dir / f"{base}.json"
    attempt = 2
    while path.exists():
        path = output_dir / f"{base}-r{attempt}.json"
        attempt += 1
    payload = json.dumps(run.as_dict(), indent=2, ensure_ascii=False)
    path.write_text(f"{payload}\n", encoding="utf-8")
    return path


def summarise(run: AlphaProposalRun) -> str:
    """Human-readable review sheet for the terminal (same language as the rest of the CLI)."""
    lines = [
        f"Model: {run.model} @ {run.endpoint_host}",
        f"As of: {run.as_of.isoformat()}  (knowledge cutoff stated to the model)",
        f"Prompt: {run.prompt_file}  sha256={run.prompt_sha256[:12]}",
        f"Hypotheses: {len(run.hypotheses)} of {run.count_requested}",
        "",
    ]
    for index, item in enumerate(run.hypotheses, start=1):
        flag = item.unknown_identifiers()
        marker = " [!]" if flag else ""
        lines.append(f"{index}. {item.name}{marker}")
        lines.append(f"   formula: {item.formula}")
        lines.append(f"   horizon: {item.horizon_bars} bars, sign: {item.expected_sign:+d}")
        if flag:
            lines.append(f"   UNKNOWN IDENTIFIERS: {', '.join(flag)}")
        else:
            try:
                complexity = recipe_complexity(parse_recipe(item.formula))
            except InvalidHypothesisError as exc:
                lines.append(f"   COMPILE ERROR: {exc}")
            else:
                lines.append(f"   complexity: {complexity}")
    if run.flagged:
        lines += [
            "",
            f"WARNING: {len(run.flagged)} proposal(s) reference identifiers that are not "
            "real features.",
            "That is usually an invented feature - review by hand before any run.",
        ]
    lines += [
        "",
        "Next: human approval -> implement in domain/ per docs/07 -> purged CV ->",
        "walk-forward OOS, then a decision row in research/journal.md.",
    ]
    return "\n".join(lines)


def endpoint_host_of(base_url: str) -> str:
    """Host (and non-default port) only.

    The artifact records provenance, never credentials: a base URL may legitimately
    carry userinfo, and that must not end up in a file committed to git.
    """
    parsed = urlparse(base_url)
    if not parsed.hostname:
        return "unknown"
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()
