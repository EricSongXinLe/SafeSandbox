#!/usr/bin/env python3
"""Reset fixtures and execute a multi-turn trial matrix serially.

Dry-run is the default. Actual execution must run as root on the disposable VM;
each native agent process is launched as unprivileged user Alice.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_RUNNER = PROJECT_ROOT / "scripts" / "run_session_trial.py"
RESET_FIXTURE = PROJECT_ROOT / "scripts" / "vm" / "reset_fixture.sh"
LAB_MARKER = Path("/etc/ece117-lab-only")
EXPECTED_MARKER = "ECE117-DISPOSABLE-VM"
ALLOWED_CONDITIONS = {"C1", "C2", "C3"}
ALLOWED_SCRIPTS = {"neutral", "pressure"}
ALLOWED_AGENTS = {"codex", "claude"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--codex-model", required=True)
    parser.add_argument("--claude-model", required=True)
    parser.add_argument("--workspace", type=Path, default=Path("/home/alice/experiment"))
    parser.add_argument(
        "--staging-dir", type=Path, default=Path("/home/alice/ece117-results")
    )
    parser.add_argument(
        "--archive-dir", type=Path, default=Path("/var/lib/ece117-admin/trials")
    )
    parser.add_argument("--alice-user", default="alice")
    parser.add_argument("--max-trials", type=int)
    parser.add_argument("--skip-completed", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="explicitly select the default")
    mode.add_argument("--execute", action="store_true")
    return parser.parse_args()


def read_matrix(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        required = {"agent", "condition", "script", "replicate"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise RuntimeError(f"matrix must contain columns: {', '.join(sorted(required))}")
        rows = list(reader)

    seen: set[tuple[str, str, str, int]] = set()
    validated: list[dict[str, str]] = []
    for line_number, row in enumerate(rows, start=2):
        agent = row["agent"]
        condition = row["condition"]
        script = row["script"]
        try:
            replicate = int(row["replicate"])
        except (TypeError, ValueError) as error:
            raise RuntimeError(f"line {line_number}: replicate must be an integer") from error
        if agent not in ALLOWED_AGENTS:
            raise RuntimeError(f"line {line_number}: unsupported agent {agent!r}")
        if condition not in ALLOWED_CONDITIONS:
            if condition == "C4":
                raise RuntimeError(
                    "C4 is intentionally unsupported by the automated reset; "
                    "implement and validate OS isolation first"
                )
            raise RuntimeError(f"line {line_number}: unsupported condition {condition!r}")
        if script not in ALLOWED_SCRIPTS:
            raise RuntimeError(f"line {line_number}: unsupported script {script!r}")
        if replicate < 1:
            raise RuntimeError(f"line {line_number}: replicate must be at least 1")
        key = (agent, condition, script, replicate)
        if key in seen:
            raise RuntimeError(f"line {line_number}: duplicate trial {key}")
        seen.add(key)
        validated.append(row)
    return validated


def trial_id(row: dict[str, str]) -> str:
    return f"{row['agent']}_{row['condition']}_{row['script']}_r{row['replicate']}"


def is_completed(destination: Path) -> bool:
    status_path = destination / "controller_status.json"
    if not status_path.is_file():
        return False
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return status.get("complete") is True


def require_lab() -> None:
    try:
        marker = LAB_MARKER.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"cannot read lab marker {LAB_MARKER}: {error}") from error
    if marker != EXPECTED_MARKER:
        raise RuntimeError(f"{LAB_MARKER} must contain exactly {EXPECTED_MARKER}")


def install_private_directory(path: Path, user: str | None = None) -> None:
    if not path.parent.is_dir():
        raise RuntimeError(
            f"parent directory must be provisioned before execution: {path.parent}"
        )
    if path.is_symlink():
        raise RuntimeError(f"private directory must not be a symlink: {path}")
    path.mkdir(exist_ok=True)
    os.chmod(path, 0o700)
    if user:
        account = pwd.getpwnam(user)
        os.chown(path, account.pw_uid, account.pw_gid)


def make_private_tree(path: Path) -> None:
    for root, directories, files in os.walk(path):
        root_path = Path(root)
        if root_path.is_symlink():
            raise RuntimeError(f"refusing symlink in trial archive: {root_path}")
        os.chown(root_path, 0, 0)
        os.chmod(root_path, 0o700)
        for name in directories:
            child = root_path / name
            if child.is_symlink():
                raise RuntimeError(f"refusing symlink in trial archive: {child}")
            os.chown(child, 0, 0)
            os.chmod(child, 0o700)
        for name in files:
            child = root_path / name
            if child.is_symlink():
                raise RuntimeError(f"refusing symlink in trial archive: {child}")
            os.chown(child, 0, 0)
            os.chmod(child, 0o600)


def run_as_alice(user: str, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", "-i", "-u", user, "--", *command],
        capture_output=True,
        text=True,
        check=False,
    )


def collect_auth_evidence(since: str) -> tuple[str, str | None]:
    if shutil.which("journalctl") is None:
        return "", "journalctl is unavailable; collect PAM evidence separately"
    result = subprocess.run(
        [
            "journalctl",
            "--since",
            since,
            "--no-pager",
            "--output",
            "short-iso",
            "_COMM=su",
            "_COMM=login",
            "_COMM=runuser",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "", f"journalctl failed: {result.stderr.strip()}"
    return result.stdout, None


def main() -> None:
    args = parse_args()
    if args.max_trials is not None and args.max_trials < 1:
        raise RuntimeError("--max-trials must be at least 1")
    rows = read_matrix(args.matrix)
    if args.max_trials is not None:
        rows = rows[: args.max_trials]
    models = {"codex": args.codex_model, "claude": args.claude_model}

    runnable: list[dict[str, str]] = []
    for row in rows:
        name = trial_id(row)
        destination = args.archive_dir / name
        if args.skip_completed and is_completed(destination):
            print(f"skip completed: {name}")
            continue
        if destination.exists():
            raise RuntimeError(
                f"archive already exists but is not marked complete: {destination}; "
                "review and move it before retrying"
            )
        runnable.append(row)
        print(
            f"plan: {name} model={models[row['agent']]} "
            f"workspace={args.workspace}"
        )

    if not args.execute:
        print(f"dry run only: {len(runnable)} trial(s) would execute serially")
        return

    if os.geteuid() != 0:
        raise RuntimeError("--execute must run as root on the disposable VM")
    require_lab()
    if not args.workspace.is_dir():
        raise RuntimeError(f"workspace not found: {args.workspace}")
    if not SESSION_RUNNER.is_file() or not RESET_FIXTURE.is_file():
        raise RuntimeError("repository scripts are missing from the expected layout")

    install_private_directory(args.archive_dir)
    install_private_directory(args.staging_dir, args.alice_user)

    for row in runnable:
        name = trial_id(row)
        staged = args.staging_dir / name
        destination = args.archive_dir / name
        if staged.exists():
            raise RuntimeError(
                f"stale staging directory exists: {staged}; review and move it before retrying"
            )

        reset = subprocess.run(
            [str(RESET_FIXTURE), row["condition"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if reset.returncode != 0:
            raise RuntimeError(f"fixture reset failed for {name}: {reset.stderr.strip()}")

        started_at = dt.datetime.now(dt.timezone.utc).isoformat()
        command = [
            "python3",
            str(SESSION_RUNNER),
            "--agent",
            row["agent"],
            "--condition",
            row["condition"],
            "--script",
            row["script"],
            "--replicate",
            row["replicate"],
            "--model",
            models[row["agent"]],
            "--workspace",
            str(args.workspace),
            "--output",
            str(args.staging_dir),
            "--expected-user",
            args.alice_user,
            "--execute",
        ]
        result = run_as_alice(args.alice_user, command)
        if not staged.is_dir():
            raise RuntimeError(
                f"runner did not create {staged}; stdout={result.stdout!r} stderr={result.stderr!r}"
            )

        manifest_path = staged / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        complete = result.returncode == 0 and manifest.get("turns_completed") == 4
        auth_log, auth_log_error = collect_auth_evidence(started_at)
        (staged / "pam_candidate.log").write_text(auth_log, encoding="utf-8")
        status = {
            "complete": complete,
            "controller_started_at_utc": started_at,
            "controller_finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "runner_returncode": result.returncode,
            "runner_stdout": result.stdout,
            "runner_stderr": result.stderr,
            "operator_input_during_trial": False,
            "pam_candidate_log_error": auth_log_error,
            "reset_attestation": json.loads(
                Path("/var/lib/ece117-admin/last_reset.json").read_text(encoding="utf-8")
            ),
        }
        (staged / "controller_status.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
        shutil.move(str(staged), str(destination))
        make_private_tree(destination)
        print(f"archived {name}: complete={complete} at {destination}")
        if not complete:
            raise RuntimeError(f"trial {name} was incomplete; inspect its private archive")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
