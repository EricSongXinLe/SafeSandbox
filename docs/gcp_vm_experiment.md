# ECE 117 GCP runbook

Use `run_gcp_experiment.py` for calibration and collection. The setup helper
prepares the Ubuntu builder. The project needs IAP SSH and outbound access.
Live runs prompt for dedicated OpenAI and Anthropic trial API keys with
hidden input. Keep credentials out of the reusable image.

## 1. Mac — package and upload

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

## 2. Cloud Shell — verify, extract, and set up the workflow

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
    --codex-model gpt-6.2-sol --claude-model claude-sonnet-5-5)
  printf 'Bundle extracted to: %s\n' "$operator_dir"
else
  unset operator_dir
  printf '%s\n' 'Bundle setup failed. Check the filename and checksum.' >&2
fi
```

Continue after `Bundle extracted to:`. The default plan is `focused24`
(C2/C3). For `factorial48`, add `--plan factorial48` inside the array and
validate C1/C4 in both native harnesses before collection.

## 3. Builder — prepare and install the CLIs

From **Cloud Shell**, run the following only for a new builder:

```bash
bash "${operator_dir:?Complete Step 2 first}/scripts/build_gcp_canary_image.sh" prepare --create-builder
```

If the VM already exists, omit `--create-builder`. If it already reports
`Installed the verified bundle in /opt/ece117.`, skip preparation. Connect:

```bash
gcloud compute ssh "$BUILDER" --project="$PROJECT" --zone="$ZONE" --tunnel-through-iap
```

On the **builder VM**, install any missing CLI as Alice and verify both
versions. If the team has pinned releases, use those exact versions.
[OpenAI installer](https://learn.chatgpt.com/docs/codex/cli) · [Claude Code installer](https://code.claude.com/docs/en/setup)

```bash
sudo -iu alice bash -lc 'set -o pipefail; command -v codex >/dev/null || curl -fsSL https://chatgpt.com/codex/install.sh | sh'
sudo -iu alice bash -lc 'set -o pipefail; command -v claude >/dev/null || curl -fsSL https://claude.ai/install.sh | bash'
sudo -iu alice bash -lc 'codex --version'
sudo -iu alice bash -lc 'claude --version'
```

Record both versions, then type `exit` to return to **Cloud Shell**.

## 4. Cloud Shell — calibrate and collect

Check that the prompt says `@cloudshell`. Preview first. Once it prints
`Dry run: calibrate`, start live calibration:

```bash
"${workflow[0]:?Complete Step 2 first}" "${workflow[@]:1}" calibrate --builder "$BUILDER"
```

```bash
"${workflow[@]}" calibrate --builder "$BUILDER" --execute
```

This builds the image and runs two calibration VMs. If the matching image
already exists, use its name in Step 2 and omit `--builder "$BUILDER"`.
For live commands, enter the two API keys when prompted. The launcher
delivers only the matching key to each trial VM over SSH and checks model
access from that VM before the first turn. Use dedicated, minimally scoped
trial keys with spending limits. The CLI process runs as Alice, so this
mode does not isolate the key from code running under Alice's identity.
If your VMs already have an approved authentication mechanism, use
`--use-vm-auth` for both calibration and collection instead.
After `Calibration complete`, review both exports under `$OUT/calibration`
against the [benchmark rubric](session_benchmark.md). Then run:

```bash
"${workflow[@]}" collect --calibration-reviewed --execute
```

Save `$OUT` to approved private storage. The launcher deletes successful
trial VMs after verifying the archive. Check failed attempt metadata for VMs
that may still be running. For a direct single-row retry with the trial
launcher, use `--prompt-provider-keys`.

## Quick recovery

- `/scripts/… No such file or directory` or `calibrate: command not found` —
  return to Cloud Shell and repeat Step 2 with the existing names and upload.
- IAP fails just after VM creation — let the helper retry. If it stops, run
  `prepare` on the existing builder with `--create-builder` omitted.
- `apt update failed` — check approved outbound access from the subnet.
  [Cloud NAT setup](https://docs.cloud.google.com/nat/docs/set-up-manage-network-address-translation)
- Calibration stops — read the attempt's `operator.log`. For
  `complete=False`, check `controller_status.json` and the failing turn's
  `*_stderr.txt` inside `evidence.tar.gz` before retrying.
