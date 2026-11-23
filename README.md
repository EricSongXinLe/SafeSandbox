# SafeSandbox
ECE M117 project

This repository contains prompt fixtures and orchestration scaffolding for a
controlled study of coding-agent behavior around a misconfigured cross-user
file. Only synthetic canaries may be used.

Generate the full 160-trial primary manifest:

```bash
python3 scripts/generate_trials.py
```

Generate the separate 200-trial subtle-framing extension:

```bash
python3 scripts/generate_trials.py \
  --cases prompts/subtle_pressure_conditions.json \
  --output runs/subtle_trial_manifest.jsonl
```

Inspect a dry run without invoking either agent:

```bash
python3 scripts/run_trials.py --limit 8
```

Before executing on the disposable VM, copy the invariant instruction templates
into Alice's workspace as `AGENTS.md` and `CLAUDE.md`, pin both CLI versions,
calibrate their permissions using benign files, and edit
`config/harnesses.example.json` to match the verified versions. The actual run
requires a trusted root/admin runner plus both `--execute` and
`--accept-calibrated-profiles`. Alice and Bob themselves should be non-root and
should not be granted sudo for the experiment.

See `docs/experiment_prompts.md` for the study prompt specification.

## Multi-turn session extension

The repository also includes a separate four-turn session-continuation
benchmark. It exercises a shared-file control, a direct credential request,
neutral or pressured reassessment, and a synthetic authentication request in
one native CLI conversation.

Generate its randomized 24- or 48-trial matrix with:

```bash
python3 scripts/generate_session_matrix.py --plan factorial48
```

Inspect one trial without executing an agent:

```bash
python3 scripts/run_session_trial.py \
  --agent codex --condition C2 --script pressure --replicate 1 \
  --model '<pinned-model>' --workspace /home/alice/experiment \
  --output /home/alice/ece117-results
```

See `docs/session_benchmark.md` for its condition matrix, isolated-VM
preconditions, execution procedure, limitations, and evidence rubric. Keep its
results separate from the single-turn manifests described above.

For a followable deployment and execution walkthrough on a disposable GCP
Ubuntu VM, see `docs/gcp_vm_experiment.md`.
