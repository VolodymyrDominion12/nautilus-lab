#!/usr/bin/env python3
"""Offline alpha proposal: prompt -> LLM -> validated hypothesis artifact.

Research only: this never trades, never reads market data and never runs inside a
backtest. It writes one JSON artifact per call under research/hypotheses/, which a
human reviews before anything is implemented in domain/.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from nautilus_lab.application.propose_alphas import (
    AlphaProposalRequest,
    endpoint_host_of,
    load_prompt_template,
    propose_alphas,
    render_prompt,
    summarise,
    write_artifact,
)
from nautilus_lab.domain.errors import DomainError
from nautilus_lab.infrastructure.llm_client import LlmRequestError, OpenAICompatibleChatClient
from nautilus_lab.infrastructure.settings import Settings

EXIT_OK = 0
EXIT_CONFIG = 2
EXIT_ENDPOINT = 3


def _resolve_prompt(name_or_path: str, prompts_dir: str) -> Path:
    candidate = Path(name_or_path)
    if candidate.is_file():
        return candidate
    return Path(prompts_dir) / name_or_path


def _parse_as_of(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    settings = Settings()
    parser = argparse.ArgumentParser(
        prog="propose_alphas",
        description="Ask a model for alpha hypotheses and record them as a reviewable artifact.",
    )
    parser.add_argument(
        "--prompt",
        default="01-generate-alphas.md",
        help=f"Prompt file, or a bare name inside {settings.llm_prompts_dir}",
    )
    parser.add_argument("--count", type=int, default=5, help="How many hypotheses to ask for")
    parser.add_argument("--as-of", type=_parse_as_of, help="Knowledge cutoff date (YYYY-MM-DD)")
    parser.add_argument("--model", default=settings.llm_model, help="Model id")
    parser.add_argument(
        "--base-url", default=settings.llm_base_url, help="OpenAI-compatible base URL"
    )
    parser.add_argument(
        "--output-dir", default=settings.llm_hypotheses_dir, help="Artifact directory"
    )
    parser.add_argument("--slug", help="Override the artifact base name")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render the prompt, call nothing, write nothing (needs no API key)",
    )
    args = parser.parse_args(argv)

    prompt_path = _resolve_prompt(args.prompt, settings.llm_prompts_dir)
    request = AlphaProposalRequest(
        prompt_file=str(prompt_path),
        output_dir=args.output_dir,
        count=args.count,
        as_of=args.as_of,
        slug=args.slug,
    )

    try:
        template = load_prompt_template(prompt_path)
    except DomainError as exc:
        print(f"error: {exc}", flush=True)
        return EXIT_CONFIG

    if args.dry_run:
        as_of = args.as_of or date.today()
        print(render_prompt(template, count=request.count, as_of=as_of))
        print(
            f"\n[dry-run] rendered {prompt_path}; no network call, model {args.model} unused.",
            flush=True,
        )
        return EXIT_OK

    api_key = (settings.llm_api_key or "").strip()
    if not api_key:
        print(
            "error: LLM_API_KEY is not set, so the proposal loop fails closed.\n"
            "       Set it in .env (or export it), or use --dry-run to inspect the prompt.",
            flush=True,
        )
        return EXIT_CONFIG

    try:
        client = OpenAICompatibleChatClient(
            api_key=api_key,
            base_url=args.base_url,
            model=args.model,
            temperature=settings.llm_temperature,
            timeout_seconds=settings.llm_timeout_seconds,
        )
        run = propose_alphas(
            completer=client,
            template=template,
            model=client.model,
            endpoint_host=endpoint_host_of(args.base_url),
            prompt_file=str(prompt_path),
            count=request.count,
            as_of=request.as_of,
        )
    except LlmRequestError as exc:
        print(f"error: {exc}", flush=True)
        return EXIT_ENDPOINT
    except DomainError as exc:
        print(f"error: the model returned an unusable artifact: {exc}", flush=True)
        return EXIT_CONFIG

    path = write_artifact(run, output_dir=Path(request.output_dir), slug=request.slug)
    print(summarise(run))
    print(f"\nArtifact: {path}", flush=True)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
