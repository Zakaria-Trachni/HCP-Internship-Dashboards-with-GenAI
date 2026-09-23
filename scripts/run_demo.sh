#!/usr/bin/env bash
# End-to-end demo: generate a sample dataset, then run the pipeline on it.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo "[demo] No .env found, copying .env.example -> .env"
  cp .env.example .env
  echo "[demo] Edit .env to set your GROQ_API_KEY (or switch to ollama) and re-run."
  exit 1
fi

mkdir -p data runs

if [ ! -f data/sample_sales.csv ]; then
  echo "[demo] Generating sample dataset..."
  python scripts/generate_sample_data.py --out data/sample_sales.csv
fi

echo "[demo] Running pipeline on data/sample_sales.csv ..."
python -m src.pipeline data/sample_sales.csv

echo
echo "[demo] Done. Inspect the latest run directory under ./runs/"
