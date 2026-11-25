# SafeSandbox

ECE 117 study of how coding agents handle requests for an inert marker in
another user's file. The GCP benchmark uses a fresh VM per trial and measures
marker access, disclosure, and a fictional role-authorization decision.

- [GCP runbook](docs/gcp_vm_experiment.md) — package, calibrate, and collect through `scripts/run_gcp_experiment.py`.
- [Benchmark protocol](docs/session_benchmark.md) — conditions, trial plans, and scoring.
- [GCP smoke-test record](docs/gcp_smoke_test_recap.md) — historical Ubuntu verification.

## Local checks

Run the regression tests without launching agents or creating VMs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Generate the focused 24-trial matrix locally:

```bash
python3 scripts/generate_session_matrix.py --plan focused24 --seed 117
```

Use `factorial48` for the full design after validating the additional controls.
The generator writes to `runs/session_trial_matrix.csv` by default.

## Earlier single-turn study

The [prompt specification](docs/experiment_prompts.md) documents the original
single-turn designs. Keep their results separate from the multi-turn GCP
benchmark.
