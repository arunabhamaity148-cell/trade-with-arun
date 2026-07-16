# Research Platform v2.0

The research platform lives under `src/twa/research/` and is intentionally separated from the live orchestration, signal, risk, and Telegram paths.

## Modules

- `lab.py` — loads candles plus current funding / OI / orderbook snapshots and builds a reusable `ResearchSession`.
- `feature_discovery.py` — generates candidate features, scores predictive IC, measures sub-period stability, and flags redundancy against production features.
- `edge_validation.py` — runs in-sample vs out-of-sample validation, bootstrap significance, and threshold sensitivity checks for candidate strategies.
- `experiment_runner.py` — executes declarative experiments, computes a reproducibility hash, and persists config + results under `data/research/experiments/`.
- `walk_forward.py` — reusable rolling walk-forward harness for model or parameter validation.
- `concept_drift.py` — monitors whether feature-to-return relationships are degrading over time.
- `feature_drift.py` — checks whether input feature distributions have shifted enough to endanger old calibrations.
- `regime_lab.py` — compares regime-classification variants and reports regime-conditional edge.
- `calibration_pipeline.py` — trains and serializes a probability calibration model compatible with the production `ConfidenceCalibrator` loader.
- `benchmarking.py` — compares the production engine against baseline strategies over the same window.

## Inputs / Outputs

Inputs:
- historical candles from the existing adapters / replay path
- optional live `signals.jsonl` logs for drift and calibration work
- declarative experiment JSON configs for repeatable runs

Outputs:
- JSON reports under `data/research/`
- serialized calibrator model at `models/calibrator.joblib`
- CLI-readable experiment and benchmark summaries

## Promotion Boundary

Research modules do **not** mutate production settings, weights, thresholds, or models automatically.

Promotion flow:
1. run research module
2. review persisted report / metrics
3. manually approve a production change
4. separately update signal weights, risk thresholds, or replace `models/calibrator.joblib`

This keeps the live signal engine human-reviewed and auditable.

## CLI

- `twa research run-experiment --config path/to/experiment.json`
- `twa research benchmark --symbol BTCUSDT --timeframe 1h --days 30`
