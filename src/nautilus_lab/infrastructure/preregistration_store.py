"""`research/preregistrations/*.json`: registered test terms, one file each (R-2).

Files are written once and never rewritten. Each carries the hash of its own terms; a
file edited afterwards stops matching it and counts as tampered, not as a registration.
They are meant to be committed with the journal: the commit date is a second, outside
witness that the terms existed before the run.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from nautilus_lab.domain.preregistration import Preregistration, ResearchTerms


class JsonPreregistrationStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, registration: Preregistration) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = registration.registered_at.strftime("%Y%m%dT%H%M%SZ")
        name = f"{registration.terms.robot}-{stamp}-{registration.terms_sha256[:12]}.json"
        path = self.directory / name
        payload = {
            "schema": "preregistration/1",
            "registered_at": registration.registered_at.isoformat(),
            "hypothesis": registration.hypothesis,
            "terms_sha256": registration.terms_sha256,
            "terms": registration.terms.as_dict(),
        }
        # "x": a registration is never overwritten, even by an identical one.
        with path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        return str(path)

    def load_all(self) -> list[Preregistration]:
        if not self.directory.is_dir():
            return []
        found: list[Preregistration] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                terms = payload["terms"]
                if not isinstance(terms, dict):
                    continue
                found.append(
                    Preregistration(
                        terms=ResearchTerms.from_dict(terms),
                        hypothesis=str(payload.get("hypothesis", "")),
                        registered_at=datetime.fromisoformat(str(payload["registered_at"])),
                        terms_sha256=str(payload["terms_sha256"]),
                        source=path.name,
                    )
                )
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return found
