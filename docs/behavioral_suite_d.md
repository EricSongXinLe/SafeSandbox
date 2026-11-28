# Suite D operator manual

Suite D measures whether urgency and trusted-policy reinforcement change a
model's judgments about fictional board-game authorization. It runs on a
Mac or in Cloud Shell using Python 3.10 or later. A live run requires an
OpenAI API key and an approved Responses API model with Structured Outputs.
It sends up to 48 measured requests, plus any retries after transport
failures. Model requests may incur API charges. The launcher provisions
zero GCP resources and uses zero native-agent sessions.

[Responses API Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs) ·
[Defensive Suite B GCP manual](gcp_defensive_suite_b.md) ·
[Research design](session_benchmark.md)

## 1. Run the offline checks from the repo root

```bash
cd "$HOME/Desktop/SafeSandbox"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The tests exercise the eight matched conditions, the response contract,
scoring, evidence validation, and resumption using mocked provider replies.
The reference mutation check belongs to Defensive Suite B.

## 2. Choose where to run

For a Mac-only run, stay in the repo root and continue to Step 3. For a
Cloud Shell run, package the Suite D files on the Mac.

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  bundle="$(mktemp -d)/ece117-suite-d.tar.gz"
  LC_ALL=C COPYFILE_DISABLE=1 tar -czf "$bundle" scripts/behavioral_protocol.py \
    scripts/run_behavioral_suite.py scripts/summarize_behavioral.py \
    scripts/provider_auth.py prompts/suite_d_scenarios.json
  digest="$(LC_ALL=C shasum -a 256 "$bundle")"
  printf 'Upload this file: %s\n' "$bundle"
  printf 'BUNDLE_SHA=%s\n' "${digest%% *}"
)
```

Upload the printed archive through **Cloud Shell → More → Upload**. In
Cloud Shell, paste the printed `BUNDLE_SHA=…` assignment, then run:

```bash
(
  set -e
  printf '%s  %s\n' "${BUNDLE_SHA:?Paste the checksum assignment first}" \
    "$HOME/ece117-suite-d.tar.gz" | sha256sum -c -
  mkdir -p "$HOME/ece117-suite-d"
  tar -xzf "$HOME/ece117-suite-d.tar.gz" -C "$HOME/ece117-suite-d"
)
cd "$HOME/ece117-suite-d"
ls scripts/run_behavioral_suite.py
```

Continue once the checksum prints `OK` and `ls` shows the script. This
installation uses Cloud Shell storage. No image, builder, or SSH step is
needed. After reconnecting, `cd "$HOME/ece117-suite-d"` again.

## 3. Freeze and preview the 48-row campaign

Run from the selected repo or operator directory. Run the model prompt on
its own line, enter the model ID approved for the run, and prefer a dated
snapshot if available. Use one model for the full campaign.

```bash
printf 'Approved OpenAI Responses API model ID: '; IFS= read -r SUITE_D_MODEL
```

```bash
D_OUT="$HOME/ece117-evidence/ece117-behavioral-d-$(date -u +%Y%m%d-%H%M%S)"
python3 scripts/run_behavioral_suite.py plan --output "$D_OUT" --model "$SUITE_D_MODEL"
python3 scripts/run_behavioral_suite.py run --campaign "$D_OUT"
printf 'Suite D campaign directory: %s\n' "$D_OUT"
```

Save that last path. The plan and preview work offline and require zero
keys. Expect **48 planned** and **0 recorded outcomes**. Inspect
`matrix.csv` for the row order and expected labels, and `plan.json` for
the exact prompts, model, and response settings. Calibration VMs apply to
Suite B. Suite D uses the offline checks and the fixed response contract.

## 4. Collect or resume

```bash
python3 scripts/run_behavioral_suite.py run --campaign "${D_OUT:?Set the campaign directory first}" --execute
```

The launcher prompts once for the OpenAI key with hidden input. If
`OPENAI_API_KEY` is already in the current environment, it uses that value.
Enter the key only at the hidden prompt or provide it through your
approved secret mechanism.

Each request is independent. The only live service the runner contacts is
the OpenAI Responses API. An HTTP or transport failure stops collection
at that row. A valid decision, a provider refusal, an incomplete provider
response, or an invalid output is recorded once as the row's final
observation. An interrupted request may have reached the provider.
Resuming can send it again and can incur another charge.

After a new shell starts, return to the runner directory and restore the
same output path before rerunning the command above.

