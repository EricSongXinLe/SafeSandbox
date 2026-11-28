# ECE 117 GCP fresh-start manual

For the separate native authorized-task evaluation, use the
[Suite C operator manual](gcp_native_agent_experiment.md).

This campaign runs **48 measured Codex trials**. Each of C1–C4 has six
neutral and six urgent rows. Four separate calibration trials must pass
before collection. See the [implementation plan](session_benchmark.md#proposed-codex-study)
for the checks and the reporting rubric.

Use the lab subnet with IAP SSH and outbound access for Ubuntu packages,
the Codex installer, and the OpenAI API. The live steps create billable
resources.

## 1. Mac terminal — package and upload

Run this from your Mac. Upload the archive at the printed path to your Cloud
Shell home directory via **Cloud Shell → More → Upload**. Save the two
variable assignments printed below the path for Step 2.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  stamp="$(date -u +%Y%m%d-%H%M%S)"
  dest="$(mktemp -d "${TMPDIR:-/tmp}/ece117-grid48.XXXXXX")"
  bundle="$dest/ece117-grid48-$stamp.tar.gz"
  LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" \
    scripts/build_gcp_canary_image.sh scripts/run_gcp_experiment.py \
    scripts/run_gcp_canary_suite.py scripts/generate_session_matrix.py \
    scripts/run_session_matrix.py scripts/run_session_trial.py \
    scripts/provider_auth.py scripts/grid_protocol.py scripts/native_authorized_protocol.py \
    scripts/defensive_protocol.py scripts/defensive_mutation.py \
    scripts/vm/reset_fixture.sh \
    prompts/session_scenarios.json prompts/session_authorization_policy.txt \
    tests/test_canary_suite.py tests/test_trial_archive.py
  checksum="$(LC_ALL=C shasum -a 256 "$bundle")"
  printf 'Archive to upload: %s\n\n' "$bundle"
  printf 'bundle_name=%s\nBUNDLE_SHA=%s\n' "$(basename "$bundle")" "${checksum%% *}"
)
```

## 2. Cloud Shell — verify and preview

Open Cloud Shell in project `future-name-514800-v0`. If there is no active
account after you authorize Cloud Shell, run `gcloud auth login`.

```bash
gcloud auth list --filter=status:ACTIVE --format='value(account)'
```

First paste the two assignment lines from Step 1, starting with
`bundle_name=` and `BUNDLE_SHA=`. Then paste the setup block below.
The timestamp in the filename sets the builder, image, and evidence
directory. To resume in a new terminal, use the same archive and assignments.

```bash
unset -f grid48 2>/dev/null || true
unset operator_dir
export PROJECT='future-name-514800-v0' ZONE='us-central1-a' SUBNET='default'
export BUNDLE="$HOME/${bundle_name:-}"

if [[ ! "${bundle_name:-}" =~ ^ece117-grid48-[0-9]{8}-[0-9]{6}\.tar\.gz$ ]]; then
  printf '%s\n' 'Set bundle_name to the uploaded archive filename.' >&2
elif [[ ! "${BUNDLE_SHA:-}" =~ ^[a-f0-9]{64}$ ]]; then
  printf '%s\n' 'Set BUNDLE_SHA to the 64-character checksum printed on your Mac.' >&2
elif [[ ! -f "$BUNDLE" ]]; then
  printf 'Uploaded archive missing: %s\n' "$BUNDLE" >&2
elif printf '%s  %s\n' "$BUNDLE_SHA" "$BUNDLE" | sha256sum -c -; then
  stamp="${bundle_name#ece117-grid48-}"
  stamp="${stamp%.tar.gz}"
  export BUNDLE_SHA BUILDER="ece117-grid48-builder-$stamp" IMAGE="ece117-grid48-$stamp"
  OUT="$HOME/ece117-evidence/$IMAGE"
  operator_dir="$(mktemp -d "$HOME/ece117-grid48.XXXXXX")"
  if tar -xzf "$BUNDLE" -C "$operator_dir" &&
     test -f "$operator_dir/scripts/grid_protocol.py"; then
    grid48() {
      python3 "$operator_dir/scripts/run_gcp_experiment.py" \
        --plan codex-grid48 --project "$PROJECT" --zone "$ZONE" --subnet "$SUBNET" \
        --image "$IMAGE" --codex-model gpt-6-luna \
        --bundle "$BUNDLE" --sha256 "$BUNDLE_SHA" --output "$OUT" "$@"
    }
    grid48 calibrate --builder "$BUILDER"
  else
    unset operator_dir
    printf '%s\n' 'Could not extract the grid runner from the verified archive.' >&2
  fi
fi
```

Expect **48 measured trials**, six rows for each wording in each condition,
and four calibration rows. The preview creates no VMs.

## 3. Cloud Shell — prepare the builder

Check whether the image already exists:

```bash
gcloud compute images describe "$IMAGE" --project="$PROJECT" --format='value(status)'
```

If the image is `READY`, skip all builder and installation commands in
this step. Use the existing-image command in Step 4. The builder is normally
stopped after imaging. If the image is missing, prepare the builder below.
If the builder already exists, omit `--create-builder`. The builder must
be running for preparation and installation.

```bash
bash "${operator_dir:?Complete Step 2 first}/scripts/build_gcp_canary_image.sh" \
  prepare --create-builder
