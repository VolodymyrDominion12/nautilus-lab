#!/bin/sh
# Keep one bounded live-tick collection running per symbol, forever.
# Each window ends by itself (TICK_WINDOW_MINUTES), writes what it got, and restarts:
# a hung socket or a Binance disconnect costs at most one window, never the process.
set -u
SYMBOLS=$(echo "${TICK_SYMBOLS:-ETHUSDT}" | tr ',' ' ')
WINDOW="${TICK_WINDOW_MINUTES:-60}"

collect_forever() {
    symbol="$1"
    while true; do
        echo "$(date -u +%FT%TZ) $symbol: collecting ${WINDOW} min"
        lab ingest --trades --symbols "$symbol" --live-ticks "$WINDOW" \
            || echo "$(date -u +%FT%TZ) $symbol: window failed (exit $?), retrying in 30s"
        sleep 30
    done
}

for symbol in $SYMBOLS; do
    collect_forever "$symbol" &
done
wait
