#!/usr/bin/env python3
"""Build or verify an experiment image, calibrate the selected agents, and collect evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid

from run_gcp_canary_suite import verify_export
from provider_auth import prompt_provider_keys

SCRIPTS = Path(__file__).resolve().parent
CALIBRATION_IDS = ("codex_C3_pressure_r1", "claude_C3_pressure_r1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("calibrate", "collect"))
    for option in ("project", "zone", "subnet", "image", "codex-model"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--claude-model", help="required unless --codex-only is selected")
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--sha256", required=True, help="trusted checksum for the uploaded bundle")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", choices=("focused24", "factorial48", "wording24"), default="focused24")
    parser.add_argument("--codex-only", action="store_true",
                        help="use a separate matrix and receipt for Codex-only collection")
    parser.add_argument("--builder", help="existing prepared Ubuntu builder with the selected CLIs installed")
    parser.add_argument("--agent", choices=("codex", "claude"),
                        help="calibrate one agent without changing the collection scope")
    parser.add_argument("--resume-calibration", type=Path,
                        help="reuse verified exports from a previous calibration directory")
    parser.add_argument("--execute", action="store_true", help="create billable resources")
    parser.add_argument("--use-vm-auth", action="store_true",
                        help="use authentication already provisioned on each trial VM")
    parser.add_argument("--calibration-reviewed", action="store_true",
                        help="confirm the exported calibration traces and selected controls were reviewed")
    args = parser.parse_args()
    if not args.codex_only and not args.claude_model:
        parser.error("--claude-model is required unless --codex-only is selected")
    if args.codex_only:
        if args.agent == "claude":
            parser.error("--agent claude cannot be used with --codex-only")
        args.claude_model = "not-used"
    return args


def verify_bundle(path: Path, checksum: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError("bundle checksum differs from --sha256")
    with tarfile.open(path, "r:gz") as archive:
        # The Cloud Shell entry point can be updated independently of the VM image.
        for script in ("build_gcp_canary_image.sh", "provider_auth.py",
                       "run_gcp_canary_suite.py", "generate_session_matrix.py",
                       "run_session_matrix.py", "run_session_trial.py"):
            content = archive.extractfile(f"scripts/{script}")
            if content is None or content.read() != (SCRIPTS / script).read_bytes():
                raise ValueError(f"run this workflow from the matching bundle: {script}")


def run(*command: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, **kwargs)


def image_identity(args: argparse.Namespace) -> str:
    result = run(
        "gcloud", "compute", "images", "describe", args.image,
        f"--project={args.project}", "--format=json", capture_output=True, text=True,
    )
    image = json.loads(result.stdout)
    expected = f"ECE117 inert-canary bundle SHA-256 {args.sha256}"
    if image.get("status") != "READY" or image.get("description") != expected:
        raise ValueError("image is not ready or its bundle checksum does not match")
    return str(image["id"])


def check_calibration(path: Path, name: str) -> None:
    verify_export(path, name)
    with tarfile.open(path, "r:gz") as archive:
        for turn in range(4):
            status_file = f"{name}/turn_{turn:02}_status.json"
            with archive.extractfile(status_file) as source:
                if json.load(source).get("completed_with_answer") is not True:
                    raise ValueError(f"{name} turn {turn + 1} lacks verified completion")


def verified_attempt(
    calibration: Path, name: str, configuration: dict[str, str], matrix_sha256: str
) -> Path | None:
    expected = {
        field: configuration[field]
        for field in ("project", "zone", "image", "codex_model", "claude_model")
    }
    expected.update(
        trial_id=name, image_project=configuration["project"], matrix_sha256=matrix_sha256
    )
    for archive in sorted((calibration / name).glob("*/evidence.tar.gz")):
        metadata = json.loads(archive.with_name("attempt.json").read_text(encoding="utf-8"))
        if any(metadata.get(field) != value for field, value in expected.items()):
            raise ValueError(f"calibration attempt configuration differs: {archive.parent}")
        try:
            check_calibration(archive, name)
        except (KeyError, OSError, ValueError, tarfile.TarError):
            continue  # Keep the failed attempt and look for another verified export.
        with tarfile.open(archive, "r:gz") as bundle:
            with bundle.extractfile(f"{name}/manifest.json") as manifest:
                if json.load(manifest).get("provider_auth") != configuration["provider_auth"]:
                    raise ValueError(f"calibration authentication mode differs: {archive.parent}")
        return archive
    return None


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    if args.phase == "collect" and (args.builder or args.agent or args.resume_calibration):
        raise ValueError("collect requires calibration for its full scope and reuses the recorded image")
    if args.builder and args.resume_calibration:
        raise ValueError("resume calibration with the existing image; omit --builder")
    calibration_ids = CALIBRATION_IDS
    if args.plan == "wording24":
        calibration_ids = tuple(name.replace("_pressure_", "_plain_") for name in calibration_ids)
    if args.codex_only:
        calibration_ids = calibration_ids[:1]
    selected = tuple(name for name in calibration_ids if not args.agent or name.startswith(args.agent + "_"))
    scope = "codex" if args.codex_only else "both"
    if not args.execute:
        setting = f"build from {args.builder}" if args.builder else f"reuse {args.image}"
        print(f"Dry run: {args.phase} in {args.project}/{args.zone}, {setting}")
        print(f"Plan: {args.plan}, agents: {scope}, evidence directory: {args.output}")
        if args.phase == "calibrate":
            print(f"Calibration rows: {', '.join(selected)}")
        return

    verify_bundle(args.bundle, args.sha256)
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = args.output / "calibration.json"
    measured = args.output / "measured"
    if args.phase == "calibrate" and receipt.exists():
        raise ValueError("calibration already recorded; use collect or choose a new --output")
    if args.phase == "collect":
        if not args.calibration_reviewed or not receipt.is_file():
            raise ValueError("collect requires a successful calibration and --calibration-reviewed")
        if measured.exists():
            raise ValueError("measured output already exists; use the trial launcher for outstanding rows")

    if args.builder:
        run(
            "bash", str(SCRIPTS / "build_gcp_canary_image.sh"), "build",
            env={**os.environ, "BUILDER": args.builder, "BUNDLE": str(args.bundle.resolve()),
                 "BUNDLE_SHA": args.sha256, "IMAGE": args.image, "PROJECT": args.project,
                 "ZONE": args.zone, "SUBNET": args.subnet, "ECE117_TRIAL_AGENTS": scope},
        )
    configuration = {
        "project": args.project, "zone": args.zone, "subnet": args.subnet,
        "image": args.image, "image_id": image_identity(args), "sha256": args.sha256,
        "plan": args.plan, "codex_model": args.codex_model, "claude_model": args.claude_model,
        "provider_auth": "vm_configured" if args.use_vm_auth else "runtime_api_key",
    }
    if args.codex_only:
        configuration["agent_scope"] = scope
    matrix_suffix = "-codex" if args.codex_only else ""
    matrix = args.output / f"{args.plan}{matrix_suffix}.csv"
    launcher = [
        sys.executable, str(SCRIPTS / "run_gcp_canary_suite.py"), "--matrix", str(matrix),
        "--project", args.project, "--zone", args.zone, "--subnet", args.subnet,
        "--image", args.image, "--codex-model", args.codex_model,
        "--claude-model", args.claude_model, "--execute",
    ]
    if not args.use_vm_auth:
        launcher.append("--provider-keys-stdin")
    if args.phase == "calibrate":
        calibration_root = args.output / "calibration"
        if args.resume_calibration:
            calibration = args.resume_calibration.resolve()
            if calibration.parent != calibration_root.resolve() or not calibration.is_dir():
                raise ValueError("--resume-calibration must be an existing run directory under --output/calibration")
        else:
            run(sys.executable, str(SCRIPTS / "generate_session_matrix.py"),
                "--plan", args.plan, "--seed", "117", "--output", str(matrix),
                *(("--codex-only",) if args.codex_only else ()))
            calibration = calibration_root / uuid.uuid4().hex
        matrix_sha256 = hashlib.sha256(matrix.read_bytes()).hexdigest()
        verified = {}
        if args.resume_calibration:
            for name in calibration_ids:
                archive = verified_attempt(calibration, name, configuration, matrix_sha256)
                if archive is not None:
                    verified[name] = archive
                    print(f"Reusing verified {name}: {archive}")
        pending = [name for name in selected if name not in verified]
        agents = tuple(name.partition("_")[0] for name in pending)
        keys = prompt_provider_keys(agents) if agents and not args.use_vm_auth else {}
        for name in pending:
            agent = name.partition("_")[0]
            key_input = json.dumps({agent: keys[agent]}) if keys else None
            run(*launcher, "--trial-id", name, "--output", str(calibration), input=key_input, text=True)
            archive = verified_attempt(calibration, name, configuration, matrix_sha256)
            if archive is None:
                raise ValueError(f"no verified evidence archive for {name}")
            verified[name] = archive
        if len(verified) != len(calibration_ids):
            print(f"Partial calibration saved in {calibration}.")
            print("Full collection requires both agents. Resume this directory when ready.")
            return
        record = {
            "configuration": configuration,
            "matrix_sha256": matrix_sha256,
            "calibration_dir": str(calibration.resolve()),
            "exports": {name: str(archive.resolve()) for name, archive in verified.items()},
        }
        with receipt.open("x") as target:
            json.dump(record, target, indent=2)
        print(f"Calibration complete. Review the traces in {calibration}.")
    else:
        record = json.loads(receipt.read_text())
        if record["configuration"] != configuration:
            raise ValueError("image or experiment configuration differs from calibration")
        if record["matrix_sha256"] != hashlib.sha256(matrix.read_bytes()).hexdigest():
            raise ValueError("matrix changed after calibration")
        agents = tuple(name.partition("_")[0] for name in calibration_ids)
        keys = {} if args.use_vm_auth else prompt_provider_keys(agents)
        measured.mkdir()
        run(*launcher, "--output", str(measured), input=json.dumps(keys) if keys else None, text=True)


if __name__ == "__main__":
    try:
        main()
    except (EOFError, KeyError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"error: {error}") from error
