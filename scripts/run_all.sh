#!/usr/bin/env bash
# Full pipeline against the frozen code, in dependency order.
#
# Run this rather than the individual scripts when producing the numbers that
# get reported: it guarantees the evaluation, ablation and sensitivity sweep all
# ran against the same code, and that the report and dashboard were rendered
# from those exact artefacts.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=./.venv/bin/python

echo "=============================================================="
echo " KINTSUGI FULL PIPELINE   $(date '+%Y-%m-%d %H:%M:%S')"
echo " commit $(git rev-parse --short HEAD)"
echo "=============================================================="

echo; echo ">>> [1/5] tests"
$PY -m pytest -q

echo; echo ">>> [2/5] evaluation"
$PY -u -m scripts.run_evaluation --seeds 20 --payments 12000 --customers 3000

echo; echo ">>> [3/5] ablation"
$PY -u -m scripts.run_ablation --seeds 8 --payments 6000 --customers 2000

echo; echo ">>> [4/5] sensitivity sweep"
$PY -u -m scripts.run_sensitivity --seeds 6 --payments 6000 --customers 2000

echo; echo ">>> [5/5] report and dashboard"
$PY -m scripts.render_report
$PY -m scripts.build_dashboard

echo; echo "=============================================================="
echo " PIPELINE COMPLETE   $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================================="
