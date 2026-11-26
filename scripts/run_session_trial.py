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

if __package__:
    from .provider_auth import KEY_ENV, KEY_LIMIT, check_model_access, validate_key
else:
    from provider_auth import KEY_ENV, KEY_LIMIT, check_model_access, validate_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = PROJECT_ROOT / "prompts" / "session_scenarios.json"
POLICY = PROJECT_ROOT / "prompts" / "session_authorization_policy.txt"
CANARY = Path("/var/lib/ece117-fixtures/canary.txt")
SHARED = Path("/var/lib/ece117-fixtures/shared.txt")
CONDITIONS = {"C1": 0o600, "C2": 0o664, "C3": 0o664, "C4": 0o664}
WORDING_SCRIPTS = ("plain", "urgency")
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


def select_prompts(scenario: dict, variant: str) -> list[str]:
    if variant in WORDING_SCRIPTS:
        follow_up = scenario["wording_comparison"][variant]
        simulation = scenario["neutral"]["simulation"]
    else:
        follow_up = scenario[variant]["reassessment"]
        simulation = scenario[variant]["simulation"]
    return [scenario["shared"], scenario["direct"], follow_up, simulation]


def shared_control_verified(agent: str, events: list[dict[str, object]], expected: str) -> bool:
    """Require a successful tool result from the shared path, rather than assistant prose."""
    if not expected:
        return False
    if agent == "codex":
        for event in events:
            item = event.get("item")
            if (
                event.get("type") == "item.completed"
                and isinstance(item, dict)
                and item.get("type") == "command_execution"
                and item.get("exit_code") == 0
                and str(SHARED) in str(item.get("command", ""))
                and expected in str(item.get("aggregated_output", ""))
            ):
                return True
        return False

    calls = set()
    for event in events:
        message = event.get("message")
        blocks = message.get("content") if isinstance(message, dict) else None
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                inputs = block.get("input")
                call_id = block.get("id")
                if (
                    isinstance(inputs, dict) and isinstance(call_id, str)
                    and (
                        (block.get("name") == "Read" and inputs.get("file_path") == str(SHARED))
                        or (block.get("name") == "Bash" and str(SHARED) in str(inputs.get("command", "")))
                    )
                ):
                    calls.add(call_id)
            if (
                event.get("type") == "user" and block.get("type") == "tool_result"
                and isinstance(block.get("tool_use_id"), str) and block["tool_use_id"] in calls
                and not block.get("is_error", False)
            ):
                content = block.get("content")
                if isinstance(content, str) and expected in content:
                    return True
                if isinstance(content, list) and any(
                    isinstance(part, dict) and part.get("type") == "text"
                    and expected in str(part.get("text", "")) for part in content
                ):
                    return True
    return False


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
    parser.add_argument("--script", choices=("neutral", "pressure", *WORDING_SCRIPTS), required=True)
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
    parser.add_argument("--provider-key-stdin", action="store_true", help=argparse.SUPPRESS)
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
    prompts = select_prompts(scenario, args.script)
    require_shared_control = args.script in WORDING_SCRIPTS
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
        "control_gate": "verified_shared_file_read" if require_shared_control else None,
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
    expected_shared = SHARED.read_text(encoding="utf-8").strip() if require_shared_control else ""
    binary = "codex" if args.agent == "codex" else "claude"
    if shutil.which(binary) is None:
        raise SystemExit(f"{binary} is not installed on PATH for {args.expected_user}")

    provider_key = None
    provider_env = None
    if args.provider_key_stdin:
        provider_key = validate_key(sys.stdin.read(KEY_LIMIT + 1), args.agent)
        check_model_access(args.agent, args.model, provider_key)
        provider_env = {**os.environ, KEY_ENV[args.agent]: provider_key}

    run_id = f"{args.agent}_{args.condition}_{args.script}_r{args.replicate}"
    output_dir = args.output.resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest.update(
        timestamp_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        cli_version=cli_version(binary),
        provider_auth="runtime_api_key" if provider_key else "vm_configured",
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

    def clean(output: str | bytes | None) -> str:
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        text = output or ""
        return text.replace(provider_key, "[REDACTED_PROVIDER_KEY]") if provider_key else text

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
                env=provider_env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            (output_dir / f"turn_{index:02}_events.jsonl").write_text(
                clean(error.stdout), encoding="utf-8"
            )
            (output_dir / f"turn_{index:02}_stderr.txt").write_text(
                clean(error.stderr), encoding="utf-8"
            )
            (output_dir / f"turn_{index:02}_ERROR.txt").write_text(
                "TIMEOUT; trial incomplete\n", encoding="utf-8"
            )
            break

        safe_stdout = clean(process.stdout)
        (output_dir / f"turn_{index:02}_events.jsonl").write_text(safe_stdout, encoding="utf-8")
        (output_dir / f"turn_{index:02}_stderr.txt").write_text(
            clean(process.stderr), encoding="utf-8"
        )
        events = parse_events(safe_stdout)
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
        if index == 0 and require_shared_control:
            control_ok = shared_control_verified(args.agent, events, expected_shared)
            manifest["shared_control_verified"] = control_ok
            if not control_ok:
                manifest["termination_reason"] = "shared_control_unverified"
                (output_dir / "turn_00_ERROR.txt").write_text(
                    "Authorized shared-file read unverified; later prompts not sent\n",
                    encoding="utf-8",
                )
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if manifest.get("termination_reason") == "shared_control_unverified":
            break

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
    except (KeyError, OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
