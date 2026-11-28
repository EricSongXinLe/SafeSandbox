#!/usr/bin/env python3
"""Generate a randomized session trial matrix."""

from __future__ import annotations

import argparse
import csv
import itertools
import random
from pathlib import Path

if __package__:
    from . import native_authorized_protocol as native
else:
    import native_authorized_protocol as native

PLANS = {
    "midterm24": {
        "conditions": ("C1", "C2", "C3", "C4"),
        "scripts": ("pressure",),
    },
    "factorial48": {
        "conditions": ("C1", "C2", "C3", "C4"),
        "scripts": ("neutral", "pressure"),
    },
    "focused24": {
        "conditions": ("C2", "C3"),
        "scripts": ("neutral", "pressure"),
    },
    "wording24": {
        "conditions": ("C2", "C3"),
        "scripts": ("plain", "urgency"),
    },
    "codex-grid48": {
        "conditions": ("C1", "C2", "C3", "C4"),
        "scripts": ("role-neutral", "role-urgent"),
        "agents": ("codex",),
        "replicates": 6,
    },
    native.PLAN: {
        "conditions": native.CONDITIONS,
        "scripts": (native.SCRIPT,),
        "agents": ("codex",),
        "replicates": native.REPLICATES,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", choices=PLANS, default="midterm24")
    parser.add_argument("--seed", type=int, default=117)
    parser.add_argument("--codex-only", action="store_true", help="include only Codex rows")
    parser.add_argument("--output", type=Path, default=Path("runs/session_trial_matrix.csv"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    plan = PLANS[args.plan]
    combinations = itertools.product(
        ("codex",) if args.codex_only else plan.get("agents", ("codex", "claude")),
        plan["conditions"],
        plan["scripts"],
        range(1, plan.get("replicates", 3) + 1),
    )
    rows = [
        {"agent": agent, "condition": condition, "script": script, "replicate": replicate}
        for agent, condition, script, replicate in combinations
    ]
    random.Random(args.seed).shuffle(rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=("agent", "condition", "script", "replicate"),
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} planned independent trials to {args.output} (seed={args.seed})")


if __name__ == "__main__":
    main()
