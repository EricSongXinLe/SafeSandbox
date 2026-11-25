#!/usr/bin/env python3
"""Reset fixtures and execute a multi-turn trial matrix serially.

Dry-run is the default. Actual execution must run as root on the disposable VM;
each native agent process is launched as unprivileged user Alice.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SESSION_RUNNER = PROJECT_ROOT / "scripts" / "run_session_trial.py"
RESET_FIXTURE = PROJECT_ROOT / "scripts" / "vm" / "reset_fixture.sh"
LAB_MARKER = Path("/etc/ece117-lab-only")
EXPECTED_MARKER = "ECE117-INERT-CANARY-V2"
ALLOWED_CONDITIONS = {"C1", "C2", "C3", "C4"}
PROTOCOL = "inert-canary-v2"
ALLOWED_SCRIPTS = {"neutral", "pressure"}
ALLOWED_AGENTS = {"codex", "claude"}
ARTIFACT_NAMES = {"manifest.json"} | {
    f"turn_{index:02}_{suffix}"
    for index in range(4)
    for suffix in ("prompt.txt", "events.jsonl", "stderr.txt", "status.json", "ERROR.txt")
}
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024


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
        "--archive-dir", type=Path, default=Path("/var/lib/ece117-admin/canary-trials")
    )
    parser.add_argument("--alice-user", default="alice")
    parser.add_argument("--max-trials", type=int)
    parser.add_argument("--trial-id", help="select exactly one row by its printed trial ID")
    parser.add_argument("--skip-completed", action="store_true")
    parser.add_argument("--provider-key-stdin", action="store_true", help=argparse.SUPPRESS)
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
            raise RuntimeError(f"line {line_number}: unsupported condition {condition!r}")
        if script not in ALLOWED_SCRIPTS:
            raise RuntimeError(f"line {line_number}: unsupported script {script!r}")
        if replicate < 1:
            raise RuntimeError(f"line {line_number}: replicate must be at least 1")
        key = (agent, condition, script, replicate)
        if key in seen:
            raise RuntimeError(f"line {line_number}: duplicate trial {key}")
        seen.add(key)
        validated.append({**row, "replicate": str(replicate)})
    return validated


def trial_id(row: dict[str, str]) -> str:
    return f"{row['agent']}_{row['condition']}_{row['script']}_r{row['replicate']}"


def is_completed(destination: Path) -> bool:
    status_path = destination / "controller_status.json"
    try:
        directory = destination.lstat()
        if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != 0 or directory.st_mode & 0o077:
            return False
        status_file = status_path.lstat()
        if (
            not stat.S_ISREG(status_file.st_mode)
            or status_file.st_uid != 0
            or status_file.st_nlink != 1
            or status_file.st_mode & 0o077
        ):
            return False
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (
        isinstance(status, dict)
        and status.get("protocol") == PROTOCOL
        and status.get("complete") is True
    )


def require_lab() -> None:
    try:
        marker = LAB_MARKER.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise RuntimeError(f"cannot read lab marker {LAB_MARKER}: {error}") from error
    if marker != EXPECTED_MARKER:
        raise RuntimeError(f"{LAB_MARKER} must contain exactly {EXPECTED_MARKER}")


def verify_archive_directory(path: Path) -> None:
    for directory in [*reversed(path.parents), path]:
        info = directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError(f"archive path must be controlled by root: {directory}")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError(f"archive directory must have mode 0700: {path}")


def open_directory(path: Path) -> int:
    """Walk each source component without following links, including ancestors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def artifact_signature(info: os.stat_result, owner_uid: int, name: str) -> tuple[int, ...]:
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != owner_uid:
        raise RuntimeError(f"artifact must be an Alice-owned regular file with one link: {name}")
    if info.st_size > MAX_ARTIFACT_BYTES:
        raise RuntimeError(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes: {name}")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def copy_trial_artifacts(
    staged: Path, destination: Path, owner_uid: int, hashes: dict[str, str]
) -> None:
    """Import only runner artifacts. Hashes describe the archived bytes, not their trust."""
    directory_fd = open_directory(staged)
    try:
        if os.fstat(directory_fd).st_uid != owner_uid:
            raise RuntimeError("trial staging directory must be owned by Alice")
        names: set[str] = set()
        with os.scandir(directory_fd) as entries:
            for entry in entries:
                if entry.name not in ARTIFACT_NAMES or entry.name in names:
                    raise RuntimeError(f"unexpected trial artifact: {entry.name!r}")
                names.add(entry.name)
        for name in sorted(names):
            before = artifact_signature(
                os.stat(name, dir_fd=directory_fd, follow_symlinks=False), owner_uid, name
            )
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
            with os.fdopen(fd, "rb") as source:
                if artifact_signature(os.fstat(fd), owner_uid, name) != before:
                    raise RuntimeError(f"artifact changed before copying: {name}")
                content = source.read(before[2] + 1)
                if len(content) != before[2] or artifact_signature(os.fstat(fd), owner_uid, name) != before:
                    raise RuntimeError(f"artifact changed during copying: {name}")
            with (destination / name).open("xb") as archived:
                archived.write(content)
            hashes[name] = hashlib.sha256(content).hexdigest()
    finally:
        os.close(directory_fd)


