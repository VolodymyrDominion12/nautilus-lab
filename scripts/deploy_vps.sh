#!/usr/bin/env bash
# Ship the committed code to the VPS and rebuild the containers.
#
#   VPS=lab@100.101.102.103 scripts/deploy_vps.sh
#
# Code goes one way (workstation -> VPS); data goes the other (scripts/pull_vps.sh).
# Only committed code is shipped: a paper ledger must be traceable to a revision, and
# `git archive` of HEAD is exactly that revision — no stray local edits, no .env, no
# catalog. The revision is written to DEPLOYED_REVISION on the server.
#
# The running paper session is NOT stopped: the API restarts, finds the unfinished
# session in the journal and resumes it (docs/26-deploy-vps.md).
set -euo pipefail
cd "$(dirname "$0")/.."

: "${VPS:?set VPS=user@host}"
REMOTE_DIR="${REMOTE_DIR:-nautilus-lab}"  # relative to the SSH user home

if [[ -n "$(git status --porcelain --untracked-files=no)" && "${ALLOW_DIRTY:-0}" != "1" ]]; then
    echo "Uncommitted changes. Commit first (or ALLOW_DIRTY=1 to ship HEAD anyway)." >&2
    exit 1
fi
REV="$(git rev-parse --short HEAD)"
# The full revision is baked into the image as LAB_REVISION: the container has no .git,
# and every run/paper session records it as its provenance (docs/27 E-1.4).
FULL_REV="$(git rev-parse HEAD)"
echo "Deploying $REV to $VPS:$REMOTE_DIR"

git archive --format=tar HEAD | ssh "$VPS" "
    set -e
    mkdir -p $REMOTE_DIR && cd $REMOTE_DIR
    tar -xf -
    echo $REV > DEPLOYED_REVISION
    mkdir -p data reports catalog
    test -f .env || { echo 'missing .env on the server: cp deploy/vps.env.example .env and edit it'; exit 1; }
    test -f deploy/.env || { echo 'missing deploy/.env: cp deploy/compose.env.example deploy/.env and edit it'; exit 1; }
    # An exposed dashboard without a lock hands the API token to anyone (deploy/Caddyfile).
    ALLOW_OPEN_DASHBOARD=${ALLOW_OPEN_DASHBOARD:-0} sh deploy/check_exposure.sh deploy/.env
    # data/ reports/ catalog/ must be writable by the container's user (APP_UID/APP_GID,
    # default 1001, deploy/Dockerfile.api). Wrong owner is caught at startup by ensure_journal_writable.
    #   sudo chown -R 1001:1001 data reports catalog
    LAB_REVISION=$FULL_REV docker compose -f deploy/docker-compose.yml up -d --build --remove-orphans
    docker compose -f deploy/docker-compose.yml ps
"
echo "Done. Logs: ssh $VPS 'cd $REMOTE_DIR && docker compose -f deploy/docker-compose.yml logs -f api'"
