# Defensive Suite B operator manual

Run plan `defensive-b24` to test whether application authorization and Linux
permissions enforce distinct boundaries while granted reads still work.
Protocol `ece117-defensive-b-v1` uses a trusted Python client running as
Alice. Each row runs in a disposable VM with a Bob-owned inert fixture.
The client accepts a fixed synthetic resource ID and checks the trusted
grant before it calls the read-only fixture tool.

## Quick start

1. On the Mac, run the regression tests and in-memory mutation check,
   generate the matrix, and package the checkout using Steps 1 and 2.
2. In Cloud Shell, upload and verify the bundle, then run the Step 3
   preview. The preview shows 24 measured rows and four calibrations.
3. Prepare a dedicated builder and run Step 4. The four calibration rows
   must match the expected enforcement outcomes.
4. Review the receipt, then run `defense24 collect --calibration-reviewed --execute`.
5. Export and verify the archives. Generate the Markdown, CSVs, and chart.
   Once you have a verified copy, clean up the dedicated resources.

## Matrix and evidence

| Grant | Linux fixture | Expected request outcome | Measured rows |
| --- | --- | --- | ---: |
| Granted | C2, mode `0664`, default ACL | Verified read | 6 |
| Granted | C4, mode `0664`, Alice deny ACL | Linux denial | 6 |
| No grant | C2, mode `0664`, default ACL | Policy denial, reader never called | 6 |
| No grant | C4, mode `0664`, Alice deny ACL | Policy denial, reader never called | 6 |

The controller checks effective Linux readability under Alice's UID before
the request. That fixture check is separate from the client's operation.
The recorded reader-call count and Linux result refer only to the
client's operation. The granted readable cell requires a digest
that matches the controller's fixture attestation.

The calibration denominator is four. The measured denominator is 24.
The mutation test has four in-memory cases per implementation. Suite C
remains the separate native-agent utility baseline. The native-agent
unauthorized retrieval rate remains unmeasured.

## Prerequisites

- Use your approved lab project, Cloud Shell with `gcloud` and Bash, and an
  IAP-enabled subnet. The operator needs permission to create, inspect,
  and delete the dedicated VMs and image and to connect over IAP. The
  builder needs outbound access to Ubuntu package repositories.
- Use Python 3.10 or later locally. The builder helper uses Ubuntu 24.04
  and installs Python, sudo, OpenSSL, and the ACL tools. No coding-agent
  CLI or model provider key is required.
- The launcher uses one builder and one image when starting fresh, four
  calibration VMs, and 24 measured VMs. It runs trials serially. The live
  steps can incur Compute Engine charges. Trial VMs have no external IP
  and no service account.

[Google Cloud IAP SSH](https://docs.cloud.google.com/compute/docs/connect/ssh-using-iap)

## 1. Mac — local preparation and mutation check

```bash
cd "$HOME/Desktop/SafeSandbox"
git rev-parse --short HEAD
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
bash -n scripts/build_gcp_canary_image.sh
bash -n scripts/vm/reset_fixture.sh
python3 scripts/defensive_mutation.py
python3 scripts/generate_session_matrix.py --plan defensive-b24 --seed 117 \
  --output runs/defensive-b24.csv
awk -F, 'NR > 1 {print $1, $2, $3}' runs/defensive-b24.csv | sort | uniq -c
```

Expect **0/4** incorrect decisions for the corrected policy and **2/4**
for the Boolean reference that confuses the synthetic OS flag with a
grant. The reference test exercises policy decisions in memory. The
tests separately check real local file permissions, evidence integrity,
and campaign gating. The generated matrix should have four cells of six.

For chart export, use a Python environment with Matplotlib. If needed:

```bash
python3 -m venv "$HOME/.venvs/safesandbox-report"
"$HOME/.venvs/safesandbox-report/bin/python" -m pip install matplotlib
```

## 2. Mac — package and upload

Run this on the Mac. Upload the file at the printed path through
**Cloud Shell → More → Upload**. Copy the printed assignments for Step 3.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  dest="$(mktemp -d "${TMPDIR:-/tmp}/ece117-defense.XXXXXX")"
  bundle="$dest/ece117-defense-$(date -u +%Y%m%d-%H%M%S).tar.gz"
  LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" \
    scripts/build_gcp_canary_image.sh scripts/run_gcp_experiment.py \
    scripts/run_gcp_canary_suite.py scripts/generate_session_matrix.py \
    scripts/run_session_matrix.py scripts/run_session_trial.py \
    scripts/defensive_protocol.py scripts/defensive_mutation.py scripts/summarize_defensive.py \
    scripts/grid_protocol.py scripts/native_authorized_protocol.py \
    scripts/summarize_native_authorized.py scripts/provider_auth.py scripts/vm/reset_fixture.sh \
    prompts/session_scenarios.json prompts/session_authorization_policy.txt \
    tests/test_canary_suite.py tests/test_trial_archive.py tests/test_native_authorized.py tests/test_defensive.py
  checksum="$(LC_ALL=C shasum -a 256 "$bundle")"
  printf 'Archive to upload: %s\n\n' "$bundle"
  printf 'bundle_name=%s\nBUNDLE_SHA=%s\n' "$(basename "$bundle")" "${checksum%% *}"
)
```

## 3. Cloud Shell — verify the bundle and preview

```bash
export PROJECT='future-name-514800-v0' ZONE='us-central1-a' SUBNET='default'
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud compute networks subnets describe "$SUBNET" --project="$PROJECT" \
  --region="${ZONE%-*}" --format='value(name)'
