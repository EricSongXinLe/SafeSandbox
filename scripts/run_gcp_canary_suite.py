#!/usr/bin/env python3
"""Run each inert-canary matrix row on a separate GCP VM from a prepared image."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import time
import uuid

from run_session_matrix import ARTIFACT_NAMES, MAX_ARTIFACT_BYTES, PROTOCOL, read_matrix, trial_id


def verify_export(path: Path, name: str) -> None:
    with tarfile.open(path, "r:gz") as bundle:
        members = {}
        for entry in bundle:
            if entry.name == name and entry.isdir():
                continue
            directory, _, filename = entry.name.partition("/")
            if (
                directory != name
                or filename not in ARTIFACT_NAMES | {"controller_status.json"}
                or filename in members
                or not entry.isfile()
                or entry.size > MAX_ARTIFACT_BYTES
            ):
                raise ValueError(f"unexpected archive member: {entry.name}")
            members[filename] = entry
        status = json.load(bundle.extractfile(members.pop("controller_status.json")))
        if status.get("protocol") != PROTOCOL or status.get("complete") is not True:
            raise ValueError("guest did not mark the trial complete")
        hashes = status["artifact_sha256"]
        required = {filename for filename in ARTIFACT_NAMES if not filename.endswith("_ERROR.txt")}
        if members.keys() != required or hashes.keys() != required:
            raise ValueError("exported artifact list disagrees with the expected four turns")
        for filename, entry in members.items():
            with bundle.extractfile(entry) as source:
                digest = hashlib.sha256(source.read()).hexdigest()
            if digest != hashes[filename]:
                raise ValueError(f"artifact hash mismatch: {filename}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--trial-id", help="run only the selected row")
    parser.add_argument("--project", required=True)
    parser.add_argument("--zone", required=True)
    parser.add_argument("--subnet", required=True)
    parser.add_argument("--image", required=True, help="exact prepared Compute Engine image name")
    parser.add_argument("--image-project", help="defaults to --project")
    parser.add_argument("--machine-type", default="e2-small")
    parser.add_argument("--codex-model", required=True)
    parser.add_argument("--claude-model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="create billable VMs; default is a plan")
    return parser.parse_args()


def run_trial(args: argparse.Namespace, name: str, matrix_bytes: bytes) -> None:
    attempt = uuid.uuid4().hex[:12]
    vm = f"ece117-canary-{attempt}"
    destination = args.output / name / attempt
    destination.mkdir(parents=True)
    (destination / "matrix.csv").write_bytes(matrix_bytes)
    metadata = {
        "trial_id": name,
        "project": args.project,
        "zone": args.zone,
        "vm": vm,
        "image": args.image,
        "image_project": args.image_project or args.project,
        "codex_model": args.codex_model,
        "claude_model": args.claude_model,
        "matrix_sha256": hashlib.sha256(matrix_bytes).hexdigest(),
    }
    (destination / "attempt.json").write_text(json.dumps(metadata, indent=2) + "\n")
    scope = [f"--project={args.project}", f"--zone={args.zone}"]
    ssh = ["gcloud", "compute", "ssh", vm, *scope, "--tunnel-through-iap"]
    print(f"{name}: {vm} ({destination})", flush=True)
    with (destination / "operator.log").open("wb") as log:
        subprocess.run(
            [
                "gcloud", "compute", "instances", "create", vm, *scope,
                f"--subnet={args.subnet}", f"--machine-type={args.machine_type}",
                f"--image={args.image}", f"--image-project={metadata['image_project']}",
                "--no-address", "--no-service-account", "--no-scopes",
            ],
            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600,
        )
        for attempt in range(8):
            try:
                probe = subprocess.run(
                    [*ssh, "--ssh-flag=-oConnectTimeout=10", "--command=true"],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    timeout=25, check=False,
                )
                if probe.returncode == 0:
                    break
            except subprocess.TimeoutExpired:
                pass
            if attempt < 7:
                time.sleep(5)
        else:
            raise ValueError("IAP SSH did not become ready; see operator.log")
        subprocess.run(
            [
                "gcloud", "compute", "scp", str(destination / "matrix.csv"),
                f"{vm}:~/ece117-matrix.csv", *scope, "--tunnel-through-iap",
            ],
            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300,
        )
        guest = shlex.join([
            "sudo", "-n", "python3", "/opt/ece117/scripts/run_session_matrix.py",
            "--matrix", "ece117-matrix.csv", "--trial-id", name,
            f"--codex-model={args.codex_model}", f"--claude-model={args.claude_model}",
            "--execute",
        ])
        result = subprocess.run(
            [*ssh, f"--command={guest}"], stdout=log, stderr=subprocess.STDOUT,
            timeout=1500, check=False,
        )
        export = destination / "evidence.tar.gz"
        archive = shlex.join([
            "sudo", "-n", "tar", "-C", "/var/lib/ece117-admin/canary-trials", "-czf", "-", name,
        ])
        with export.open("xb") as output:
            subprocess.run(
                [*ssh, f"--command={archive}"], stdout=output, stderr=log,
                check=True, timeout=300,
            )
        verify_export(export, name)
        result.check_returncode()
        subprocess.run(
            ["gcloud", "compute", "instances", "delete", vm, *scope, "--quiet"],
            stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600,
        )


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    matrix_bytes = args.matrix.read_bytes()
    names = [trial_id(row) for row in read_matrix(args.matrix)]
    if args.matrix.read_bytes() != matrix_bytes:
        raise SystemExit("matrix changed while planning")
    if args.trial_id:
        names = [name for name in names if name == args.trial_id]
    if not names:
        raise SystemExit("no matching trials")
    if not args.execute:
        print(f"Dry run: {len(names)} VM(s) in {args.project}/{args.zone}")
        print("\n".join(names))
        return
    for name in names:
        try:
            run_trial(args, name, matrix_bytes)
        except (KeyError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
            raise SystemExit(
                f"{name} failed: {error}. Check attempt.json and operator.log. "
                "The VM may still be running and require cleanup."
            ) from error


if __name__ == "__main__":
    main()
