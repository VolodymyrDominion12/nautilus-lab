"""Where a result came from: code, dependencies, data and settings of one run.

A number in the research journal or a paper ledger is evidence only if it can be
produced again. That needs four things written next to it, not remembered:

* **code** — the git revision, and whether the working tree had uncommitted edits
  (a dirty tree means the revision alone cannot rebuild the run);
* **dependencies** — a hash of `uv.lock` and the NautilusTrader version, because an
  engine upgrade changes fills without any change in this repository;
* **settings** — a hash of the effective configuration. Shell variables override
  `.env` (AGENTS.md, «Пастки середовища»: `MAKER_FEE`/`TAKER_FEE` from the shell), so
  `.env` in git is not proof of what the run used;
* **data** — a fingerprint of the catalog the bars were read from.

This module only holds the value. Collecting it (git, files, versions) is I/O and
lives in `infrastructure/provenance.py`. Every field is optional on purpose: a missing
fact is recorded as unknown, never guessed, and never stops a run.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_SHORT = 12


@dataclass(frozen=True, slots=True)
class RunManifest:
    """Provenance of one run. `None` means "not known here", never "empty"."""

    code_revision: str | None = None
    code_dirty: bool | None = None
    revision_source: str | None = None
    lock_sha256: str | None = None
    python_version: str | None = None
    nautilus_version: str | None = None
    settings_sha256: str | None = None
    catalog_fingerprint: str | None = None
    catalog_files: int | None = None
    #: Hash of the run's walk-forward terms (docs/27 R-2); set after the fold windows
    #: are known, compared with `research/preregistrations/`.
    preregistration_sha256: str | None = None

    @property
    def reproducible(self) -> bool:
        """True only when a committed revision alone can rebuild the code of the run."""
        return self.code_revision is not None and self.code_dirty is False

    def warnings(self) -> tuple[str, ...]:
        """Why this run cannot be reproduced from what was recorded, if it cannot."""
        found: list[str] = []
        if self.code_revision is None:
            found.append("code revision unknown (no git and no LAB_REVISION)")
        elif self.code_dirty:
            found.append(
                "working tree has uncommitted changes: the revision alone does not rebuild this run"
            )
        if self.lock_sha256 is None:
            found.append("uv.lock not found: dependency versions not pinned in the record")
        return tuple(found)

    def summary_line(self) -> str:
        """One `key=value` line in the style the CLI already prints."""
        revision = _short(self.code_revision) or "unknown"
        if self.code_dirty:
            revision += "+dirty"
        parts = [
            f"manifest rev={revision}",
            f"lock={_short(self.lock_sha256) or 'unknown'}",
            f"settings={_short(self.settings_sha256) or 'unknown'}",
            f"nautilus={self.nautilus_version or 'unknown'}",
        ]
        if self.catalog_fingerprint is not None:
            parts.append(f"catalog={_short(self.catalog_fingerprint)}({self.catalog_files} files)")
        if self.preregistration_sha256 is not None:
            parts.append(f"terms={_short(self.preregistration_sha256)}")
        return " ".join(parts)

    def as_dict(self) -> dict[str, object]:
        return {
            "code_revision": self.code_revision,
            "code_dirty": self.code_dirty,
            "revision_source": self.revision_source,
            "lock_sha256": self.lock_sha256,
            "python_version": self.python_version,
            "nautilus_version": self.nautilus_version,
            "settings_sha256": self.settings_sha256,
            "catalog_fingerprint": self.catalog_fingerprint,
            "catalog_files": self.catalog_files,
            "preregistration_sha256": self.preregistration_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> RunManifest:
        """Rebuild from a journal record. Unknown keys are ignored; wrong types rejected."""
        dirty = payload.get("code_dirty")
        if dirty is not None and not isinstance(dirty, bool):
            raise ValueError("code_dirty must be a boolean or null")
        files = payload.get("catalog_files")
        if files is not None and (isinstance(files, bool) or not isinstance(files, int)):
            raise ValueError("catalog_files must be an integer or null")
        return cls(
            code_revision=_optional_str(payload, "code_revision"),
            code_dirty=dirty,
            revision_source=_optional_str(payload, "revision_source"),
            lock_sha256=_optional_str(payload, "lock_sha256"),
            python_version=_optional_str(payload, "python_version"),
            nautilus_version=_optional_str(payload, "nautilus_version"),
            settings_sha256=_optional_str(payload, "settings_sha256"),
            catalog_fingerprint=_optional_str(payload, "catalog_fingerprint"),
            catalog_files=files,
            preregistration_sha256=_optional_str(payload, "preregistration_sha256"),
        )


def _short(value: str | None) -> str | None:
    return None if value is None else value[:_SHORT]


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value
