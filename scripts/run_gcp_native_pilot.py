#!/usr/bin/env python3
"""Run a frozen native authorization pilot campaign on one disposable GCP VM."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

if __package__:
    from .provider_auth import prompt_provider_keys
    from .run_native_pilot import load_campaign, verify_calibration, verify_campaign, verify_smoke_receipt, write_json
else:
    from provider_auth import prompt_provider_keys
    from run_native_pilot import load_campaign, verify_calibration, verify_campaign, verify_smoke_receipt, write_json


MAX_UPLOAD_BYTES = 256 * 1024 * 1024


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("timeout", 600)
    return subprocess.run(command, check=True, **kwargs)


def wait_for_ssh(ssh: list[str], log) -> None:
    for attempt in range(8):
        try:
            probe = subprocess.run(
                [*ssh, "--ssh-flag=-oConnectTimeout=10", "--command=true"],
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                check=False, timeout=25,
            )
            if probe.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        if attempt < 7:
            time.sleep(5)
    raise ValueError("IAP SSH did not become ready. Check the VM identity and operator log.")


def image_record(args: argparse.Namespace) -> dict:
    result = run([
        "gcloud", "compute", "images", "describe", args.image,
        f"--project={args.project}", "--format=json",
    ], capture_output=True, text=True)
    image = json.loads(result.stdout)
    expected = f"ECE117 inert-canary bundle SHA-256 {args.bundle_sha256}"
    if image.get("status") != "READY" or image.get("description") != expected:
        raise ValueError("image is not READY or is not bound to the supplied bundle digest")
    return {"name": args.image, "id": str(image["id"]), "description": expected}


def safe_campaign_copy(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"campaign contains a symlink: {path}")
    shutil.copytree(source, destination)


def make_upload(source: Path, target: Path) -> None:
    with tarfile.open(target, "w:gz") as archive:
        archive.add(source, arcname="native-pilot-campaign", recursive=True)
    if target.stat().st_size > MAX_UPLOAD_BYTES:
        raise ValueError("campaign upload exceeds the pilot size limit")


def extract_export(archive_path: Path, destination: Path) -> Path:
    campaign = destination / "native-pilot-campaign"
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    total = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = Path(member.name)
            if (
                not path.parts
                or path.parts[0] != "native-pilot-campaign"
                or path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
                or path in names
                or not (member.isdir() or member.isfile())
            ):
                raise ValueError(f"unsafe evidence archive member: {member.name}")
            names.add(path)
            total += member.size
            if total > MAX_UPLOAD_BYTES:
                raise ValueError("evidence archive exceeds the pilot size limit")
        for member in members:
            output = destination / member.name
            if member.isdir():
                output.mkdir(mode=0o700, parents=True, exist_ok=True)
            else:
                output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError(f"missing archive bytes: {member.name}")
                output.write_bytes(source.read())
                output.chmod(0o600)
    return campaign


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("calibrate", "run"))
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    for option in ("project", "zone", "subnet", "image"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--bundle-sha256", required=True)
    parser.add_argument("--machine-type", default="e2-small")
    parser.add_argument("--max-sessions", type=int)
    parser.add_argument("--mode", choices=("single", "fixed", "response-conditioned"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-live-costs", action="store_true")
    return parser.parse_args()


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    plan, plan_hash = load_campaign(args.campaign)
    if not re.fullmatch(r"[0-9a-f]{64}", args.bundle_sha256):
        raise ValueError("--bundle-sha256 must be 64 lowercase hexadecimal characters")
    if args.max_sessions is not None and args.max_sessions < 1:
        raise ValueError("--max-sessions must be positive")
    rows = [row for row in plan["sessions"] if not args.mode or row["interaction_mode"] == args.mode]
    if not rows or args.phase == "calibrate" and (args.mode or args.max_sessions):
        raise ValueError("select an interaction mode from the plan only for live collection")
    print(
        f"{args.phase}: {plan['plan']} (up to {min(len(rows), args.max_sessions or len(rows))} sessions, model {plan['model']}) "
        f"on disposable image {args.image}; plan SHA-256 {plan_hash}"
    )
    if not args.execute:
        print("Dry run only: no VM or model session was created. Add --execute after review.")
        return
    if args.phase == "run" and not args.confirm_live_costs:
        raise ValueError("live model execution requires --confirm-live-costs")
    if args.output.exists():
        raise FileExistsError("choose a new --output directory so prior evidence is preserved")
    image = image_record(args)
    if args.phase == "run":
        calibration = verify_calibration(args.campaign, plan_hash)
        identity = calibration.get("gcp", {})
        if identity.get("image") != image or identity.get("project") != args.project:
            raise ValueError("use deterministic calibration from the same image and project")
        verify_smoke_receipt(args.campaign, plan, plan_hash, calibration)
        verify_campaign(args.campaign)
    vm = "safesandbox-native-" + uuid.uuid4().hex[:12]
    scope = [f"--project={args.project}", f"--zone={args.zone}"]
    ssh = ["gcloud", "compute", "ssh", vm, *scope, "--tunnel-through-iap"]
    provider_key = None
    if args.phase == "run":
        provider_key = prompt_provider_keys(("codex",))["codex"]
    with tempfile.TemporaryDirectory() as temporary:
        temp = Path(temporary)
        staged = temp / "native-pilot-campaign"
        safe_campaign_copy(args.campaign, staged)
        write_json(staged / "gcp_environment.json", {
            "project": args.project, "zone": args.zone, "subnet": args.subnet,
            "image": image, "vm": vm, "machine_type": args.machine_type,
            "bundle_sha256": args.bundle_sha256, "plan_sha256": plan_hash,
        })
        upload = temp / "native-pilot-upload.tar.gz"
        make_upload(staged, upload)
        args.output.mkdir(mode=0o700, parents=True)
        log_path = args.output / "operator.log"
        write_json(args.output / "operation.json", {"vm": vm, "project": args.project, "zone": args.zone})
        print(f"Evidence and VM identity will be recorded in {args.output}.", flush=True)
        with log_path.open("wb") as log:
            run([
                "gcloud", "compute", "instances", "create", vm, *scope,
                f"--subnet={args.subnet}", f"--machine-type={args.machine_type}",
                f"--image={args.image}", f"--image-project={args.project}",
                "--no-address", "--no-service-account", "--no-scopes",
            ], stdout=log, stderr=subprocess.STDOUT)
            wait_for_ssh(ssh, log)
            run([
                "gcloud", "compute", "scp", str(upload), f"{vm}:~/native-pilot-upload.tar.gz",
                *scope, "--tunnel-through-iap",
            ], stdout=log, stderr=subprocess.STDOUT)
            remote_root = "/var/lib/ece117-admin/native-pilot-run"
            prepare = (
                f"sudo -n install -d -m 0700 {remote_root} && "
                f"sudo -n tar --no-same-owner -xzf \"$HOME/native-pilot-upload.tar.gz\" -C {remote_root}"
            )
            run([*ssh, f"--command={prepare}"], stdout=log, stderr=subprocess.STDOUT)
            remote_campaign = f"{remote_root}/native-pilot-campaign"
            remote = (
                f"sudo -n python3 /opt/ece117/scripts/run_native_pilot.py {args.phase} "
                f"--campaign {remote_campaign} --execute"
            )
            timeout = 600
            if args.phase == "run":
                if args.max_sessions:
                    remote += f" --max-sessions {args.max_sessions}"
                if args.mode:
                    remote += f" --mode {args.mode}"
                remote += " --provider-key-stdin"
                timeout = sum(row["max_turns"] for row in rows) * 330 + 300
            try:
                result = subprocess.run(
                    [*ssh, "--ssh-flag=-T", f"--command={remote}"],
                    input=provider_key.encode() if provider_key else None,
                    stdout=log, stderr=subprocess.STDOUT,
                    check=False, timeout=timeout,
                )
                guest_exit = result.returncode
            except subprocess.TimeoutExpired:
                raise ValueError(f"guest SSH timed out. Check VM {vm} before exporting or resuming") from None
            export = args.output / "evidence.tar.gz"
            remote_archive = (
                f"sudo -n tar -C {remote_root} -czf - native-pilot-campaign"
            )
            with export.open("xb") as target:
                run([*ssh, f"--command={remote_archive}"], stdout=target, stderr=log)
        extracted = extract_export(args.output / "evidence.tar.gz", args.output / "campaign")
        _, exported_hash = load_campaign(extracted)
        if exported_hash != plan_hash:
            raise ValueError("exported plan differs from requested plan")
        coverage = verify_campaign(extracted)
        write_json(args.output / "verification.json", coverage)
        print(f"Verified export at {extracted}. Coverage {coverage['verified']}/{coverage['planned']} sessions.")
        if guest_exit:
            raise ValueError(f"guest command failed. VM {vm} retained. Inspect {log_path}")
        if args.phase == "calibrate":
            verify_calibration(extracted, plan_hash)
        if coverage["incomplete"]:
            raise ValueError(f"campaign has incomplete sessions. VM {vm} retained. Resume from {extracted}")
        with log_path.open("ab") as log:
            run([
                "gcloud", "compute", "instances", "delete", vm, *scope, "--quiet",
            ], stdout=log, stderr=subprocess.STDOUT)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyError, OSError, TypeError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"error: {error}") from error
