#!/bin/sh
# Nightly archive refresh (docs/34 P2): `lab refresh-data` once a day at REFRESH_AT_UTC.
#
# Binance publishes yesterday's daily archive files during the next day, so the run is
# placed after midnight UTC and staleness is judged with a few days of slack
# (--stale-days). The result goes to Telegram/webhook when TELEGRAM_* / ALERT_WEBHOOK_URL
# are set in .env; the exit code is logged either way.
set -u
AT="${REFRESH_AT_UTC:-01:30}"
ARGS="${REFRESH_ARGS:-}"

run_once() {
    echo "$(date -u +%FT%TZ) refresh-data: start ${ARGS}"
    # shellcheck disable=SC2086 # ARGS is a list of flags on purpose
    lab refresh-data $ARGS
    echo "$(date -u +%FT%TZ) refresh-data: exit $?"
}

if [ "${REFRESH_ON_START:-0}" = "1" ]; then
    run_once
fi

while true; do
    now=$(date -u +%s)
    next=$(date -u -d "today ${AT}" +%s)
    if [ "$next" -le "$now" ]; then
        next=$((next + 86400))
    fi
    echo "$(date -u +%FT%TZ) refresh-data: next run in $(((next - now) / 60)) min"
    sleep $((next - now))
    run_once
done
