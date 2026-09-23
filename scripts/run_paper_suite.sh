#!/usr/bin/env bash
# Paper-session suite: one forward session per candidate robot, written to reports/paper/.
# No parameter selection happens here unless --select-on-is is passed by the caller:
# these are the configurations as the lab ships them.
set -u
cd "$(dirname "$0")/.."
LAB=.venv/bin/lab
OUT=reports/paper
mkdir -p "$OUT"
for robot in regime ema pairs ml_obi meta_label; do
  echo "=== $robot $(date -u +%H:%M:%S) ==="
  timeout 1800 nice -n 10 "$LAB" paper --robot "$robot" --bars 1500 --journal >"$OUT/$robot.txt" 2>&1
  echo "$robot exit=$? $(date -u +%H:%M:%S)"
  head -4 "$OUT/$robot.txt"
done
