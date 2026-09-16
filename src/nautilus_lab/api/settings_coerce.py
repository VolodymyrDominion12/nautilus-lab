from __future__ import annotations

from decimal import Decimal
from typing import Any

from nautilus_lab.infrastructure.settings import Settings


def _field_name(env_key: str) -> str | None:
    upper = env_key.upper()
    for name in Settings.model_fields:
        if name.upper() == upper:
            return name
    return None


def _coerce_value(field_name: str, raw: str) -> object:
    field = Settings.model_fields[field_name]
    annotation = field.annotation
    if annotation is bool:
        return raw.lower() in {"1", "true", "yes", "on"}
    if annotation is int:
        return int(raw)
    if annotation is Decimal:
        return Decimal(raw)
    if annotation is list[str]:
        import json

        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            msg = f"{field_name} expects a JSON list"
            raise ValueError(msg)
        return parsed
    return raw


def apply_setting_overrides(cfg: Settings, overrides: dict[str, str]) -> Settings:
    """Apply per-run .env-style overrides onto a Settings snapshot."""
    if not overrides:
        return cfg
    patch: dict[str, Any] = {}
    for env_key, raw in overrides.items():
        field_name = _field_name(env_key)
        if field_name is None:
            continue
        patch[field_name] = _coerce_value(field_name, raw)
    merged = cfg.model_dump()
    merged.update(patch)
    return Settings.model_validate(merged)
