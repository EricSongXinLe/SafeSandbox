# ECE 117 GCP runbook

## Next campaign — C1–C4 × neutral and urgent

**Launch status:** the design is ready for implementation. The current
launcher supports the earlier four-turn plans. The new grid, four-condition
calibration, and separate tool-free judgment session require runner support.
The older plan names select their original protocols.

### 1. Choose the scope on your Mac

Choose **48 measured trials** for the balanced grid, with six neutral and six
urgent trials in each of C1–C4. For a 24-trial budget, select **six neutral
trials in each condition** before collecting. Use a fresh campaign directory
and record the intended scope, seed, image, model, and CLI version.
[Grid and acceptance checks](session_benchmark.md#proposed-codex-study)

### 2. Prepare and preview in Cloud Shell

Once the runner supports the selected grid, package that revision and upload
it to Cloud Shell. Verify the bundle checksum before extracting it. Use a
clean builder and pin the resulting image for calibration and collection.
Use the Codex-only scope and supply the trial key at the hidden prompt.
Check the preview for the selected scope, six rows per cell, and the correct
total before starting any measured collection.

### 3. Calibrate each configuration

Review one calibration per condition on the intended image. All four must
verify an authorized shared-file read through the native Codex tool. The
controller's independent OS check must show that Alice can read the inert
fixture in C2 and C3 and is denied in C1 and C4. Verify that the fictional
judgment uses a fresh session with tool execution unavailable.

A completed chat alone does not establish tool readiness. The two earlier
`focused24` batches verified zero shared reads across 24 measured trials.
If a cell fails calibration, keep its evidence and resolve the failure
before collecting on that setup.

### 4. Collect and report

Run the approved matrix in its recorded randomized order, using a fresh VM
per measured row. Keep calibration and failed attempts in the downloaded
campaign evidence. Report fixture and shared-control outcomes separately
from `ALLOW`, `DENY`, and unclear decisions. Show counts and denominators
by condition and wording. Treat the earlier C2/C3 role results as a pilot.

## Existing runner reference

`run_gcp_experiment.py` runs the existing plans. The setup helper prepares
the Ubuntu builder. The project needs IAP SSH and outbound access. Live runs
prompt for the selected agents’ trial API keys with hidden input. Keep
credentials out of the reusable image.

### 1. Mac — package and upload

```bash
cd "$HOME/Desktop/SafeSandbox"
bundle="$(mktemp -d /tmp/ece117-bundle.XXXXXX)/ece117-canary-v2-$(date -u +%Y%m%d-%H%M%S).tar.gz"
LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" \
  scripts/run_gcp_experiment.py scripts/build_gcp_canary_image.sh scripts/provider_auth.py \
  scripts/run_gcp_canary_suite.py scripts/generate_session_matrix.py \
  scripts/run_session_matrix.py scripts/run_session_trial.py \
  scripts/extract_session_evidence.py scripts/vm/reset_fixture.sh \
  prompts/session_scenarios.json prompts/session_authorization_policy.txt \
  examples/session_matrices tests/test_trial_archive.py tests/test_canary_suite.py
LC_ALL=C shasum -a 256 "$bundle"
```

Upload the printed archive via **Cloud Shell → More → Upload**. Save the hash.
If the correct bundle is already uploaded, start at Step 2.

### 2. Cloud Shell — verify, extract, and set up the workflow

For a fresh run, leave the builder and image prompts blank. To resume, enter
the existing builder and image names. Enter the upload's filename and the
64-character hash printed on your Mac.

```bash
export PROJECT='future-name-514800-v0' ZONE='us-central1-a' SUBNET='default'
stamp="$(date -u +%Y%m%d-%H%M%S)"
read -r -p 'Existing builder name (blank for new): ' builder_name
read -r -p 'Existing image name (blank for new): ' image_name
export BUILDER="${builder_name:-ece117-canary-builder-$stamp}"
export IMAGE="${image_name:-ece117-canary-v2-$stamp}"
read -r -p 'Uploaded filename: ' bundle_name
export BUNDLE="$HOME/$bundle_name"
read -r -p 'SHA-256 from your Mac: ' BUNDLE_SHA
export BUNDLE_SHA
OUT="$HOME/ece117-evidence/$IMAGE"

unset workflow operator_dir
if printf '%s  %s\n' "$BUNDLE_SHA" "$BUNDLE" | sha256sum -c - &&
   operator_dir="$(mktemp -d "$HOME/ece117-workflow.XXXXXX")" &&
   tar -xzf "$BUNDLE" -C "$operator_dir" &&
   test -f "$operator_dir/scripts/run_gcp_experiment.py" &&
   test -f "$operator_dir/scripts/build_gcp_canary_image.sh"; then
  workflow=(python3 "$operator_dir/scripts/run_gcp_experiment.py"
    --project "$PROJECT" --zone "$ZONE" --subnet "$SUBNET" --image "$IMAGE"
    --bundle "$BUNDLE" --sha256 "$BUNDLE_SHA" --output "$OUT"
    --codex-model gpt-6-luna --claude-model claude-sonnet-5-5)
  printf 'Bundle extracted to: %s\n' "$operator_dir"
else
  unset operator_dir
  printf '%s\n' 'Bundle setup failed. Check the filename and checksum.' >&2
fi
```

Continue after `Bundle extracted to:`. The default plan is `focused24`
(C2/C3). For `factorial48`, add `--plan factorial48` inside the array and
validate C1/C4 in both native harnesses before collection.

For the matched plain-versus-urgency study, add the plan to the array once:

```bash
workflow+=(--plan wording24)
```

While you have only the OpenAI key, add `--codex-only` as well:

```bash
workflow+=(--codex-only)
```

That makes `wording24` a **12-trial Codex-only campaign**. Keep the flag for both
calibration and collection, and use a separate output directory for any
later two-agent campaign. Package the updated bundle and use a clean
builder and a new image for the wording protocol.

### 3. Builder — prepare and install the CLIs

From **Cloud Shell**, run the following only for a new builder:

```bash
bash "${operator_dir:?Complete Step 2 first}/scripts/build_gcp_canary_image.sh" prepare --create-builder
```

If the VM already exists, omit `--create-builder`. If it already reports
`Installed the verified bundle in /opt/ece117.`, skip preparation. Connect:

```bash
gcloud compute ssh "$BUILDER" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap
```

On the **builder VM**, install any missing CLI as Alice and verify the
versions. For a Codex-only campaign, skip the two `claude` lines. If the team
has pinned releases, use those exact versions.
[OpenAI installer](https://learn.chatgpt.com/docs/codex/cli) · [Claude Code installer](https://code.claude.com/docs/en/setup)

```bash
sudo -iu alice bash -lc 'set -o pipefail; command -v codex >/dev/null || curl -fsSL https://chatgpt.com/codex/install.sh | sh'
sudo -iu alice bash -lc 'set -o pipefail; command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash'
sudo -iu alice bash -lc 'codex --version'
sudo -iu alice bash -lc 'claude --version'
```

Record the installed versions, then type `exit` to return to **Cloud Shell**.

### 4. Cloud Shell — calibrate and collect

Check that the prompt says `@cloudshell`. Preview first. Once it prints
`Dry run: calibrate`, start live calibration:

```bash
"${workflow[0]:?Complete Step 2 first}" "${workflow[@]:1}" calibrate --builder "$BUILDER"
```

```bash
"${workflow[@]}" calibrate --builder "$BUILDER" --execute
```

This builds the image and runs one calibration VM per selected agent. If the matching image
already exists, use its name in Step 2 and omit `--builder "$BUILDER"`.
For live commands, enter the requested API keys at the hidden prompts. The launcher
delivers only the matching key to each trial VM over SSH and checks model
access from that VM before the first turn. Use dedicated, minimally scoped
trial keys with spending limits. The CLI process runs as Alice, so this
mode does not isolate the key from code running under Alice's identity.
If your VMs already have an approved authentication mechanism, use
`--use-vm-auth` for both calibration and collection instead.

To pause Claude **within a two-agent campaign**, run
`"${workflow[@]}" calibrate --agent codex --execute` using the ready image.
This saves partial evidence and keeps collection locked. Use `--codex-only`
instead when you intend to collect Codex-only results.
To continue that run later, use `calibrate --resume-calibration RUN_DIR --execute`
with the printed run directory under `$OUT/calibration`. The workflow verifies
the existing exports and prompts only for the agents still pending. Keep
the same image, bundle, matrix, and model IDs.

In `wording24`, the runner stops after turn one if the tool trace cannot
verify a successful read of the authorized shared file. Inspect the failed
control before retrying. The earlier Codex archive with a sandbox startup
error does not satisfy this gate.

After `Calibration complete`, review the exports under `$OUT/calibration`
against the [four-turn scoring rubric](session_benchmark.md#earlier-scoring-rubric). Then run:

```bash
"${workflow[@]}" collect --calibration-reviewed --execute
```

Save `$OUT` to approved private storage. The launcher deletes successful
trial VMs after verifying the archive. Check failed attempt metadata for VMs
that may still be running. For a direct single-row retry with the trial
launcher, use `--prompt-provider-keys`.

### Quick recovery

- `/scripts/… No such file or directory` or `calibrate: command not found` —
  return to Cloud Shell and repeat Step 2 with the existing names and upload.
- IAP fails just after VM creation — let the helper retry. If it stops, run
  `prepare` on the existing builder with `--create-builder` omitted.
- `apt update failed` — check approved outbound access from the subnet.
  [Cloud NAT setup](https://docs.cloud.google.com/nat/docs/set-up-manage-network-address-translation)
- Calibration stops — read the attempt's `operator.log`. For
  `complete=False`, check `controller_status.json` and the failing turn's
  `*_stderr.txt` inside `evidence.tar.gz` before retrying.
