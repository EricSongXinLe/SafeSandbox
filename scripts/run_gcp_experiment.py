#!/usr/bin/env python3
"""Build or verify the experiment image, calibrate both agents, and collect evidence."""

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

SCRIPTS = Path(__file__).resolve().parent
CALIBRATION_IDS = ("codex_C3_pressure_r1", "claude_C3_pressure_r1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("calibrate", "collect"))
    for option in ("project", "zone", "subnet", "image", "codex-model", "claude-model"):
        parser.add_argument(f"--{option}", required=True)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--sha256", required=True, help="trusted checksum for the uploaded bundle")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--plan", choices=("focused24", "factorial48"), default="focused24")
    parser.add_argument("--builder", help="existing prepared Ubuntu builder with both CLIs installed")
    parser.add_argument("--execute", action="store_true", help="create billable resources")
    parser.add_argument("--calibration-reviewed", action="store_true",
                        help="confirm the exported calibration traces and selected controls were reviewed")
    return parser.parse_args()


def verify_bundle(path: Path, checksum: str) -> None:
    if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError("bundle checksum differs from --sha256")
    with tarfile.open(path, "r:gz") as archive:
        for script in ("run_gcp_experiment.py", "build_gcp_canary_image.sh",
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


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    if args.builder and args.phase == "collect":
        raise ValueError("collect reuses the image recorded during calibration")
    if not args.execute:
        setting = f"build from {args.builder}" if args.builder else f"reuse {args.image}"
        print(f"Dry run: {args.phase} in {args.project}/{args.zone}, {setting}")
        print(f"Plan: {args.plan}, evidence directory: {args.output}")
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
                 "ZONE": args.zone, "SUBNET": args.subnet},
        )
    configuration = {
        "project": args.project, "zone": args.zone, "subnet": args.subnet,
        "image": args.image, "image_id": image_identity(args), "sha256": args.sha256,
        "plan": args.plan, "codex_model": args.codex_model, "claude_model": args.claude_model,
    }
    matrix = args.output / f"{args.plan}.csv"
    launcher = (
        sys.executable, str(SCRIPTS / "run_gcp_canary_suite.py"), "--matrix", str(matrix),
        "--project", args.project, "--zone", args.zone, "--subnet", args.subnet,
        "--image", args.image, "--codex-model", args.codex_model,
        "--claude-model", args.claude_model, "--execute",
    )
    if args.phase == "calibrate":
        run(sys.executable, str(SCRIPTS / "generate_session_matrix.py"),
            "--plan", args.plan, "--seed", "117", "--output", str(matrix))
        calibration = args.output / "calibration" / uuid.uuid4().hex
        for name in CALIBRATION_IDS:
            run(*launcher, "--trial-id", name, "--output", str(calibration))
            exports = list((calibration / name).glob("*/evidence.tar.gz"))
            if len(exports) != 1:
                raise ValueError(f"expected one evidence archive for {name}")
            check_calibration(exports[0], name)
        record = {
            "configuration": configuration,
            "matrix_sha256": hashlib.sha256(matrix.read_bytes()).hexdigest(),
            "calibration_dir": str(calibration.resolve()),
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
        measured.mkdir()
        run(*launcher, "--output", str(measured))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        raise SystemExit(f"error: {error}") from error
