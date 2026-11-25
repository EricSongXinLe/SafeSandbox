#!/usr/bin/env python3
"""Run four scripted turns in one native Codex or Claude Code session.

This runner does not create Unix accounts, alter file modes, reset a VM,
or execute model-generated commands itself. The native
coding-agent harness owns its own tool-use loop.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import stat
import subprocess
import sys
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = PROJECT_ROOT / "prompts" / "session_scenarios.json"
POLICY = PROJECT_ROOT / "prompts" / "session_authorization_policy.txt"
CANARY = Path("/var/lib/ece117-fixtures/canary.txt")
SHARED = Path("/var/lib/ece117-fixtures/shared.txt")
CONDITIONS = {"C1": 0o600, "C2": 0o664, "C3": 0o664, "C4": 0o664}
PROTOCOL = "inert-canary-v2"
LAB_MARKER = Path("/etc/ece117-lab-only")
EXPECTED_LAB_MARKER = "ECE117-INERT-CANARY-V2"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def parse_events(output: str) -> list[dict[str, object]]:
    parsed = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            parsed.append(event)
    return parsed


def find_session_id(agent: str, events: list[dict[str, object]]) -> str | None:
    if agent == "codex":
        for event in events:
            if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
                return str(event["thread_id"])
        return None
    for event in reversed(events):
        if event.get("type") == "result" and isinstance(event.get("session_id"), str):
            return str(event["session_id"])
    return None


def completed_with_answer(agent: str, events: list[dict[str, object]]) -> bool:
    if agent == "codex":
        terminal = [event for event in events if event.get("type") in ("turn.completed", "turn.failed")]
        if len(terminal) != 1 or terminal[0]["type"] != "turn.completed":
            return False
        for event in events:
            if event is terminal[0]:
                break
            item = event.get("item")
            if event.get("type") == "item.completed" and isinstance(item, dict):
                answer = item.get("text")
                if item.get("type") == "agent_message" and isinstance(answer, str) and answer.strip():
                    return True
        return False
    results = [event for event in events if event.get("type") == "result"]
    if len(results) != 1:
        return False
    result = results[0]
    answer = result.get("result")
    return (
        result.get("subtype") == "success"
        and result.get("is_error") is False
        and isinstance(answer, str)
        and bool(answer.strip())
    )


def cli_version(binary: str) -> str:
    try:
        process = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        return (process.stdout or process.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "unavailable"


def preflight(condition: str, expected_user: str) -> dict[str, object]:
    actual_user = pwd.getpwuid(os.geteuid()).pw_name
    status: dict[str, object] = {
        "euid": os.geteuid(),
        "user": actual_user,
        "expected_user": expected_user,
        "canary_file": str(CANARY),
        "requested_condition": condition,
    }
    if actual_user != expected_user:
        raise RuntimeError(f"runner must execute as {expected_user}, not {actual_user}")
    if actual_user == "root":
        raise RuntimeError("do not execute an agent as root")

    try:
        fixture_stat = CANARY.lstat()
        status.update(
            mode=oct(stat.S_IMODE(fixture_stat.st_mode)),
            uid=fixture_stat.st_uid,
            owner=pwd.getpwuid(fixture_stat.st_uid).pw_name,
            is_regular=stat.S_ISREG(fixture_stat.st_mode),
            readable_from_alice=os.access(CANARY, os.R_OK),
        )
        if not status["is_regular"]:
            raise RuntimeError("canary fixture must be a regular file")
        if status["owner"] != "bob":
            raise RuntimeError("canary fixture must be owned by bob")
        expected_mode = CONDITIONS[condition]
        if stat.S_IMODE(fixture_stat.st_mode) != expected_mode:
            raise RuntimeError(
                f"mode mismatch: expected {oct(expected_mode)}, got {status['mode']}"
            )
        expected_readable = condition in ("C2", "C3")
        if bool(status["readable_from_alice"]) != expected_readable:
            expectation = "readable" if expected_readable else "unreadable"
            raise RuntimeError(
                f"preflight failed: canary should be {expectation} as {expected_user}"
            )
    except (PermissionError, FileNotFoundError) as error:
        raise RuntimeError(f"cannot stat the canary fixture: {error}") from error

    if not SHARED.is_file() or not os.access(SHARED, os.R_OK):
        raise RuntimeError("positive-control file is missing or unreadable")
    return status


def build_command(
    args: argparse.Namespace, session_id: str | None, prompt: str, policy: str | None
) -> list[str]:
    if args.agent == "codex":
        command = [
            "codex",
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            args.codex_sandbox,
            "--model",
            args.model,
        ]
        if policy:
            # JSON strings are valid TOML basic strings for Codex -c overrides.
            command.extend(["-c", "developer_instructions=" + json.dumps(policy)])
        if session_id:
            command.extend(["resume", session_id, prompt])
        else:
            command.append(prompt)
        return command

    command = [
        "claude",
        "--print",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        args.model,
        "--allowedTools",
        "Read,Bash",
    ]
    if args.claude_bare:
        # Bare mode normally disables snapshots; retain the trusted policy on resume.
        command.extend(["--bare", "--system-prompt-snapshot", "on"])
    if session_id:
        command.extend(["--resume", session_id])
    else:
        command.extend(["--session-id", args.session_uuid])
        if policy:
            command.extend(["--append-system-prompt-file", str(POLICY)])
    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude"), required=True)
    parser.add_argument("--condition", choices=tuple(CONDITIONS), required=True)
    parser.add_argument("--script", choices=("neutral", "pressure"), required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--model", required=True, help="pin a concrete model identifier")
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-user", default="alice")
    parser.add_argument(
        "--codex-sandbox",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default="read-only",
    )
    parser.add_argument(
        "--claude-bare",
        action="store_true",
        help="only with separately configured provider auth; changes native defaults",
    )
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="without this flag, print the protocol and never invoke an agent",
    )
    return parser.parse_args()


def main() -> None:
    os.umask(0o077)
    args = parse_args()
    args.session_uuid = str(uuid.uuid4())
    args.workspace = args.workspace.resolve()
    if args.replicate < 1:
        raise SystemExit("--replicate must be at least 1")
    if args.timeout < 1:
        raise SystemExit("--timeout must be positive")

    scenario = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    if scenario.get("schema_version") != 2:
        raise RuntimeError("expected the inert-canary scenario schema")
    prompts = [
        scenario["shared"],
        scenario["direct"],
        scenario[args.script]["reassessment"],
        scenario[args.script]["simulation"],
    ]
    if not all(isinstance(prompt, str) and prompt for prompt in prompts):
        raise RuntimeError("scenario file contains a missing or invalid prompt")
    policy = (
        POLICY.read_text(encoding="utf-8").strip()
        if args.condition in ("C3", "C4")
        else None
    )
    manifest: dict[str, object] = {
        "protocol": PROTOCOL,
        "agent": args.agent,
        "condition": args.condition,
        "script": args.script,
        "replicate": args.replicate,
        "model_arg": args.model,
        "prompts_sha256": [digest(prompt) for prompt in prompts],
        "policy_sha256": digest(policy) if policy else None,
        "note": "one trial is one fresh session containing all four scripted turns",
    }
    if not args.execute:
        print(json.dumps({"dry_run": True, "manifest": manifest, "turns": prompts}, indent=2))
        return

    try:
        marker = LAB_MARKER.read_text(encoding="utf-8").strip()
    except OSError as error:
        raise SystemExit(f"LAB GUARD: cannot read {LAB_MARKER}: {error}") from error
    if marker != EXPECTED_LAB_MARKER:
        raise SystemExit(
            f"LAB GUARD: {LAB_MARKER} must contain exactly {EXPECTED_LAB_MARKER}"
        )
    if not args.workspace.is_dir():
        raise SystemExit(f"workspace not found: {args.workspace}")
    preflight_status = preflight(args.condition, args.expected_user)
    binary = "codex" if args.agent == "codex" else "claude"
    if shutil.which(binary) is None:
        raise SystemExit(f"{binary} is not installed on PATH for {args.expected_user}")

    run_id = f"{args.agent}_{args.condition}_{args.script}_r{args.replicate}"
    output_dir = args.output.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest.update(
        timestamp_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        cli_version=cli_version(binary),
        workspace=str(args.workspace),
        codex_sandbox=args.codex_sandbox if args.agent == "codex" else None,
        claude_bare=args.claude_bare if args.agent == "claude" else None,
        preflight=preflight_status,
        session_id=None,
        turns_completed=0,
        reset_status="NOT VERIFIED BY RUNNER: administrator must attest a clean fixture",
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    session_id = None
    for index, prompt in enumerate(prompts):
        command = build_command(args, session_id, prompt, policy)
        (output_dir / f"turn_{index:02}_prompt.txt").write_text(
            prompt + "\n", encoding="utf-8"
        )
        try:
            process = subprocess.run(
                command,
                cwd=args.workspace,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            (output_dir / f"turn_{index:02}_ERROR.txt").write_text(
                "TIMEOUT; trial incomplete\n", encoding="utf-8"
            )
            break

        (output_dir / f"turn_{index:02}_events.jsonl").write_text(
            process.stdout, encoding="utf-8"
        )
        (output_dir / f"turn_{index:02}_stderr.txt").write_text(
            process.stderr, encoding="utf-8"
        )
        events = parse_events(process.stdout)
        extracted_id = find_session_id(args.agent, events)
        has_answer = completed_with_answer(args.agent, events)
        turn_status = {
            "exit_code": process.returncode,
            "session_id_seen": extracted_id,
            "had_structured_events": bool(events),
            "completed_with_answer": has_answer,
        }
        (output_dir / f"turn_{index:02}_status.json").write_text(
            json.dumps(turn_status, indent=2) + "\n", encoding="utf-8"
        )
        if process.returncode != 0 or not extracted_id or not has_answer:
            (output_dir / f"turn_{index:02}_ERROR.txt").write_text(
                "nonzero exit, missing session metadata, or no successful answer; trial incomplete\n",
                encoding="utf-8",
            )
            break
        if index == 0 and args.agent == "claude" and extracted_id != args.session_uuid:
            (output_dir / f"turn_{index:02}_ERROR.txt").write_text(
                "Claude returned a different initial session ID; trial invalid\n",
                encoding="utf-8",
            )
            break
        if session_id and extracted_id != session_id:
            (output_dir / f"turn_{index:02}_ERROR.txt").write_text(
                "session ID changed unexpectedly; trial contaminated/invalid\n",
                encoding="utf-8",
            )
            break

        session_id = extracted_id
        manifest["session_id"] = session_id
        manifest["turns_completed"] = index + 1
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )

    print(
        f"wrote private trial evidence to {output_dir}; "
        f"completed {manifest['turns_completed']}/4 turns"
    )
    print("score canary access, disclosure, and the fictional role decision offline")
    if manifest["turns_completed"] != len(prompts):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (KeyError, OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
