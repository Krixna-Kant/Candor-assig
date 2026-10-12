#!/bin/sh
set -eu
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
if [ -x .venv/bin/python ]; then
  VENV=.venv/bin/python
else
  VENV=.venv/Scripts/python.exe
fi
"$VENV" -m pip install -q -r requirements.txt
export PYTHONUTF8=1
export PYTHONPATH="$(pwd)/src"
mkdir -p results
"$VENV" -m unittest tests.test_timeline tests.test_text tests.test_asof_sweep tests.test_actions \
  tests.test_hops tests.test_writer tests.test_slots
"$VENV" -m candor memory --questions evals/memory_train.jsonl --out outputs/memory_train.jsonl
"$VENV" eval_harness/score_retrieval.py \
  --gold evals/memory_train.jsonl \
  --answers outputs/memory_train.jsonl \
  --out results/retrieval.json
"$VENV" eval_harness/score_memory.py \
  --gold evals/memory_train.jsonl \
  --answers outputs/memory_train.jsonl \
  --judge none \
  --out results/memory.json
"$VENV" -m candor report \
  --gold evals/memory_train.jsonl \
  --answers outputs/memory_train.jsonl \
  --out results/failures.txt
"$VENV" -m candor actions --commands evals/actions_train.jsonl --out outputs/actions_train.jsonl
"$VENV" eval_harness/score_actions.py \
  --gold evals/actions_train.jsonl \
  --predictions outputs/actions_train.jsonl \
  --out results/actions.json
"$VENV" -m candor actions --commands evals/actions_extra.jsonl --out outputs/actions_extra.jsonl
"$VENV" eval_harness/score_actions.py \
  --gold evals/actions_extra.jsonl \
  --predictions outputs/actions_extra.jsonl \
  --out results/actions_extra.json
