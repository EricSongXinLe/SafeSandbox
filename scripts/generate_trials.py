#!/usr/bin/env python3
"""Generate a deterministic, randomized trial manifest.

This script creates prompts and metadata only. It does not call an agent or
touch the synthetic credential fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, default=Path("prompts/pressure_conditions.json"))
    parser.add_argument("--output", type=Path, default=Path("runs/trial_manifest.jsonl"))
    parser.add_argument("--seed", type=int, default=11714)
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--harnesses", nargs="+", default=["codex", "claude"])
    parser.add_argument("--modes", nargs="+", type=int, default=[0o600, 0o644])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repetitions < 1:
        raise SystemExit("--repetitions must be positive")

    data = json.loads(args.cases.read_text())
    target_path = data["target_path"]
    trials: list[dict[str, object]] = []

    for harness in args.harnesses:
        for mode in args.modes:
            if mode not in (0o600, 0o644):
                raise SystemExit("This primary study only permits modes 0600 and 0644")
            for condition in data["conditions"]:
                variants = condition["variants"]
                for repetition in range(args.repetitions):
                    variant_index = repetition % len(variants)
                    prompt = variants[variant_index].format(target_path=target_path)
                    identity = (
                        f"{args.seed}|{harness}|{mode:04o}|{condition['id']}|"
                        f"{repetition}|{variant_index}"
                    )
                    trial_id = hashlib.sha256(identity.encode()).hexdigest()[:16]
                    trials.append(
                        {
                            "trial_id": trial_id,
                            "harness": harness,
                            "file_mode": f"{mode:04o}",
                            "condition_id": condition["id"],
                            "condition_name": condition["name"],
                            "repetition": repetition,
                            "variant_index": variant_index,
                            "target_path": target_path,
                            "prompt": prompt,
                        }
                    )

    random.Random(args.seed).shuffle(trials)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w") as output:
        for order, trial in enumerate(trials):
            trial["randomized_order"] = order
            output.write(json.dumps(trial, sort_keys=True) + "\n")

    print(f"wrote {len(trials)} trials to {args.output} (seed={args.seed})")


if __name__ == "__main__":
    main()

