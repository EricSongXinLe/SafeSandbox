# ECE 117 GCP fresh-start manual

This campaign has **48 measured Codex trials**. Each of C1–C4 has six
neutral and six urgent trials. The [implementation plan](session_benchmark.md#proposed-codex-study)
defines the conditions and the evidence to collect.

**Status:** Steps 1–4 work today and end with a verified 48-row preview in
Cloud Shell. Live calibration and collection require runner support.

## 1. Mac terminal — generate and package the grid

Paste this block on your Mac. It prints the archive path and its SHA-256
checksum. Copy the 64-character checksum for Step 4.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  python3 scripts/generate_session_matrix.py --plan codex-grid48 --seed 117 \
    --output runs/codex-grid48.csv

  stamp="$(date -u +%Y%m%d-%H%M%S)"
  preview_dir="$(mktemp -d "${TMPDIR:-/tmp}/ece117-grid48.XXXXXX")"
  bundle="$preview_dir/ece117-grid48-preview-$stamp.tar.gz"
  LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" \
    runs/codex-grid48.csv scripts/generate_session_matrix.py
  LC_ALL=C shasum -a 256 "$bundle"
)
```

## 2. Google Cloud Console — open Cloud Shell and upload

Open project `future-name-514800-v0` and click **Activate Cloud Shell** (`>_`).
In the Cloud Shell toolbar, choose **More → Upload** and select the
`ece117-grid48-preview-…tar.gz` file from Step 1. Upload it to your
Cloud Shell home directory.

## 3. Cloud Shell — verify the account and subnet

Run this at a prompt that shows `@cloudshell`.

```bash
(
  set -e
  PROJECT='future-name-514800-v0'
  ZONE='us-central1-a'
  SUBNET='default'

  account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
  if [[ -z "$account" ]]; then
    printf '%s\n' 'No active account. Authorize Cloud Shell, then rerun this block.' >&2
    exit 1
  fi
  printf 'Active Google Cloud account: %s\n' "$account"

  gcloud compute networks subnets describe "$SUBNET" \
    --project="$PROJECT" --region="${ZONE%-*}" --format='value(name)'
)
```

Expect your lab account and `default`. If Cloud Shell has no credentialed
account after authorization, run `gcloud auth login` and repeat Step 3.

## 4. Cloud Shell — verify, extract, and preview the grid

Paste the complete block. Enter the uploaded **filename** and the SHA-256
from Step 1 when prompted.

```bash
(
  set -e
  read -r -p 'Uploaded filename: ' bundle_name
  read -r -p 'SHA-256 from your Mac: ' bundle_sha
  bundle="$HOME/$bundle_name"

  if [[ ! -f "$bundle" || ! "$bundle_sha" =~ ^[a-f0-9]{64}$ ]]; then
    printf '%s\n' 'Check the uploaded filename and paste only the 64-character checksum.' >&2
    exit 1
  fi
  printf '%s  %s\n' "$bundle_sha" "$bundle" | sha256sum -c -

  stage="$(mktemp -d "$HOME/ece117-grid48.XXXXXX")"
  tar -xzf "$bundle" -C "$stage"
  python3 "$stage/scripts/generate_session_matrix.py" \
    --plan codex-grid48 --seed 117 --output "$stage/regenerated.csv"
  cmp "$stage/runs/codex-grid48.csv" "$stage/regenerated.csv"

  printf '\nRows by condition and wording\n'
  awk -F, 'NR > 1 {print $1, $2, $3}' "$stage/runs/codex-grid48.csv" | sort | uniq -c
  printf '\nVerified matrix: %s\n' "$stage/runs/codex-grid48.csv"
)
```

Expect `OK` from the checksum and **eight rows of counts**, each showing
six trials. The package is a preview bundle. These commands create no
trial VMs and ask for no model API key.

## Live-run checkpoint

The existing launcher has no launch command for `codex-grid48`. Once the
new runner is available, calibrate all four conditions on the intended
image before collecting the 48 measured rows.

| Condition | Alice's OS read of the inert fixture | Codex read of the authorized shared file |
| --- | --- | --- |
| C1 | Denied | Verified |
| C2 | Allowed | Verified |
| C3 | Allowed | Verified |
| C4 | Denied | Verified |

The shared-file check must come from the actual Codex tool result.
The fictional role decision runs in a separate session with tool
execution unavailable. Keep fixture checks, shared-file reads, and
fictional decisions separate when reporting.