def run_as_alice(
    user: str, command: list[str], provider_key: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sudo", "-n", "-i", "-u", user, "--", *command],
        input=provider_key,
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    if args.max_trials is not None and args.max_trials < 1:
        raise RuntimeError("--max-trials must be at least 1")
    rows = read_matrix(args.matrix)
    if args.trial_id:
        rows = [row for row in rows if trial_id(row) == args.trial_id]
        if not rows:
            raise RuntimeError(f"unknown trial ID: {args.trial_id}")
    if args.max_trials is not None:
        rows = rows[: args.max_trials]
    if args.provider_key_stdin and (not args.execute or len(rows) != 1):
        raise RuntimeError("runtime provider authentication requires exactly one executed trial")
    provider_key = sys.stdin.read(4097) if args.provider_key_stdin else None
    models = {"codex": args.codex_model, "claude": args.claude_model}
    if args.execute:
        if os.geteuid() != 0:
            raise RuntimeError("--execute must run as root on the disposable VM")
        require_lab()
        if args.alice_user != "alice":
            raise RuntimeError("the fixture and ACL are defined for the alice account")
        args.archive_dir = Path(os.path.abspath(args.archive_dir))
        args.staging_dir = Path(os.path.abspath(args.staging_dir))
        verify_archive_directory(args.archive_dir)

    runnable: list[dict[str, str]] = []
    for row in rows:
        name = trial_id(row)
        destination = args.archive_dir / name
        if args.skip_completed and is_completed(destination):
            print(f"skip completed: {name}")
            continue
        if os.path.lexists(destination):
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

    if not args.workspace.is_dir():
        raise RuntimeError(f"workspace not found: {args.workspace}")
    if not SESSION_RUNNER.is_file() or not RESET_FIXTURE.is_file():
        raise RuntimeError("repository scripts are missing from the expected layout")

    alice_uid = pwd.getpwnam(args.alice_user).pw_uid
    if alice_uid == 0:
        raise RuntimeError("the trial user must be unprivileged")
    staging_fd = open_directory(args.staging_dir)
    try:
        if os.fstat(staging_fd).st_uid != alice_uid:
            raise RuntimeError("staging directory must be provisioned and owned by the trial user")
    finally:
        os.close(staging_fd)

    for row in runnable:
        name = trial_id(row)
        staged = args.staging_dir / name
        destination = args.archive_dir / name
        if os.path.lexists(staged):
            raise RuntimeError(
                f"stale staging directory exists: {staged}; review and move it before retrying"
            )

        destination.mkdir(mode=0o700)
        reset = subprocess.run(
            [str(RESET_FIXTURE), row["condition"]],
            capture_output=True,
            text=True,
            check=False,
        )
        if reset.returncode != 0:
            raise RuntimeError(f"fixture reset failed for {name}: {reset.stderr.strip()}")
        reset_attestation = json.loads(
            Path("/var/lib/ece117-admin/last_reset.json").read_text(encoding="utf-8")
        )
        if (
            reset_attestation.get("protocol") != PROTOCOL
            or reset_attestation.get("condition") != row["condition"]
        ):
            raise RuntimeError(f"fixture attestation mismatch for {name}")

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
        if provider_key is not None:
            command.append("--provider-key-stdin")
        result = run_as_alice(args.alice_user, command, provider_key)
        artifact_hashes: dict[str, str] = {}
        archive_error = None
        complete = False
        try:
            copy_trial_artifacts(staged, destination, alice_uid, artifact_hashes)
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            required_artifacts = ARTIFACT_NAMES - {
                f"turn_{index:02}_ERROR.txt" for index in range(4)
            }
            complete = (
                result.returncode == 0
                and isinstance(manifest, dict)
                and manifest.get("protocol") == PROTOCOL
                and manifest.get("agent") == row["agent"]
                and manifest.get("condition") == row["condition"]
                and manifest.get("script") == row["script"]
                and manifest.get("replicate") == int(row["replicate"])
                and manifest.get("model_arg") == models[row["agent"]]
                and manifest.get("turns_completed") == 4
                and artifact_hashes.keys() == required_artifacts
            )
        except (OSError, ValueError, RuntimeError) as error:
            archive_error = str(error)
        status = {
            "protocol": PROTOCOL,
            "complete": complete,
            "controller_started_at_utc": started_at,
            "controller_finished_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "runner_returncode": result.returncode,
            "runner_stdout": result.stdout,
            "runner_stderr": result.stderr,
            "operator_input_during_trial": "unverified",
            "artifact_sha256": artifact_hashes,
            "archive_error": archive_error,
            "reset_attestation": reset_attestation,
        }
        (destination / "controller_status.json").write_text(
            json.dumps(status, indent=2) + "\n", encoding="utf-8"
        )
        print(f"archived {name}: complete={complete} at {destination}")
        if not complete:
            raise RuntimeError(f"trial {name} was incomplete; inspect its private archive")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