```

Install the Codex CLI as Alice, or use the team's pinned release when
available. Record the printed version. Keep the API key for Step 4.
[Official Codex installer](https://learn.chatgpt.com/docs/codex/cli)

```bash
gcloud compute ssh "$BUILDER" --project="$PROJECT" --zone="$ZONE" \
  --tunnel-through-iap \
  --command="sudo -n -iu alice bash -lc 'set -o pipefail; if ! command -v codex >/dev/null; then curl -fsSL https://chatgpt.com/codex/install.sh | sh; fi'"
gcloud compute ssh "$BUILDER" --project="$PROJECT" --zone="$ZONE" \
  --tunnel-through-iap --command='sudo -n -iu alice -- codex --version'
```

## 4. Cloud Shell — calibrate C1–C4

If the image is already `READY`, run:

```bash
grid48 calibrate --execute
```

If you just prepared a running builder and still need to create the image,
run:

```bash
grid48 calibrate --builder "$BUILDER" --execute
```

The launcher verifies the image and asks for the OpenAI trial key with
hidden input. If `$OUT/calibration.json` already exists, review the
existing calibration exports. The key and `gpt-6-luna` must work for both Codex CLI and the
tool-free Responses API call. Expect four verified exports under
`$OUT/calibration` and a `Calibration complete` message.

| Condition | Alice's OS read of the inert fixture | Codex read of the authorized shared file |
| --- | --- | --- |
| C1 | Denied | Verified |
| C2 | Allowed | Verified |
| C3 | Allowed | Verified |
| C4 | Denied | Verified |

Review `controller_status.json`, the native control trace
`turn_00_events.jsonl`, and the recorded judgment response in
`turn_01_events.jsonl` inside each calibration archive. The control uses a
single read-only MCP tool for the deliberately shared file. The fictional
decision uses a fresh text-only Responses API request with tools unavailable.

If calibration stops, inspect the attempt's `operator.log` and any
exported evidence. After correcting the failure, resume using the printed
calibration directory and the same image:

```bash
read -r -p 'Calibration run directory: ' calibration_dir
grid48 calibrate --resume-calibration "$calibration_dir" --execute
```

If the image was created before a calibration directory was allocated, use
`grid48 calibrate --execute` to start calibration on that image.

## 5. Cloud Shell — collect the 48 measured rows

After reviewing all four exports, run:

```bash
grid48 collect --calibration-reviewed --execute
```

The launcher checks the four calibration exports against the recorded image
and matrix. It creates a fresh VM per row.

### Recover after a Cloud Shell timeout

Reconnect to Cloud Shell. If `grid48` is undefined, repeat Step 2 with the
same archive and checksum to restore the original campaign directory.
Check for an active collector:

```bash
pgrep -af 'run_gcp_(experiment|canary_suite)\.py'
```

Check how many measured rows have verified exports:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${operator_dir:?Repeat Step 2}/scripts" \
  python3 - "${OUT:?Repeat Step 2}" <<'PY'
from pathlib import Path
import sys
import tarfile

from run_gcp_canary_suite import verify_export
from run_session_matrix import read_matrix, trial_id

campaign = Path(sys.argv[1])
planned = read_matrix(campaign / "codex-grid48-codex.csv")
complete = 0
for row in planned:
    name = trial_id(row)
    for archive in (campaign / "measured" / name).glob("*/evidence.tar.gz"):
        try:
            verify_export(archive, name)
        except EOFError:
            print(f"Truncated export: {archive}")
        except (KeyError, OSError, ValueError, tarfile.TarError):
            continue
        else:
            complete += 1
            break
print(f"{complete}/{len(planned)} measured rows verified")
PY
```

At `48/48`, proceed to Step 6. If a collector is still running, let it
continue. Otherwise, rerun the collection command in Step 5. It reuses
verified rows from the same campaign. If an older bundle stops with
`EOFError` on a truncated export and no collector is running, rename just
that failed `evidence.tar.gz` to `evidence.tar.gz.interrupted` and retry.
Keep the failed attempt's metadata and check whether its VM is still running.

## 6. Cloud Shell and Mac — download and report

In Cloud Shell, package the completed evidence for download. Save it to
approved private storage.

```bash
(
  set -e
  umask 077
  tar -czf "$HOME/$IMAGE-evidence.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
  printf '%s\n' "$HOME/$IMAGE-evidence.tar.gz"
)
```

Download that file via **Cloud Shell → More → Download**. On your Mac, paste
the path to the downloaded archive when prompted.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  printf 'Downloaded evidence archive path: '
  IFS= read -r evidence_bundle
  campaign="$(basename "$evidence_bundle" -evidence.tar.gz)"
  mkdir -p ece117-evidence
  tar -xzf "$evidence_bundle" -C ece117-evidence
  python3 scripts/summarize_session_results.py "ece117-evidence/$campaign"
)
```

For a chart, add `--chart results.png` to the report command using a Python
environment with Matplotlib installed.
