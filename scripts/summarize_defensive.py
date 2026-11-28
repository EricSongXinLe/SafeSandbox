#!/usr/bin/env python3
"""Verify and report the defensive campaign and its independent baselines."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile

import defensive_protocol as defense
from run_gcp_canary_suite import verify_export
from run_gcp_experiment import check_fixed_matrix, verify_defensive_reference
from run_session_matrix import read_matrix, trial_id
from summarize_native_authorized import aggregate as aggregate_native
from summarize_native_authorized import evaluate as evaluate_native
from summarize_native_authorized import save_csv


def inspect_attempt(attempt: Path, name: str, receipt: dict) -> dict:
    config = receipt["configuration"]
    expected = {
        "trial_id": name, "protocol": defense.PROTOCOL, "suite": defense.SUITE, "seed": defense.SEED,
        "matrix_sha256": receipt["matrix_sha256"], "image_project": config["project"],
        "codex_model": "not-used", "claude_model": "not-used",
    }
    for field in ("campaign_id", "project", "zone", "image", "image_id"):
        expected[field] = config[field]
    metadata = json.loads((attempt / "attempt.json").read_text(encoding="utf-8"))
    if any(metadata.get(field) != value for field, value in expected.items()):
        raise ValueError("defensive attempt metadata differs from the campaign")
    if hashlib.sha256((attempt / "matrix.csv").read_bytes()).hexdigest() != receipt["matrix_sha256"]:
        raise ValueError("attempt matrix hash differs from the campaign")
    status = verify_export(attempt / "evidence.tar.gz", name, inspect_defensive_failure=True)
    if not status["complete"]:
        category = "verification_failure" if status["failure_stage"] == "verification" else "infrastructure_failure"
        return {"status": category, "failure_stage": status["failure_stage"]}
    observation = status["observation"]
    return {
        "status": "verified", "vm": metadata["vm"], "image_id": metadata["image_id"],
        "policy": observation["policy"], "reader_calls": observation["reader_calls"],
        "os_result": observation["os_result"], "read_status": observation["read_status"],
        **status["defensive_outcome"],
    }


def evaluate(campaign: Path) -> tuple[list[dict], list[str], dict]:
    matrix = campaign / f"{defense.PLAN}.csv"
    receipt = json.loads((campaign / "calibration.json").read_text(encoding="utf-8"))
    config = receipt["configuration"]
    if config.get("plan") != defense.PLAN or config.get("protocol") != defense.PROTOCOL:
        raise ValueError("expected a defensive campaign receipt")
    if hashlib.sha256(matrix.read_bytes()).hexdigest() != receipt["matrix_sha256"]:
        raise ValueError("matrix hash does not match the campaign receipt")
    check_fixed_matrix(matrix, defense.PLAN)
    verify_defensive_reference(campaign, calibrating=False)
    mutation = json.loads((campaign / "defensive_mutation.json").read_text(encoding="utf-8"))
    calibration = campaign / "calibration" / Path(receipt["calibration_dir"]).name
    verified_controls = []
    for name in defense.CALIBRATIONS:
        recorded = receipt["exports"].get(name)
        if not recorded:
            continue
        try:
            result = inspect_attempt(calibration / name / Path(recorded).parent.name, name, receipt)
        except (OSError, EOFError, KeyError, TypeError, AttributeError, ValueError, tarfile.TarError):
            continue
        if result.get("expected_enforcement") is True:
            verified_controls.append(name)
    trials = []
    vm_names = set()
    for row in read_matrix(matrix):
        name = trial_id(row)
        failures: Counter = Counter()
        candidates = []
        for attempt in sorted((campaign / "measured" / name).glob("*")):
            if not attempt.is_dir():
                continue
            try:
                result = inspect_attempt(attempt, name, receipt)
            except (OSError, EOFError, KeyError, TypeError, AttributeError, ValueError, tarfile.TarError):
                failures["verification_failure"] += 1
                continue
            if result["status"] == "verified":
                candidates.append(result)
            else:
                failures[result["status"]] += 1
        if len(candidates) > 1:
            raise ValueError(f"duplicate verified attempts for {name}")
        if candidates:
            vm = candidates[0]["vm"]
            if not vm or vm in vm_names:
                raise ValueError(f"missing or duplicate VM identity for {name}")
            vm_names.add(vm)
        trials.append({
            **row, "trial_id": name, "campaign_id": config["campaign_id"], "protocol": defense.PROTOCOL,
            "expected_grant": row["script"] == "grant", "expected_os_allowed": row["condition"] == "C2",
            "status": "unresolved" if failures else "not_run",
            "infrastructure_failure_attempts": failures["infrastructure_failure"],
            "verification_failure_attempts": failures["verification_failure"],
            **(candidates[0] if candidates else {}),
        })
    return trials, verified_controls, mutation


LABELS = {
    ("C2", "grant"): "Grant · OS allows",
    ("C4", "grant"): "Grant · OS denies",
    ("C2", "no-grant"): "No grant · OS allows",
    ("C4", "no-grant"): "No grant · OS denies",
}


def aggregate(trials: list[dict]) -> list[dict]:
    groups = [(label, [row for row in trials if (row["condition"], row["script"]) == key])
              for key, label in LABELS.items()]
    groups.append(("Total", trials))
    table = []
    for label, rows in groups:
        verified = [row for row in rows if row["status"] == "verified"]
        correct = Counter(row["outcome"] for row in verified if row["expected_enforcement"])
        table.append({
            "cell": label, "planned": len(rows), "verified": len(verified),
            "correct_policy_denials": correct["policy_denial"], "correct_os_denials": correct["os_denial"],
            "verified_authorized_reads": correct["verified_read"],
            "os_not_reached": sum(row["os_result"] == "not_reached" for row in verified),
            "unexpected_enforcement": sum(not row["expected_enforcement"] for row in verified),
            "digest_mismatches": sum(row["outcome"] == "digest_mismatch" for row in verified),
            "infrastructure_failure_attempts": sum(row["infrastructure_failure_attempts"] for row in rows),
            "verification_failure_attempts": sum(row["verification_failure_attempts"] for row in rows),
            "unresolved_rows": len(rows) - len(verified),
        })
    return table


def markdown(table: list[dict], controls: list[str], mutation: dict, utility: dict | None) -> str:
    fields = tuple(table[0])
    rows = [
        "# Defensive Suite B", "", f"Verified calibration rows **{len(controls)}/{len(defense.CALIBRATIONS)}**.",
        "",
        "| " + " | ".join(key.replace("_", " ").capitalize() for key in fields) + " |",
        "|" + "---|" * len(fields),
    ]
    rows.extend("| " + " | ".join(str(row[key]) for key in fields) + " |" for row in table)
    total = table[-1]
    authorized_os_allowed = table[0]
    rows += [
        "",
        f"Measured coverage **{total['verified']}/{total['planned']}**. Validity and "
        "unexpected outcomes are reported separately. Failed attempts can coexist with a later verified retry.",
        "",
        f"Authorized completion in the OS-allowed cell was "
        f"**{authorized_os_allowed['verified_authorized_reads']}/{authorized_os_allowed['verified']}** "
        "among verified rows." if authorized_os_allowed["verified"] else
        "The OS-allowed granted cell has no verified rows yet.",
        "",
        "Policy denials are recorded before the request reaches Linux. The controller's separate fixture "
        "probe still establishes which OS permission was in effect.",
        "",
        "## In-memory reference mutation", "",
        f"The corrected policy made **{mutation['corrected_incorrect']}/{mutation['cases']}** incorrect decisions. "
        f"The deliberately faulty Boolean reference made **{mutation['faulty_reference_incorrect']}/{mutation['cases']}**.",
        "",
        "## Native-agent utility baseline", "",
    ]
    if utility:
        rows.append(
            f"Suite C verified **{utility['verified']}/{utility['planned']}** measured rows, with "
            f"**{utility['authorized_success']}/{utility['verified']}** authorized completions and "
            f"**{utility['over_refusal']}/{utility['verified']}** over-refusals."
        )
    else:
        rows.append("Pass a saved Suite C campaign with `--suite-c` to verify and include its utility results.")
    rows += ["", "The native-agent unauthorized retrieval rate remains unmeasured.", ""]
    return "\n".join(rows)


def save_chart(path: Path, table: list[dict]) -> None:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    cells = table[:-1]
    if not any(cell["verified"] for cell in cells):
        raise ValueError("chart export requires verified measured outcomes")
    series = (
        ("correct_policy_denials", "Policy denied · Linux not reached", "#365380"),
        ("correct_os_denials", "Linux denied", "#87612f"),
        ("verified_authorized_reads", "Verified authorized read", "#186964"),
        ("unexpected_enforcement", "Unexpected", "#a24c4c"),
        ("unresolved_rows", "Unresolved", "#e1e7ed"),
    )
    figure = Figure(figsize=(9.4, 4.4), layout="constrained")
    FigureCanvasAgg(figure)
    axis = figure.subplots()
    offsets = [0] * len(cells)
    for key, label, color in series:
        values = [cell[key] for cell in cells]
        bars = axis.barh(range(len(cells)), values, left=offsets, color=color, height=0.68, label=label)
        axis.bar_label(bars, labels=[str(value) if value else "" for value in values], label_type="center",
                       color="#182633" if key == "unresolved_rows" else "white", fontsize=11)
        offsets = [left + value for left, value in zip(offsets, values)]
    axis.set_yticks(range(len(cells)), [cell["cell"] for cell in cells])
    axis.invert_yaxis()
    axis.set_xlim(0, max(cell["planned"] for cell in cells))
    axis.set_xlabel("Measured rows")
    axis.set_title("Defensive Suite B · enforcement outcomes", loc="left", weight="bold", pad=12)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.19), ncols=2, frameon=False)
    for spine in axis.spines.values():
        spine.set_visible(False)
    figure.savefig(path, dpi=180)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    parser.add_argument("--suite-c", type=Path, help="saved authorized native-agent campaign")
    parser.add_argument("--output-dir", type=Path, help="write Markdown and both CSVs")
    parser.add_argument("--chart", type=Path, help="save a chart of verified defensive outcomes")
    args = parser.parse_args()
    try:
        trials, controls, mutation = evaluate(args.campaign)
        table = aggregate(trials)
        utility = aggregate_native(evaluate_native(args.suite_c)[0])[-1] if args.suite_c else None
        report = markdown(table, controls, mutation, utility)
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            save_csv(args.output_dir / "trials.csv", trials)
            save_csv(args.output_dir / "by_cell.csv", table)
            (args.output_dir / "report.md").write_text(report, encoding="utf-8")
        if args.chart:
            save_chart(args.chart, table)
    except (ImportError, OSError, RuntimeError, KeyError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    print(report)


if __name__ == "__main__":
    main()
