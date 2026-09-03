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

echo; echo ">>> [0/9] refit world + retrain predictors (slow; skip with FAST=1)"
if [ "${FAST:-0}" != "1" ]; then
  $PY -u -m kintsugi.world.fitting
  $PY -u -m scripts.train_predictor
else
  echo "    skipped"
fi

echo; echo ">>> [1/9] tests"
$PY -m pytest -q

echo; echo ">>> [2/9] evaluation"
$PY -u -m scripts.run_evaluation --seeds 20 --payments 12000 --customers 3000

echo; echo ">>> [3/9] ablation"
$PY -u -m scripts.run_ablation --seeds 8 --payments 6000 --customers 2000

echo; echo ">>> [4/9] sensitivity sweep"
$PY -u -m scripts.run_sensitivity --seeds 6 --payments 6000 --customers 2000

echo; echo ">>> [5/9] detector open-loop vs closed-loop study"
$PY -u -m scripts.run_detector_study

echo; echo ">>> [6/9] contact frontier"
$PY -u -m scripts.run_contact_frontier --seeds 8 --payments 6000 --customers 2000

echo; echo ">>> [7/9] external validation against published figures"
$PY -u -m scripts.run_external_validation

echo; echo ">>> [8/9] report and dashboard"
$PY -m scripts.render_report
$PY -m scripts.build_dashboard

echo; echo ">>> [9/9] compliance summary"
$PY -c "
import json
d = json.load(open('data/results.json'))
for name, row in d['summary_table'].items():
    print(f\"  {name:14s} violations={row.get('scheme_violations', 0):6.0f}  fines=INR {row.get('fines_paise', 0)/100:9,.0f}\")
"

echo; echo "=============================================================="
echo " PIPELINE COMPLETE   $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================================="
