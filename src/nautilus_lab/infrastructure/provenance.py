"""Collect a `RunManifest`: git revision, lock hash, versions, settings and data fingerprint.

Every probe is best-effort and bounded. A missing `git`, a server image without `.git`,
an unreadable catalog — each becomes `None` in the manifest and a warning line, never an
exception: provenance is recorded to make a run checkable, and a run that refuses to
start because it cannot describe itself protects nothing.

Where the revision comes from, in order:

1. ``git`` in the repository (workstation, CI);
2. ``LAB_REVISION`` in the environment (the Docker image: `scripts/deploy_vps.sh`
   passes the shipped revision as a build argument, see `deploy/Dockerfile.api`);
3. a ``DEPLOYED_REVISION`` file at the repository root (written by the same script).

The settings hash covers the *effective* configuration — `.env` plus shell overrides —
with secrets left out: rotating an API key must not look like a different experiment,
and a hash of a secret is still not something to write into a tracked journal.

The catalog fingerprint hashes relative path + size of every file, not contents:
reading gigabytes of Parquet before each run is not acceptable, and path+size already
changes on any ingest. It also stays equal for the same data copied to another machine
(modification times would not).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from collections.abc import Iterable, Mapping
from functools import cache
from importlib import metadata
from pathlib import Path

from nautilus_lab.domain.provenance import RunManifest

#: The repository root: src/nautilus_lab/infrastructure/provenance.py -> parents[3].
REPO_ROOT = Path(__file__).resolve().parents[3]

REVISION_ENV = "LAB_REVISION"
REVISION_FILE = "DEPLOYED_REVISION"
_GIT_TIMEOUT_SECONDS = 5.0

#: Settings whose names contain these never enter the hash (lower-case match).
SECRET_MARKERS: tuple[str, ...] = ("token", "secret", "password", "api_key", "chat_id")


def collect_manifest(
    *,
    settings: Mapping[str, object] | None = None,
    catalog_paths: Iterable[str | Path] = (),
    repo_root: Path = REPO_ROOT,
    environ: Mapping[str, str] | None = None,
) -> RunManifest:
    """Describe the code, dependencies, settings and data of the run about to happen."""
    env = os.environ if environ is None else environ
    revision, dirty, source = code_revision(repo_root, env)
    catalogs = [Path(item) for item in catalog_paths]
    fingerprint, files = catalog_fingerprint(catalogs) if catalogs else (None, None)
    return RunManifest(
        code_revision=revision,
        code_dirty=dirty,
        revision_source=source,
        lock_sha256=file_sha256(repo_root / "uv.lock"),
        python_version=platform.python_version(),
        nautilus_version=_package_version("nautilus_trader"),
        settings_sha256=None if settings is None else settings_sha256(settings),
        catalog_fingerprint=fingerprint,
        catalog_files=files,
    )


@cache
def code_manifest() -> RunManifest:
    """Code-only provenance of this process, collected once.

    For long-running consumers (the live paper terminal): the code of a running process
    does not change, and a session's configuration is already frozen in its journal, so
    neither settings nor a catalog belong here.
    """
    return collect_manifest()


def code_revision(
    repo_root: Path, environ: Mapping[str, str]
) -> tuple[str | None, bool | None, str | None]:
    """(revision, dirty, source). Dirty is None when it cannot be known (no git)."""
    head = _git(repo_root, "rev-parse", "HEAD")
    if head:
        status = _git(repo_root, "status", "--porcelain", "--untracked-files=no")
        # `status` returning None means git failed after HEAD worked: unknown, not clean.
        dirty = None if status is None else bool(status.strip())
        return head.strip(), dirty, "git"
    from_env = environ.get(REVISION_ENV, "").strip()
    if from_env:
        # `git archive HEAD` ships exactly the committed tree, so a deployed image is
        # clean by construction.
        return from_env, False, "env"
    marker = repo_root / REVISION_FILE
    try:
        from_file = marker.read_text(encoding="utf-8").strip()
    except OSError:
        from_file = ""
    if from_file:
        return from_file, False, "file"
    return None, None, None


def settings_sha256(settings: Mapping[str, object]) -> str:
    """Stable hash of the effective settings, secrets excluded."""
    public = {
        str(key): value
        for key, value in settings.items()
        if not any(marker in str(key).lower() for marker in SECRET_MARKERS)
    }
    canonical = json.dumps(public, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def catalog_fingerprint(paths: Iterable[Path]) -> tuple[str | None, int | None]:
    """sha256 over (catalog, relative path, size) of every file; (None, None) if unreadable."""
    digest = hashlib.sha256()
    count = 0
    seen_any = False
    for root in paths:
        if not root.is_dir():
            continue
        seen_any = True
        try:
            entries = sorted(
                (item.relative_to(root).as_posix(), item.stat().st_size)
                for item in root.rglob("*")
                if item.is_file() and not item.name.startswith(".")
            )
        except OSError:
            return None, None
        digest.update(f"catalog:{root.name}\n".encode())
        for relative, size in entries:
            digest.update(f"{relative}\t{size}\n".encode())
            count += 1
    if not seen_any:
        return None, None
    return digest.hexdigest(), count


def file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
