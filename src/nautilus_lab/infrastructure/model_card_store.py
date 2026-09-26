"""JSON sidecar for model cards: `<model file>.card.json` (domain/model_card.py)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from nautilus_lab.domain.model_card import ModelCard


def card_path(model_path: str | Path) -> Path:
    path = Path(model_path)
    return path.with_name(f"{path.name}.card.json")


def file_sha256(path: str | Path) -> str | None:
    target = Path(path)
    if not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_model_card(model_path: str | Path, card: ModelCard) -> Path:
    target = card_path(model_path)
    target.write_text(json.dumps(card.as_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
    return target


class JsonModelCardSource:
    """Reads cards next to model files. A corrupt card reads as no card (fail closed)."""

    def card_for(self, model_path: str) -> ModelCard | None:
        target = card_path(model_path)
        if not target.is_file():
            return None
        try:
            return ModelCard.from_dict(json.loads(target.read_text("utf-8")))
        except (ValueError, KeyError, TypeError):
            return None

    def sha256_of(self, model_path: str) -> str | None:
        return file_sha256(model_path)
