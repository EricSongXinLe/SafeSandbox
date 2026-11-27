# ECE 117 GCP fresh-start manual

The fresh-start campaign is **48 measured Codex trials**. Run six neutral
and six urgent trials in each of C1–C4. Calibration is separate. The
[implementation plan](session_benchmark.md#proposed-codex-study) explains
what each condition tests.

**Status:** the matrix is ready to generate locally. The Cloud Shell launcher
still needs support for this grid and its separate control and judgment
sessions. Complete Step 1 now. Steps 2–4 describe the sequence once the
runner is ready.

## 1. Mac — generate the 48-trial matrix

From the repository root, run:

```bash
python3 scripts/generate_session_matrix.py --plan codex-grid48 --seed 117 \
  --output runs/codex-grid48.csv
```

Expect `wrote 48 planned independent trials`. The file has eight groups of
six rows. Every row uses Codex. The script labels `role-neutral` and
`role-urgent` identify the new protocol.

## 2. Cloud Shell — prepare a fresh campaign

When the runner supports `codex-grid48`, package that revision on your Mac
and upload it to Cloud Shell. Verify the uploaded bundle against its
SHA-256 checksum. Prepare a clean builder, give the new image and evidence
directory unique names, and record the pinned image, model, and CLI version.

The lab project is `future-name-514800-v0`, the zone is `us-central1-a`,
and the subnet is `default`. Enter the OpenAI trial key at the hidden
prompt. Check that the preview shows Codex, all eight groups, six trials
per group, and 48 measured rows before starting live operations.

## 3. GCP — verify the four calibration trials

On the intended image, check one calibration per condition:

| Condition | Alice's OS read of the inert fixture | Codex read of the authorized shared file |
| --- | --- | --- |
| C1 | Denied | Verified |
| C2 | Allowed | Verified |
| C3 | Allowed | Verified |
| C4 | Denied | Verified |

Check the actual tool result for the shared read. If any condition fails,
save its evidence and resolve the failure before collection. The prior
batches verified zero shared reads across 24 measured trials. The
fictional role decision must use a fresh session with tool execution
unavailable.

## 4. GCP and Mac — collect and review

Run the fixed matrix on the calibrated image with one fresh VM per measured
row. Download the campaign evidence, including calibration and any failed
attempts. Report OS access, verified shared reads, and fictional role
decisions as separate outcomes by condition and wording. Keep the two
earlier C2/C3 batches as separate pilot evidence.
