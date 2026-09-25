import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from nautilus_lab.application.propose_alphas import (
    SYSTEM_PROMPT,
    AlphaProposalRun,
    artifact_slug,
    endpoint_host_of,
    extract_json_block,
    load_prompt_template,
    prompt_sha256,
    propose_alphas,
    render_prompt,
    summarise,
    write_artifact,
)
from nautilus_lab.domain.errors import InvalidHypothesisError
from nautilus_lab.domain.formulaic_alphas import FEATURE_NAMES

_TEMPLATE = "Features: {{FEATURES}}\nGive {{COUNT}} hypotheses as of {{AS_OF}}.\n"

_HYPOTHESES_JSON = json.dumps(
    [
        {
            "name": "volume-climax reversal",
            "formula": "-reversal_3 * zscore(volume_ratio)",
            "mechanism": "the aggressor is spent after a volume spike",
            "horizon_bars": 5,
            "expected_sign": -1,
            "kill_condition": "out-of-sample IC < 0 in two adjacent folds",
        },
        {
            "name": "trend continuation",
            "formula": "trend_er * momentum_10",
            "mechanism": "trends persist while latecomers chase them",
            "horizon_bars": 12,
            "expected_sign": 1,
            "kill_condition": "trend_er does not separate out-of-sample from noise",
        },
    ]
)

_NOW = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)


class _FakeCompleter:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def _run(completer: _FakeCompleter, *, count: int = 2) -> AlphaProposalRun:
    return propose_alphas(
        completer=completer,
        template=_TEMPLATE,
        model="deepseek-chat",
        endpoint_host="api.deepseek.com",
        prompt_file="research/prompts/01-generate-alphas.md",
        count=count,
        as_of=date(2026, 9, 15),
        now=_NOW,
    )


def test_render_prompt_fills_every_placeholder() -> None:
    rendered = render_prompt(_TEMPLATE, count=7, as_of=date(2026, 9, 15))
    assert "{{" not in rendered
    assert "2026-09-15" in rendered
    assert "Give 7 hypotheses" in rendered
    for name in FEATURE_NAMES:
        assert name in rendered


def test_render_prompt_requires_all_placeholders() -> None:
    with pytest.raises(InvalidHypothesisError, match="AS_OF"):
        render_prompt("Features: {{FEATURES}}, count {{COUNT}}", count=3, as_of=date(2026, 9, 15))


def test_render_prompt_rejects_zero_count() -> None:
    with pytest.raises(ValueError, match="count"):
        render_prompt(_TEMPLATE, count=0, as_of=date(2026, 9, 15))


def test_load_prompt_template_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(InvalidHypothesisError, match="not found"):
        load_prompt_template(tmp_path / "missing.md")
    empty = tmp_path / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    with pytest.raises(InvalidHypothesisError, match="empty"):
        load_prompt_template(empty)


def test_extract_json_block_handles_fences_and_prose() -> None:
    fenced = f"Here is the result:\n```json\n{_HYPOTHESES_JSON}\n```\nDone."
    parsed = extract_json_block(fenced)
    assert isinstance(parsed, list)
    assert len(parsed) == 2
    assert extract_json_block('{"hypotheses": []}') == {"hypotheses": []}


def test_extract_json_block_fails_without_json() -> None:
    with pytest.raises(InvalidHypothesisError, match="no JSON"):
        extract_json_block("I cannot complete this task")


def test_extract_json_block_falls_back_to_later_object() -> None:
    parsed = extract_json_block("note {broken} then " + _HYPOTHESES_JSON)
    assert isinstance(parsed, list)


def test_prompt_hash_is_stable_and_content_addressed() -> None:
    assert prompt_sha256(_TEMPLATE) == prompt_sha256(_TEMPLATE)
    assert prompt_sha256(_TEMPLATE) != prompt_sha256(_TEMPLATE + "\n")


def test_propose_alphas_builds_attributed_run() -> None:
    completer = _FakeCompleter(f"```json\n{_HYPOTHESES_JSON}\n```")
    run = _run(completer)
    assert len(run.hypotheses) == 2
    assert run.flagged == ()
    assert run.as_of == date(2026, 9, 15)
    assert run.created_at == _NOW
    assert run.prompt_sha256 == prompt_sha256(_TEMPLATE)
    assert run.raw_response.startswith("```json")
    system, user = completer.calls[0]
    assert system == SYSTEM_PROMPT
    assert "2026-09-15" in user


def test_propose_alphas_flags_invented_features() -> None:
    payload = json.loads(_HYPOTHESES_JSON)
    payload[0]["formula"] = "mean(order_flow_imbalance)"
    run = _run(_FakeCompleter(json.dumps(payload)))
    assert [item.name for item in run.flagged] == ["volume-climax reversal"]


def test_propose_alphas_propagates_invalid_payload() -> None:
    with pytest.raises(InvalidHypothesisError, match="no JSON"):
        _run(_FakeCompleter("no JSON to be found here"))


def test_artifact_slug_is_deterministic_and_model_scoped() -> None:
    run = _run(_FakeCompleter(_HYPOTHESES_JSON))
    slug = artifact_slug(run)
    assert slug.startswith("2026-09-15-deepseek-chat-")
    assert artifact_slug(run) == slug


def test_write_artifact_never_overwrites_an_earlier_run(tmp_path: Path) -> None:
    run = _run(_FakeCompleter(_HYPOTHESES_JSON))
    first = write_artifact(run, output_dir=tmp_path)
    second = write_artifact(run, output_dir=tmp_path)
    third = write_artifact(run, output_dir=tmp_path, slug="custom-name")
    assert first.exists()
    assert second.exists()
    assert third.exists()
    assert first.name != second.name
    assert second.name.endswith("-r2.json")
    assert third.name == "custom-name.json"

    payload = json.loads(first.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["count_parsed"] == 2
    assert payload["endpoint_host"] == "api.deepseek.com"
    assert payload["review"]["status"] == "pending"
    assert payload["feature_contract"] == list(FEATURE_NAMES)
    assert payload["hypotheses"][0]["unknown_identifiers"] == []


def test_summarise_reports_flagged_proposals() -> None:
    payload = json.loads(_HYPOTHESES_JSON)
    payload[0]["formula"] = "mean(ghost_feature)"
    text = summarise(_run(_FakeCompleter(json.dumps(payload))))
    assert "UNKNOWN IDENTIFIERS: ghost_feature" in text
    assert "research/journal.md" in text


def test_summarise_compiles_valid_formulas_and_flags_shallow_ones() -> None:
    text = summarise(_run(_FakeCompleter(_HYPOTHESES_JSON)))
    assert "complexity:" in text
    payload = json.loads(_HYPOTHESES_JSON)
    payload[0]["formula"] = "momentum_10"
    shallow = summarise(_run(_FakeCompleter(json.dumps(payload))))
    assert "COMPILE ERROR:" in shallow


def test_endpoint_host_of_strips_credentials_and_path() -> None:
    assert endpoint_host_of("https://api.deepseek.com/v1") == "api.deepseek.com"
    assert endpoint_host_of("http://127.0.0.1:11434/v1") == "127.0.0.1:11434"
    assert endpoint_host_of("https://user:secret@gateway.internal/v1") == "gateway.internal"
    assert endpoint_host_of("not-a-url") == "unknown"
