"""Read and edit `.env` from the dashboard. Secrets go out masked and are never
overwritten by their own mask."""

from __future__ import annotations

from typing import Any

import dotenv
from fastapi import APIRouter, HTTPException

from nautilus_lab.api.context import Lab
from nautilus_lab.api.requests import SettingsUpdate
from nautilus_lab.api.responses import SettingsResponse, SettingsSchemaResponse
from nautilus_lab.api.settings_schema import (
    mask_secret,
    settings_schema_payload,
    validate_settings_update,
)

router = APIRouter()

SECRET_SETTING_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_URL")


def mask_settings(config: dict[str, str | None]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in config.items():
        if value is None:
            masked[key] = ""
            continue
        upper = key.upper()
        if (
            any(upper.endswith(suffix) for suffix in SECRET_SETTING_SUFFIXES)
            and "PATH" not in upper
        ):
            masked[key] = mask_secret(str(value))
        else:
            masked[key] = str(value)
    return masked


@router.get("/api/settings/schema", response_model=SettingsSchemaResponse)
def get_settings_schema() -> dict[str, Any]:
    return settings_schema_payload()


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings(ctx: Lab) -> dict[str, Any]:
    env_path = ctx.root / ".env"
    if not env_path.exists():
        env_path = ctx.root / ".env.example"
    config = dotenv.dotenv_values(env_path)
    return {"settings": mask_settings(dict(config))}


@router.put("/api/settings")
def update_settings(ctx: Lab, update: SettingsUpdate) -> dict[str, str]:
    try:
        validated = validate_settings_update(update.settings)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    env_path = ctx.root / ".env"
    env_path.touch(exist_ok=True)
    for key, value in validated.items():
        if (
            any(key.upper().endswith(suffix) for suffix in SECRET_SETTING_SUFFIXES)
            and "****" in value
        ):
            continue
        dotenv.set_key(env_path, key, str(value))
    return {"status": "success"}
