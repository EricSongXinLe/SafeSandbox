# SafeSandbox

ECE 117 study of how Linux access controls and trusted policy affect coding
agents. The Codex study measures OS access, native tool readiness,
and fictional authorization decisions separately on fresh VMs.

- [GCP fresh-start manual](docs/gcp_vm_experiment.md) — package, calibrate C1–C4, and collect the fixed 48-trial grid.
- [Native authorized-task manual](docs/gcp_native_agent_experiment.md) — Suite C calibration, a 12-trial native Codex campaign, and verified outcome reporting.
- [Benchmark implementation plan](docs/session_benchmark.md) — grid, calibration checks, and scoring.
- [GCP smoke-test record](docs/gcp_smoke_test_recap.md) — historical Ubuntu verification.

## Local checks

Run the regression tests without launching agents or creating VMs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Generate the fixed Codex grid locally:

```bash
python3 scripts/generate_session_matrix.py --plan codex-grid48 --seed 117 \
  --output runs/codex-grid48.csv
```

The matrix generator runs locally. The GCP launcher requires verified
calibration exports for C1–C4 before collecting this grid.

## Earlier single-turn study

The [prompt specification](docs/experiment_prompts.md) documents the original
single-turn designs. Keep their results separate from the multi-turn GCP
benchmark.
