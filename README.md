# SafeSandbox

ECE 117 study of authorization judgments under pressure, layered access
control, and native coding-agent utility. Start with the
[research plan](docs/session_benchmark.md) or the
[final presentation brief](docs/final_project_brief.md).

| Suite | Evidence | Operator manual |
| --- | --- | --- |
| A | 48 verified infrastructure and fictional judgment trials | [GCP grid](docs/gcp_vm_experiment.md) |
| B | 24 planned trusted-client enforcement trials and a separate in-memory mutation check | [Defensive GCP campaign](docs/gcp_defensive_suite_b.md) |
| C | 12 verified native Codex authorized-task trials | [Native authorized tasks](docs/gcp_native_agent_experiment.md) |
| D | 48 planned tool-free, matched fictional decisions | [Behavioral campaign](docs/behavioral_suite_d.md) |

## Local checks

Run the regression tests without launching agents or creating VMs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Freeze and preview the Suite D matrix locally using your approved OpenAI model ID.

```bash
printf 'Approved OpenAI Responses API model ID: '; IFS= read -r SUITE_D_MODEL
```

```bash
D_OUT="runs/ece117-behavioral-d-$(date -u +%Y%m%d-%H%M%S)"
python3 scripts/run_behavioral_suite.py plan --output "$D_OUT" --model "$SUITE_D_MODEL"
python3 scripts/run_behavioral_suite.py run --campaign "$D_OUT"
```

The preview uses no API key. See the
[behavioral manual](docs/behavioral_suite_d.md) for collection and recovery.

## Earlier single-turn study

The [prompt specification](docs/experiment_prompts.md) documents the original
single-turn designs. Keep their results separate from the multi-turn GCP
benchmark. [Historical Ubuntu smoke test](docs/gcp_smoke_test_recap.md)
