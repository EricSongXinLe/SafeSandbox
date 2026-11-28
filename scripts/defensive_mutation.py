"""Exercise policy decisions with an in-memory truth table and a Boolean mutant."""

import json

if __package__:
    from .defensive_protocol import RESOURCE, policy_allows
else:
    from defensive_protocol import RESOURCE, policy_allows


def compare() -> dict:
    cases = (
        (True, True, True),
        (True, False, True),
        (False, True, False),
        (False, False, False),
    )
    rows = []
    for granted, os_allowed, expected in cases:
        grants = frozenset({RESOURCE}) if granted else frozenset()
        corrected = policy_allows(RESOURCE, grants)
        # The toy mutation confuses the synthetic OS-access flag with a grant.
        faulty = os_allowed
        rows.append({
            "grant": granted, "synthetic_os_allowed": os_allowed, "expected_policy_allow": expected,
            "corrected_policy_allow": corrected, "faulty_reference_policy_allow": faulty,
            "corrected_error": corrected != expected, "faulty_reference_error": faulty != expected,
        })
    return {
        "protocol": "ece117-defensive-mutation-v1",
        "cases": len(rows),
        "corrected_incorrect": sum(row["corrected_error"] for row in rows),
        "faulty_reference_incorrect": sum(row["faulty_reference_error"] for row in rows),
        "rows": rows,
    }


def main() -> None:
    result = compare()
    print(json.dumps(result, indent=2))
    if result["corrected_incorrect"] != 0 or result["faulty_reference_incorrect"] != 2:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
