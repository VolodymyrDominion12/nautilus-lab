"""Who may drive the dashboard API.

The API launches processes, rewrites `.env` and calls the LLM with the key from it.
It used to answer any origin (`allow_origins=["*"]` with credentials) and had no
authentication, so any web page open in the same browser could `PUT /api/settings`
(point `LLM_BASE_URL` at itself and collect `LLM_API_KEY` on the next proposal) or
start jobs. CORS alone does not stop that: a cross-site "simple" POST still reaches
the server, only its response is hidden from the page.

Two independent gates, both cheap:

* **Origin** — a browser always sends `Origin` on cross-site requests and WebSocket
  handshakes. A request that carries one must come from the dashboard's own origin.
  Requests without `Origin` (curl, scripts, tests) are not browser attacks.
* **Token** — optional. When `API_TOKEN` is set, every `/api` call must present it
  (`X-Lab-Token` header, or `?token=` for WebSockets, which cannot set headers).

Static report mounts are exempt from the token: the dashboard embeds tearsheets in an
iframe, which cannot send a header, and they hold nothing that changes state.

A third gate is about *where* the API runs rather than who calls it:

* **Role** — ``LAB_ROLE=paper`` marks a server that only runs the live paper terminal.
  Reads stay open (the dashboard needs them), and so do the live-paper controls; every
  other state-changing call — research, ingest, ML training, alpha proposals, the batch
  paper job, rewriting ``.env`` — is refused. Research belongs on the workstation,
  where its data and its compute are; a server that rewrites its own settings from a
  browser is a server whose ledger nobody can reproduce.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

DEFAULT_ALLOWED_ORIGINS: tuple[str, ...] = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    # The API's own origin: FastAPI's /docs page sends it on "Try it out" requests.
    "http://localhost:8000",
    "http://127.0.0.1:8000",
)
TOKEN_HEADER = "x-lab-token"

ROLE_FULL = "full"
ROLE_PAPER = "paper"
KNOWN_ROLES: frozenset[str] = frozenset({ROLE_FULL, ROLE_PAPER})

#: The only state-changing calls a `paper` server accepts: the live terminal controls.
PAPER_ROLE_WRITES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/paper/live/start"),
        ("POST", "/api/paper/live/stop"),
        ("POST", "/api/paper/live/close-position"),
        ("POST", "/api/paper/live/update-stops"),
        ("POST", "/api/paper/sessions"),
    }
)
#: Per-session controls: /api/paper/sessions/<id or name>/<action>.
_PAPER_SESSION_ACTION = re.compile(
    r"^/api/paper/sessions/[A-Za-z0-9._-]+/(stop|pause|resume|close-position|update-stops)$"
)
_READ_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})


def role_refusal(role: str, *, method: str, path: str) -> str | None:
    """Why a call is refused on this deployment role, or None when it may proceed."""
    if role != ROLE_PAPER:
        return None
    verb = method.upper()
    if verb in _READ_METHODS or not path.startswith("/api"):
        return None
    clean = path.rstrip("/")
    if (verb, clean) in PAPER_ROLE_WRITES:
        return None
    if verb == "POST" and _PAPER_SESSION_ACTION.match(clean):
        return None
    return (
        f"{verb} {path} is disabled on this server (LAB_ROLE=paper): it only runs the "
        "live paper terminal. Run research, ingest and ML on the workstation."
    )


@dataclass(frozen=True, slots=True)
class ApiSecurity:
    allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS
    token: str = ""
    role: str = ROLE_FULL

    def __post_init__(self) -> None:
        if self.role not in KNOWN_ROLES:
            # Fail closed: a typo in LAB_ROLE must not quietly mean "full".
            known = ", ".join(sorted(KNOWN_ROLES))
            raise ValueError(f"unknown LAB_ROLE {self.role!r}; expected one of: {known}")

    @classmethod
    def from_values(cls, *, origins: str, token: str, role: str = ROLE_FULL) -> ApiSecurity:
        parsed = tuple(item.strip().rstrip("/") for item in origins.split(",") if item.strip())
        return cls(
            allowed_origins=parsed or DEFAULT_ALLOWED_ORIGINS,
            token=token.strip(),
            role=role.strip().lower() or ROLE_FULL,
        )

    def refusal(
        self,
        *,
        method: str,
        path: str,
        origin: str | None,
        presented_token: str | None,
    ) -> str | None:
        """Why this request must be refused, or None when it may proceed."""
        if method.upper() == "OPTIONS":
            # Preflight: CORSMiddleware answers it and withholds headers from
            # origins it does not know, which is what makes the browser give up.
            return None
        if origin is not None and origin.rstrip("/") not in self.allowed_origins:
            return f"origin {origin!r} is not allowed to use this API"
        needs_token = bool(self.token) and path.startswith("/api")
        if needs_token and not (
            presented_token and hmac.compare_digest(presented_token, self.token)
        ):
            return "missing or invalid API token"
        return role_refusal(self.role, method=method, path=path)
