#!/usr/bin/env bash
# Pull what the VPS produced into the workstation for research.
#
#   VPS=lab@100.101.102.103 scripts/pull_vps.sh
#
# Lands under data/vps/ (git-ignored), never on top of the local catalog:
#   data/vps/paper/live_events.jsonl         live paper journal (every fill + bar)
#   data/vps/catalog/data/agg_trade/...      live ticks from the collector
#   data/vps/reports/                        anything the server wrote to reports/
#
# Then:
#   uv run python scripts/live_paper_report.py data/vps/paper/live_events.jsonl
#   uv run lab research ... --catalog data/vps/catalog     (tick-based research)
#
# rsync only copies what changed, so running it hourly is cheap. The journal is
# append-only, so a copy taken mid-write at worst lacks its last line.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${VPS:?set VPS=user@host}"
REMOTE_DIR="${REMOTE_DIR:-nautilus-lab}"
DEST="${DEST:-data/vps}"

mkdir -p "$DEST/paper" "$DEST/catalog/data" "$DEST/reports"
rsync -az --info=stats1 "$VPS:$REMOTE_DIR/data/paper/" "$DEST/paper/"
rsync -az --info=stats1 "$VPS:$REMOTE_DIR/catalog/data/" "$DEST/catalog/data/" || true
rsync -az --info=stats1 "$VPS:$REMOTE_DIR/reports/" "$DEST/reports/" || true
ssh "$VPS" "cat $REMOTE_DIR/DEPLOYED_REVISION 2>/dev/null" > "$DEST/DEPLOYED_REVISION" || true
echo "Pulled into $DEST (server revision: $(cat "$DEST/DEPLOYED_REVISION" 2>/dev/null || echo unknown))"
