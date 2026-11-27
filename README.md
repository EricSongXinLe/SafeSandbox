# SafeSandbox

ECE 117 study of how Linux access controls and trusted policy affect coding
agents. The proposed Codex study measures OS access, native tool readiness,
and fictional authorization decisions separately on fresh VMs.

- [GCP runbook](docs/gcp_vm_experiment.md) — launch criteria for the proposed grid and operator steps for the existing runner.
- [Benchmark implementation plan](docs/session_benchmark.md) — proposed grid, calibration checks, and the earlier scoring rubric.
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

`factorial48` is the existing two-agent plan. The proposed Codex grid is
documented under [Proposed Codex study](docs/session_benchmark.md#proposed-codex-study)
and requires runner support. The generator writes to
`runs/session_trial_matrix.csv` by default.

## Earlier single-turn study

The [prompt specification](docs/experiment_prompts.md) documents the original
single-turn designs. Keep their results separate from the multi-turn GCP
benchmark.
