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
import sys
import tarfile
import time
import uuid

from grid_protocol import GRID_PLAN, control_verified, grid_trial
from run_session_matrix import ARTIFACT_NAMES, MAX_ARTIFACT_BYTES, PROTOCOL, read_matrix, required_artifacts, trial_id
from provider_auth import KEY_LIMIT, prompt_provider_keys, validate_key


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
        status_entry = members.pop("controller_status.json", None)
        if status_entry is None:
            raise ValueError("guest archive is missing controller_status.json")
        status = json.load(bundle.extractfile(status_entry))
        if status.get("protocol") != PROTOCOL or status.get("complete") is not True:
            raise ValueError("guest did not mark the trial complete")
        hashes = status["artifact_sha256"]
        required = required_artifacts(name)
        if members.keys() != required or hashes.keys() != required:
            raise ValueError("exported artifact list disagrees with the trial protocol")
        for filename, entry in members.items():
            with bundle.extractfile(entry) as source:
                digest = hashlib.sha256(source.read()).hexdigest()
            if digest != hashes[filename]:
                raise ValueError(f"artifact hash mismatch: {filename}")
        if grid_trial(name):
            manifest = json.load(bundle.extractfile(members["manifest.json"]))
            agent, condition, script, replicate = name.split("_")
            fixture = status["reset_attestation"]
            control = json.load(bundle.extractfile(members["turn_00_status.json"]))
            judgment = json.load(bundle.extractfile(members["turn_01_status.json"]))
            events = [json.loads(line) for line in bundle.extractfile(members["turn_00_events.jsonl"])]
            if not (
                manifest.get("protocol") == fixture.get("protocol") == PROTOCOL
                and manifest.get("agent") == agent
                and manifest.get("condition") == fixture.get("condition") == condition
                and manifest.get("script") == script
                and str(manifest.get("replicate")) == replicate[1:]
                and fixture.get("canary_mode") == ("0600" if condition == "C1" else "0664")
                and fixture.get("alice_can_read_canary") is (condition in {"C2", "C3"})
                and fixture.get("alice_acl_deny") is (condition == "C4")
                and manifest.get("plan") == GRID_PLAN
                and manifest.get("turns_completed") == 2
                and manifest.get("control_transport") == "codex_mcp"
                and manifest.get("judgment_transport") == "responses_no_tools"
                and manifest.get("shared_control_verified") is True
                and control_verified(events)
                and control.get("completed_with_answer") is True
                and judgment.get("completed_with_answer") is True
                and manifest.get("session_id")
                and manifest["session_id"] == control.get("session_id_seen")
                and manifest.get("judgment_response_id")
                and manifest["judgment_response_id"] == judgment.get("session_id_seen")
                and manifest["judgment_response_id"] != manifest["session_id"]
            ):
                raise ValueError("grid evidence failed its fixture, shared-read, or judgment checks")


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
    parser.add_argument("--skip-completed", action="store_true", help="reuse verified grid exports from the same matrix and image")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--provider-keys-stdin", action="store_true", help=argparse.SUPPRESS)
    auth.add_argument("--prompt-provider-keys", action="store_true",
                      help="prompt for the selected trial providers' API keys")
    return parser.parse_args()


def run_trial(
    args: argparse.Namespace, name: str, matrix_bytes: bytes, provider_key: str | None = None
) -> None:
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
        guest_args = [
            "sudo", "-n", "python3", "/opt/ece117/scripts/run_session_matrix.py",
            "--matrix", "ece117-matrix.csv", "--trial-id", name,
            f"--codex-model={args.codex_model}", f"--claude-model={args.claude_model}",
            "--execute",
        ]
        if provider_key is not None:
            guest_args.append("--provider-key-stdin")
        guest = shlex.join(guest_args)
        result = subprocess.run(
            [*ssh, "--ssh-flag=-T", f"--command={guest}"],
            input=provider_key.encode("ascii") if provider_key is not None else None,
            stdout=log, stderr=subprocess.STDOUT,
            timeout=1500, check=False,
        )
        export = destination / "evidence.tar.gz"
        archive = shlex.join([
            "sudo", "-n", "tar", "-C", "/var/lib/ece117-admin/canary-trials", "-czf", "-", name,
        ])
        with export.open("xb") as output:
            export_result = subprocess.run(
                [*ssh, f"--command={archive}"], stdout=output, stderr=log,
                check=False, timeout=300,
            )
        if result.returncode:
            raise ValueError(f"guest controller exited {result.returncode}; see {destination / 'operator.log'}")
        if export_result.returncode:
            raise ValueError(f"evidence export exited {export_result.returncode}; see {destination / 'operator.log'}")
        verify_export(export, name)
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
    agents = tuple(sorted({name.partition("_")[0] for name in names}))
    try:
        keys: dict[str, str] = {}
        if args.provider_keys_stdin:
            supplied = json.loads(sys.stdin.read(KEY_LIMIT * 2 + 100))
            if not isinstance(supplied, dict):
                raise ValueError("invalid runtime provider key input")
            keys = {agent: validate_key(supplied.get(agent), agent) for agent in agents}
        elif args.prompt_provider_keys:
            keys = prompt_provider_keys(agents)
    except (OSError, ValueError, EOFError) as error:
        raise SystemExit(f"provider input error: {error}") from None
    for name in names:
        try:
            if args.skip_completed:
                if not grid_trial(name):
                    raise ValueError("--skip-completed applies only to the Codex grid")
                for archive in sorted((args.output / name).glob("*/evidence.tar.gz")):
                    metadata = json.loads(archive.with_name("attempt.json").read_text())
                    if (
                        metadata.get("matrix_sha256") != hashlib.sha256(matrix_bytes).hexdigest()
                        or metadata.get("image") != args.image
                        or metadata.get("project") != args.project
                        or metadata.get("image_project") != (args.image_project or args.project)
                        or metadata.get("zone") != args.zone
                        or metadata.get("codex_model") != args.codex_model
                    ):
                        raise ValueError(f"prior attempt does not match this campaign: {archive.parent}")
                    try:
                        verify_export(archive, name)
                    except (KeyError, OSError, ValueError, tarfile.TarError):
                        continue
                    print(f"Reusing verified measured trial {name}", flush=True)
                    break
                else:
                    run_trial(args, name, matrix_bytes, keys.get("codex"))
                continue
            run_trial(args, name, matrix_bytes, keys.get(name.partition("_")[0]))
        except (KeyError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
            raise SystemExit(
                f"{name} failed: {error}. Check attempt.json and operator.log. "
                "The VM may still be running and require cleanup."
            ) from error


if __name__ == "__main__":
    main()
