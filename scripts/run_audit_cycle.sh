#!/usr/bin/env bash
# Phase-1 audit sweep: walk-forward (4 folds) for every candidate paper robot.
# Writes one log per robot under reports/audit/. Numbers are recorded, never tuned.
set -u
cd "$(dirname "$0")/.."
LAB=.venv/bin/lab
OUT=reports/audit
mkdir -p "$OUT"
for robot in regime ema pairs vpin_momentum meta_label formulaic_lgbm; do
  echo "=== $robot $(date -u +%H:%M:%S) ==="
  timeout 3600 "$LAB" research --robot "$robot" --folds 4 >"$OUT/$robot.txt" 2>&1
  echo "$robot exit=$? $(date -u +%H:%M:%S)"
  tail -6 "$OUT/$robot.txt"
done
