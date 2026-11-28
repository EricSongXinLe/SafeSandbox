# SafeSandbox

ECE 117 study of native coding-agent authorization, layered access
control, and persistent interaction. Start with the
[revised native-agent research design](docs/native_agent_research_revision.md), the
[native pilot operator manual](docs/native_authorization_pilot.md), or the historical
[research plan](docs/session_benchmark.md). The existing
[final presentation brief](docs/final_project_brief.md) remains part of the record.

| Suite | Evidence | Operator manual |
| --- | --- | --- |
| A | 48 verified infrastructure and fictional judgment trials | [GCP grid](docs/gcp_vm_experiment.md) |
| B | 24 planned trusted-client enforcement trials and a separate in-memory mutation check | [Defensive GCP campaign](docs/gcp_defensive_suite_b.md) |
| C | 12 verified native Codex authorized-task trials | [Native authorized tasks](docs/gcp_native_agent_experiment.md) |
| D | 72 verified single-turn fictional decisions and a separate 36-session three-turn follow-up | [Behavioral campaign](docs/behavioral_suite_d.md) |
| Native pilot | 12-session formal plan plus a separate four-session response-conditioned plan; live collection requires explicit confirmation | [Native authorization pilot](docs/native_authorization_pilot.md) |
| Native comparative | 36 matched formal sessions planned, with a separate six-session smoke prerequisite | [Comparative evaluation and operator commands](docs/native_comparative_evaluation.md) |

## Local checks

Run the regression tests without launching agents or creating VMs:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Freeze and preview the native formal pilot without launching a model or VM:

```bash
python3 scripts/run_native_pilot.py plan \
  --output runs/native-pilot-formal --model YOUR_APPROVED_MODEL --design formal
python3 scripts/run_native_pilot.py preview --campaign runs/native-pilot-formal
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
Use `plan --design multi-turn` for the three-turn follow-up.

## Earlier single-turn study

The [prompt specification](docs/experiment_prompts.md) documents the original
single-turn designs. Keep their results separate from the multi-turn GCP
benchmark. [Historical Ubuntu smoke test](docs/gcp_smoke_test_recap.md)
