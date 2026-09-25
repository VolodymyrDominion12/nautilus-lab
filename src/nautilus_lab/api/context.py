"""Everything one API process owns, built once per app (docs/27 E-2.1).

`create_app(cfg)` builds a `LabContext` and stores it on `app.state.lab`; routers take it
through the `Lab` dependency. Nothing here is a module global, so a test builds an app
from its own settings instead of patching `api/app.py`.

What is read once and what is read per request is deliberate:

* security (token, origins, role), health thresholds and the session registry are fixed
  at start. Changing API_TOKEN needs a restart, which is the point: a request must not be
  able to relax the gate it is being checked by.
* `settings()` is the provider the endpoints call per request. Without an explicit
  config it re-reads `.env`, as before, so a value saved through PUT /api/settings is
  used by the next run without a restart.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from nautilus_lab.api.health import HealthLimits, Heartbeat, Readiness, check_readiness
from nautilus_lab.api.jobs import JobManager
from nautilus_lab.api.live_paper_boot import registry_from_settings
from nautilus_lab.api.live_sessions import SessionRegistry
from nautilus_lab.api.paper_streamer import binance_history_loader
from nautilus_lab.api.security import ApiSecurity
from nautilus_lab.infrastructure.settings import Settings
from nautilus_lab.interfaces.composition import settings as settings_from_env

#: `<root>/src/nautilus_lab/api/context.py` -> `<root>`: reports/, specs/ and research/
#: live next to the package in both a checkout and the editable install in the image.
ROOT_DIR = Path(__file__).resolve().parents[3]


@dataclass(frozen=True, slots=True)
class LabContext:
    root: Path
    reports_dir: Path
    hypotheses_dir: Path
    specs_dir: Path
    security: ApiSecurity
    sessions: SessionRegistry
    health_limits: HealthLimits
    jobs: JobManager
    settings_provider: Callable[[], Settings]

    def settings(self) -> Settings:
        return self.settings_provider()

    def readiness(self) -> Readiness:
        hub = self.sessions.feed_hub
        return check_readiness(
            hub.status() if hub is not None else [],
            self.sessions.sessions.values(),
            now=time.time(),
            limits=self.health_limits,
        )

    def heartbeat(self) -> Heartbeat | None:
        cfg = self.settings()
        if not cfg.live_paper_heartbeat_url.strip():
            return None
        return Heartbeat(
            url=cfg.live_paper_heartbeat_url.strip(),
            fail_url=cfg.live_paper_heartbeat_fail_url.strip(),
            every_seconds=cfg.live_paper_heartbeat_seconds,
        )

    @classmethod
    def build(
        cls,
        cfg: Settings | None = None,
        *,
        root: Path = ROOT_DIR,
        jobs: JobManager | None = None,
    ) -> LabContext:
        provider: Callable[[], Settings] = settings_from_env if cfg is None else (lambda: cfg)
        start = provider()
        reports_dir = root / "reports"
        return cls(
            root=root,
            reports_dir=reports_dir,
            hypotheses_dir=root / "research" / "hypotheses",
            specs_dir=root / "specs" / "strategies",
            security=ApiSecurity.from_values(
                origins=start.api_allowed_origins,
                token=start.api_token,
                role=start.lab_role,
            ),
            # One journal per session when persistence is configured (LIVE_PAPER_JOURNAL /
            # LIVE_PAPER_SESSIONS_DIR), shared Binance feeds (api/live_sessions.py).
            sessions=registry_from_settings(
                start, root=root, history_loader=binance_history_loader
            ),
            health_limits=HealthLimits(
                message_timeout_seconds=start.live_paper_feed_timeout_seconds,
                closed_bar_slack_seconds=start.live_paper_closed_bar_slack_seconds,
                startup_grace_seconds=start.live_paper_feed_grace_seconds,
            ),
            jobs=jobs or JobManager(reports_dir=reports_dir, python=python_executable(root)),
            settings_provider=provider,
        )


def python_executable(root: Path) -> str:
    """The project's venv interpreter when there is one, else whatever `python` is."""
    venv = root / ".venv" / "bin" / "python"
    return str(venv) if os.path.exists(venv) else "python"


def lab(request: Request) -> LabContext:
    context: LabContext = request.app.state.lab
    return context


#: Route parameter type: `def endpoint(ctx: Lab) -> ...`.
Lab = Annotated[LabContext, Depends(lab)]
