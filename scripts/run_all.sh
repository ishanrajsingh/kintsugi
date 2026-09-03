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

echo; echo ">>> [1/7] tests"
$PY -m pytest -q

echo; echo ">>> [2/7] evaluation"
$PY -u -m scripts.run_evaluation --seeds 20 --payments 12000 --customers 3000

echo; echo ">>> [3/7] ablation"
$PY -u -m scripts.run_ablation --seeds 8 --payments 6000 --customers 2000

echo; echo ">>> [4/7] sensitivity sweep"
$PY -u -m scripts.run_sensitivity --seeds 6 --payments 6000 --customers 2000

echo; echo ">>> [5/7] detector open-loop vs closed-loop study"
$PY -u -m scripts.run_detector_study

echo; echo ">>> [6/7] contact frontier"
$PY -u -m scripts.run_contact_frontier --seeds 8 --payments 6000 --customers 2000

echo; echo ">>> [7/7] report and dashboard"
$PY -m scripts.render_report
$PY -m scripts.build_dashboard

echo; echo "=============================================================="
echo " PIPELINE COMPLETE   $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================================="