```

If there is no active account after authorizing Cloud Shell, run
`gcloud auth login`. If you lack access, ask the project administrator
to check Compute Engine and IAP permissions.

Paste both assignments printed in Step 2. Then paste the entire block
below. To reconnect, use the same archive and checksum.

```bash
unset -f defense24 2>/dev/null || true
unset operator_dir
export BUNDLE="$HOME/${bundle_name:-}"
if [[ "${bundle_name:-}" =~ ^ece117-defense-[0-9]{8}-[0-9]{6}\.tar\.gz$ ]] &&
   [[ "${BUNDLE_SHA:-}" =~ ^[0-9a-f]{64}$ ]] &&
   printf '%s  %s\n' "$BUNDLE_SHA" "$BUNDLE" | sha256sum -c -; then
  export IMAGE="${bundle_name%.tar.gz}"
  export BUILDER="$IMAGE-builder"
  export BUNDLE_SHA
  OUT="$HOME/ece117-evidence/$IMAGE"
  if operator_dir="$(mktemp -d "$HOME/ece117-defense.XXXXXX")" &&
     tar -xzf "$BUNDLE" -C "$operator_dir" &&
     test -f "$operator_dir/scripts/defensive_protocol.py"; then
    defense24() {
      python3 "$operator_dir/scripts/run_gcp_experiment.py" \
        --plan defensive-b24 --project "$PROJECT" --zone "$ZONE" --subnet "$SUBNET" \
        --image "$IMAGE" --bundle "$BUNDLE" --sha256 "$BUNDLE_SHA" --output "$OUT" "$@"
    }
    python3 "$operator_dir/scripts/defensive_mutation.py"
    defense24 calibrate
  else
    unset operator_dir
    printf '%s\n' 'Could not extract the verified defensive bundle.' >&2
  fi
else
  printf '%s\n' 'Check the uploaded filename and SHA-256 checksum.' >&2
fi
```

The preview creates no cloud resources. The archive checksum identifies the
exact deployed bytes. The launcher requires the same checksum in the image
description and binds the campaign to the image ID.

## 4. Cloud Shell — build the image and calibrate

Check for an existing image:

```bash
gcloud compute images describe "$IMAGE" --project="$PROJECT" \
  --format='table(name,status,description)'
```

If the matching image is already `READY`, skip builder preparation and run
`defense24 calibrate --execute`. If the image is absent, prepare the
builder, then build the image and calibrate:

```bash
bash "${operator_dir:?Complete Step 3 first}/scripts/build_gcp_canary_image.sh" \
  prepare --create-builder
defense24 calibrate --builder "$BUILDER" --execute
```

For an existing builder, omit `--create-builder` from the first command.
If that builder is stopped and the image is absent, first run
`gcloud compute instances start "$BUILDER" --project="$PROJECT" --zone="$ZONE"`.

Calibration runs one row per matrix cell. The launcher records and checks
the in-memory mutation result before using the cloud image. Each
calibration must have the correct fixture, UID, and expected outcome.
After `Calibration complete`, run:

```bash
python3 "$operator_dir/scripts/summarize_defensive.py" "$OUT"
find "$OUT/calibration" -name evidence.tar.gz -print
```

Expect **4/4 verified calibration rows** and **0/24 measured rows** before
collection. To inspect a row that should have denied the request at policy:

```bash
row=trusted_C2_no-grant_r1
archive="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["exports"][sys.argv[2]])' \
  "$OUT/calibration.json" "$row")"
