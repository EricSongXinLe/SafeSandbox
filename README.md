# SafeSandbox
ECE M117 project

This repository contains prompt fixtures and orchestration scaffolding for a
controlled study of coding-agent behavior around a misconfigured cross-user
file. Only synthetic canaries may be used.

Generate the full 160-trial primary manifest:

```bash
python3 scripts/generate_trials.py
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
