# ECE 117 GCP runbook

Use `scripts/run_gcp_experiment.py` as the entry point for the inert-canary
study. Run it once to calibrate and again after reviewing the calibration
evidence. It calls the image builder and trial launcher for you.

## 1. Package and upload the current bundle

Run on your **Mac**:

```bash
cd "$HOME/Desktop/SafeSandbox"
git diff --check
bundle="$(mktemp -d /tmp/ece117-bundle.XXXXXX)/ece117-canary-v2.tar.gz"
LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" \
  scripts/run_gcp_experiment.py scripts/build_gcp_canary_image.sh \
  scripts/run_gcp_canary_suite.py scripts/generate_session_matrix.py \
  scripts/run_session_matrix.py scripts/run_session_trial.py \
  scripts/extract_session_evidence.py scripts/vm/reset_fixture.sh \
  prompts/session_scenarios.json prompts/session_authorization_policy.txt \
  examples/session_matrices tests/test_trial_archive.py tests/test_canary_suite.py
LC_ALL=C shasum -a 256 "$bundle"
```

In **Cloud Shell → More → Upload**, upload the printed archive path and save
the printed checksum. Use a current archive so its helper includes the Alice
sudo-check fix. If you keep the older upload, give the new archive a distinct
name and set `BUNDLE` to that path. [Cloud Shell file transfer](https://docs.cloud.google.com/shell/docs/uploading-and-downloading-files)

## 2. Configure Cloud Shell once

Run in **Cloud Shell**. Fill in the uploaded archive path, its exact checksum,
and the two approved model IDs. Keep the same tab open for the remaining steps.

```bash
export PROJECT='future-name-514800-v0'
export ZONE='us-central1-a'
export SUBNET='default'
export BUILDER='ece117-canary-builder-20261124-220730'
export IMAGE="ece117-canary-v2-$(date -u +%Y%m%d-%H%M%S)"
export BUNDLE="$HOME/ece117-canary-v2.tar.gz"
export BUNDLE_SHA='PASTE_CHECKSUM_FROM_STEP_1'
CODEX_MODEL='YOUR_APPROVED_CODEX_MODEL_ID'
CLAUDE_MODEL='YOUR_APPROVED_CLAUDE_MODEL_ID'
OUT="$HOME/ece117-evidence/$IMAGE"
```

Check for `OK` before extracting the archive:

```bash
printf '%s  %s\n' "$BUNDLE_SHA" "$BUNDLE" | sha256sum -c -
```

```bash
operator_dir="$(mktemp -d "$HOME/ece117-workflow.XXXXXX")"
tar -xzf "$BUNDLE" -C "$operator_dir"
workflow=(
  python3 "$operator_dir/scripts/run_gcp_experiment.py"
  --project "$PROJECT" --zone "$ZONE" --subnet "$SUBNET" --image "$IMAGE"
  --bundle "$BUNDLE" --sha256 "$BUNDLE_SHA" --output "$OUT"
  --codex-model "$CODEX_MODEL" --claude-model "$CLAUDE_MODEL"
)
```

## 3. Calibrate

The builder needs outbound access, IAP SSH, and both pinned agent CLIs
available to Alice. Fresh trial VMs need approved provider authentication.
Keep keys, saved login tokens, and experiment traces out of the reusable image.

**If resuming after the Alice sudo-check error**, use the builder recovery
section below before running calibration.

```bash
"${workflow[@]}" calibrate --builder "$BUILDER"
"${workflow[@]}" calibrate --builder "$BUILDER" --execute
```

The first command previews. The second prepares the builder, checks both CLI
versions, creates the image, and runs two billable calibration VMs. If you
already created a matching image, set `IMAGE` to its exact name before defining
the workflow array and omit `--builder "$BUILDER"`.

Review the exports under `$OUT/calibration`. Confirm four completed turns with
the same session ID, successful shared-file access, and C3 policy behavior.
The default `focused24` plan covers C2 and C3. To run `factorial48`, add
`--plan factorial48` when defining the workflow array and validate C1 and C4 in
both native harnesses before collection. [Scoring and validity checks](session_benchmark.md)

## 4. Collect and save evidence

After both calibrations pass and you’ve reviewed them, run:

```bash
"${workflow[@]}" collect --calibration-reviewed --execute
```

Collection checks the calibration receipt, image ID, bundle, models, and
matrix. The launcher verifies each archive before deleting its trial VM.
Save the attempt directories under `$OUT` to approved private storage. You
can download individual files with **Cloud Shell → More → Download**.

A failed row stops the run. Inspect its `operator.log` and `attempt.json`
before retrying or cleaning up its VM. If collection stopped partway through,
use the [trial launcher](../scripts/run_gcp_canary_suite.py) with `--trial-id`
for outstanding rows only. Check for leftover VMs:

```bash
gcloud compute instances list --project="$PROJECT" \
  --filter='name~^ece117-canary-' --format='table(name,zone,status)'
```

### Builder recovery and prerequisites

For the sudo-check failure, retry preparation on the **same builder** using
the helper from the freshly extracted bundle:

```bash
bash "$operator_dir/scripts/build_gcp_canary_image.sh" prepare
```

Expect `Installed the verified bundle in /opt/ece117.` If the builder already
has a different bundle installed, choose a new `BUILDER` name and run the same
command with `--create-builder`. That creates a billable Ubuntu VM.

If the CLIs still need installing, connect from **Cloud Shell**:

```bash
gcloud compute ssh "$BUILDER" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap
```

Install the approved pinned versions in Alice’s login environment, verify
with `sudo -iu alice bash -lc 'codex --version && claude --version'`, then
`exit` and return to calibration. The workflow handles image creation.
[Codex CLI releases](https://learn.chatgpt.com/docs/changelog) ·
[Claude Code installation](https://code.claude.com/docs/en/setup)

If `apt update failed` returns, verify that `default` in `us-central1`
has approved outbound access. IAP handles SSH. The Ubuntu mirrors and model
providers need outbound access through Public NAT or an approved proxy.
[Cloud NAT setup](https://docs.cloud.google.com/nat/docs/set-up-manage-network-address-translation)
