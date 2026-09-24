#!/bin/sh
# Off-server backup of what the VPS produces, with restic (docs/27 E-1.7, docs/26 §7).
#
# Runs in the `backup` compose service (profile "backup"); the repository lives
# somewhere that is NOT this server: S3/B2/R2, an SFTP box, a restic REST server.
# `scripts/pull_vps.sh` stays the copy on the workstation; this one does not depend on
# the workstation being on.
#
#   RESTIC_REPOSITORY, RESTIC_PASSWORD      required (plus the backend's credentials)
#   BACKUP_PATHS                            relative to /backup (default below; the
#                                           ticks are there because no REST history
#                                           of them exists to download again)
#   BACKUP_EVERY_SECONDS                    3600
#   BACKUP_KEEP                             restic forget policy
#   BACKUP_HEARTBEAT_URL                    optional: GET after every good run, so the
#                                           uptime service alarms when backups stop
#   BACKUP_ONESHOT=1                        one round and exit (tests, manual runs)
#
# The paper journals are append-only JSONL and are backed up while they are written:
# at worst the last line of a file is torn, and the journal reader skips a torn line.
set -u

: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY (the repository must be off this server)}"
: "${RESTIC_PASSWORD:?set RESTIC_PASSWORD (without it the backup cannot be restored)}"

ROOT="${BACKUP_ROOT:-/backup}"
PATHS="${BACKUP_PATHS:-data/paper reports catalog/data/agg_trade catalog/data/orderbook}"
EVERY="${BACKUP_EVERY_SECONDS:-3600}"
KEEP="${BACKUP_KEEP:---keep-hourly 48 --keep-daily 30 --keep-weekly 26}"
HOST_TAG="${BACKUP_HOST:-nautilus-lab-vps}"
LAST_PRUNE=""

log() { echo "$(date -u +%FT%TZ) backup: $*"; }

ensure_repository() {
    if restic cat config >/dev/null 2>&1; then
        return 0
    fi
    log "repository not initialised yet; running restic init"
    restic init
}

existing_paths() {
    for item in $PATHS; do
        if [ -e "$ROOT/$item" ]; then
            printf '%s\n' "$ROOT/$item"
        fi
    done
}

one_round() {
    targets=$(existing_paths)
    if [ -z "$targets" ]; then
        log "nothing to back up under $ROOT ($PATHS)"
        return 1
    fi
    # shellcheck disable=SC2086 # word splitting of the path list is intended
    if ! restic backup --host "$HOST_TAG" --tag nautilus-lab $targets; then
        log "restic backup failed"
        return 1
    fi
    # Retention once a day: `--prune` rewrites packs, too heavy to repeat every hour.
    today=$(date -u +%F)
    if [ "$today" != "$LAST_PRUNE" ]; then
        # shellcheck disable=SC2086 # KEEP is a list of flags
        if restic forget --host "$HOST_TAG" --tag nautilus-lab --prune $KEEP; then
            LAST_PRUNE="$today"
        else
            log "restic forget/prune failed (the new snapshot is kept)"
        fi
    fi
    if [ -n "${BACKUP_HEARTBEAT_URL:-}" ]; then
        wget -q -T 10 -O /dev/null "$BACKUP_HEARTBEAT_URL" || log "heartbeat not delivered"
    fi
    log "ok"
    return 0
}

if ! ensure_repository; then
    log "cannot open or initialise $RESTIC_REPOSITORY"
    exit 1
fi

while true; do
    one_round
    status=$?
    if [ "${BACKUP_ONESHOT:-0}" = "1" ]; then
        exit "$status"
    fi
    sleep "$EVERY"
done