```bash
ls -d "$HOME"/ece117-evidence/ece117-behavioral-d-*/
printf 'Full original campaign directory: '; IFS= read -r D_OUT
```

Use the same path after a timeout. The runner verifies saved evidence and
skips finished rows. Its lock prevents a second collector from running in
the same campaign.

| Symptom | Action |
| --- | --- |
| HTTP 401 or 403 | Verify the key and its project permissions. Resume using the same campaign if the model is still the same. |
| HTTP 400 or 404 | Check the spelling, model access, and support for the frozen response settings. Start a new campaign if the model or settings must change. |
| HTTP 429 | Check the provider's usage limits and billing, then resume once resolved. |
| Timeout or connection failure | Check outbound access to the endpoint and resume. Set `--timeout 180` if needed. |
| Returned model changes | Preserve the partial campaign and use a pinned snapshot for a new campaign. |
| Checksum or evidence failure | Restore the original verified archive or inspect the reported path. Preserve the disputed attempt for review. |
| Provider refusal or invalid output | Report the reduced coverage and keep the original outcome. A structured `DENY` is a decision and can be scored. |

## 5. Verify, report, and export

Keep the full campaign directory as the interaction record.

| Artifact | What it records |
| --- | --- |
| `plan.json` | The exact trusted instructions, user prompt, and request settings for each trial |
| `attempts/<trial_id>/<sequence>.json` | Request hash, timestamps, returned model and response IDs when available, visible answer text or refusal, and failure status |
| `matrix.csv` and `report/` | Expected labels, row-level outcomes, aggregate counts, and matched comparisons |

The request hash links each attempt to the frozen plan. Provider HTTP
failures preserve the status code. The interaction record excludes
credentials and private model reasoning.

Run from the same operator directory. The reporter is offline and requires
only Python for the Markdown and CSV files.

```bash
python3 scripts/summarize_behavioral.py "$D_OUT" --output "$D_OUT/report"
```

Check **evaluated coverage**, incorrect acceptance on ungranted rows,
over-refusal on granted rows, and `UNCLEAR` counts. Expect 48 evaluated
only if every row yielded a verified structured decision. The report also
shows eight paired contrasts. Valid `UNCLEAR` answers count in evaluated
denominators and are displayed separately. Resolved-pair transition counts
require `ALLOW` or `DENY` in both rows.

For a PNG chart, use the existing report environment with Matplotlib. Run
these setup commands only if that environment is missing.

```bash
python3 -m venv "$HOME/.venvs/safesandbox-report"
"$HOME/.venvs/safesandbox-report/bin/python" -m pip install matplotlib
```

```bash
"$HOME/.venvs/safesandbox-report/bin/python" scripts/summarize_behavioral.py "$D_OUT" \
  --output "$D_OUT/report" --chart "$D_OUT/report/authorization-errors.png"
```

To download a Cloud Shell run, create the archive and download the printed
path through **More → Download**.

```bash
(
  set -e
  umask 077
  archive="$HOME/$(basename "$D_OUT")-evidence.tar.gz"
  tar -czf "$archive" -C "$(dirname "$D_OUT")" "$(basename "$D_OUT")"
  printf 'Download: %s\n' "$archive"
  sha256sum "$archive"
)
```

From the Mac repo root, paste the downloaded archive path when prompted.
Compare its SHA-256 with the one printed in Cloud Shell before extraction.

```bash
printf 'Downloaded Suite D evidence archive path: '; IFS= read -r D_ARCHIVE
LC_ALL=C shasum -a 256 "$D_ARCHIVE"
```

```bash
(
  set -e
  cd "$HOME/Desktop/SafeSandbox"
  campaign="$(basename "$D_ARCHIVE" -evidence.tar.gz)"
  review_dir="$(mktemp -d)"
  LC_ALL=C tar -xzf "$D_ARCHIVE" -C "$review_dir"
  python3 scripts/summarize_behavioral.py "$review_dir/$campaign"
)
```

Keep the frozen plan, matrix, attempts, and report together. After verifying
the download, you can remove the uploaded code archive from Cloud Shell with
`rm -i "$HOME/ece117-suite-d.tar.gz"`. Suite D has no Compute Engine
resources to clean up.

## Interpretation

The 48 rows are six scenarios crossed with eight conditions. Report matched
effects and the individual counts. A result of zero observed errors is
evidence about these scenarios and the tested model. Suite B measures the
enforcement decisions of a trusted client. Suite C measures native-agent
utility on granted tasks. Native-agent unauthorized retrieval remains
unmeasured.
