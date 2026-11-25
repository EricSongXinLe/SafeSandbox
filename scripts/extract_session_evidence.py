#!/usr/bin/env python3
"""Create a non-verdict audit aide from a saved multi-turn session trace.

Raw event files may contain the study marker. By default this script
records command hashes and tool names, not command text or tool inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def command_digest(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()


def extract(turn_file: Path, include_commands: bool) -> dict[str, object]:
    calls: list[dict[str, object]] = []
    assistant_messages = 0
    for line in turn_file.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") in ("item.started", "item.completed"):
            item = event.get("item", {})
            if not isinstance(item, dict):
                continue
            command = item.get("command")
            if item.get("type") == "command_execution" and isinstance(command, str):
                call: dict[str, object] = {
                    "kind": "command_execution",
                    "command_sha256": command_digest(command),
                    "exit_code": item.get("exit_code"),
                    "status": item.get("status"),
                }
                if include_commands:
                    call["command"] = command
                calls.append(call)
            elif item.get("type") == "agent_message":
                assistant_messages += 1
        elif event.get("type") == "assistant":
            message = event.get("message", {})
            if not isinstance(message, dict):
                continue
            content = message.get("content", [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    calls.append({"kind": "tool_use", "tool_name": block.get("name")})
                elif block.get("type") == "text":
                    assistant_messages += 1
    return {
        "turn": turn_file.stem,
        "commands_or_tools": calls,
        "assistant_message_count": assistant_messages,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trial_dir", type=Path)
    parser.add_argument(
        "--include-commands",
        action="store_true",
        help="include raw commands; output remains sensitive and must stay private",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.trial_dir.is_dir():
        raise SystemExit(f"trial directory not found: {args.trial_dir}")
    summary = [
        extract(path, args.include_commands)
        for path in sorted(args.trial_dir.glob("turn_*_events.jsonl"))
    ]
    destination = args.trial_dir / "audit_aide.json"
    destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(
        f"saved {destination}; this is not an automated score—"
        "review tool results, assistant text, and the fixture attestation"
    )


if __name__ == "__main__":
    main()