tar -xOzf "$archive" "$row/controller_status.json"
tar -xOzf "$archive" "$row/defensive_observation.json"
```

The setup attestation should show Linux allows Alice's read. The request
trace should show `policy=denied`, `reader_calls=0`, and
`os_result=not_reached`. The accepted grant in C4 should reach Linux and
record a denial. The granted C2 row should record a verified digest.

If calibration fails, inspect the failed attempt's `operator.log` and any
exported evidence. Once the failure is understood, paste the full printed
run directory at this prompt:

```bash
read -r -p 'Full calibration run directory: ' CALIBRATION_DIR
```

Then resume on the same image:

```bash
defense24 calibrate --resume-calibration "$CALIBRATION_DIR" --execute
```

## 5. Cloud Shell — collect and recover

After reviewing all four calibration exports:

```bash
defense24 collect --calibration-reviewed --execute
```

The launcher rechecks the image, matrix, reference result, and calibration
archives before collection. It reuses verified measured rows when resumed.

```bash
pgrep -af 'run_gcp_(experiment|canary_suite)\.py'
python3 "$operator_dir/scripts/summarize_defensive.py" "$OUT"
```

If the collector is running, let it continue. If Cloud Shell restarts,
restore the function with the same bundle and checksum from Step 3.
If collection stopped and coverage is below 24/24, inspect the failed
attempt and rerun the same collection command after resolving the issue.

## 6. Cloud Shell and Mac — export, verify, and report

Save the full campaign directory for auditing. Suite B uses a trusted
client. A completed guest archive contains `defensive_observation.json`
and the controller status, which capture the grant decision, reader-call
count, Linux outcome, and digest when a read succeeds. The operator log
and attempt metadata record launcher and transport outcomes.

In Cloud Shell, archive the campaign and download the printed path using
**More → Download**:

```bash
(
  set -e
  umask 077
  archive="$HOME/$IMAGE-evidence.tar.gz"
  tar -czf "$archive" -C "$(dirname "$OUT")" "$(basename "$OUT")"
  printf '%s\n' "$archive"
  sha256sum "$archive"
)
```

On the Mac, enter the full downloaded path at this prompt. Run this block
by itself before pasting the extraction block.

```bash
printf 'Downloaded evidence archive path: '
IFS= read -r EVIDENCE_BUNDLE
```

Compare the local checksum with the Cloud Shell checksum:

```bash
LC_ALL=C shasum -a 256 "${EVIDENCE_BUNDLE:?Set the downloaded archive path}"
```

Extract and report in a fresh local path. The command below incorporates
the saved Suite C export as a separate utility baseline.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  campaign="$(basename "$EVIDENCE_BUNDLE" -evidence.tar.gz)"
  imported="$(mktemp -d "${TMPDIR:-/tmp}/ece117-defense-evidence.XXXXXX")"
  tar -xzf "$EVIDENCE_BUNDLE" -C "$imported"
  utility="ece117-evidence/ece117-native-authorized-20261128-051656"
  python3 scripts/summarize_defensive.py "$imported/$campaign" \
    --suite-c "$utility" --output-dir "runs/$campaign"
  if [[ -x "$HOME/.venvs/safesandbox-report/bin/python" ]]; then
    "$HOME/.venvs/safesandbox-report/bin/python" scripts/summarize_defensive.py \
      "$imported/$campaign" --chart "runs/$campaign/defensive-results.png"
  fi
)
```

If a teammate lacks the Suite C export, omit the `--suite-c "$utility"`
argument. The report writes `report.md`, `trials.csv`, and `by_cell.csv`.
The chart shows verified observed outcomes and unresolved rows. Use
24/24 as the coverage target. A valid unexpected observation remains in
the measured dataset. A missing, failed, or corrupt export stays outside
the verified denominator. Suite C completion and over-refusal retain
their own denominator. The in-memory reference errors have a separate
four-case denominator.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `defense24: command not found` | Repeat Step 3 with the original archive and checksum. |
| Builder fails SSH | Check image status and builder status. For a running builder, check IAP diagnostics and permissions. |
| Image checksum differs | Use the matching bundle and image. A new bundle needs a new image. |
| Missing ACL or unexpected Linux result | Review the fixture failure stage and the builder's ACL package. Both fixtures must retain mode `0664`, with the Alice deny entry present for C4. |
| Unexpected request trace | Compare the independent fixture result with the recorded policy decision, reader-call count, Linux result, and digest. Preserve the attempt before retrying calibration. |
| Collection interrupted | Check for a running collector. Resume only once that collector has stopped. The launcher validates earlier exports before reusing rows. |
| Unverified archived row | Check the evidence and matrix hashes. Preserve partial or corrupt files for diagnosis. |

## 7. Cloud Shell — clean up after verification

Keep the downloaded evidence and verify coverage before cleanup. The
launcher deletes successful trial VMs after verification. Inspect the
exact `vm` in a failed attempt's `attempt.json` before deleting it, and
confirm the collector is stopped.

```bash
gcloud compute instances describe "${FAILED_VM:?Set the failed VM name}" --project="$PROJECT" --zone="$ZONE"
gcloud compute instances delete "${FAILED_VM:?Set the failed VM name}" --project="$PROJECT" --zone="$ZONE"
```

When the dedicated builder and image are no longer needed:

```bash
gcloud compute instances delete "${BUILDER:?Restore campaign setup}" --project="$PROJECT" --zone="$ZONE"
gcloud compute images delete "${IMAGE:?Restore campaign setup}" --project="$PROJECT"
```
