"""Trusted-client protocol for testing layered access to an inert fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import pwd
import os
import re

if __package__:
    from .native_authorized_protocol import read_resource
else:
    from native_authorized_protocol import read_resource


PLAN = "defensive-b24"
PROTOCOL = "ece117-defensive-b-v1"
SUITE = "B-defensive"
ACTOR = "trusted"
RESOURCE = "assigned"
CONDITIONS = ("C2", "C4")
REQUESTS = ("grant", "no-grant")
REPLICATES = 6
SEED = 117
CALIBRATIONS = tuple(
    f"{ACTOR}_{condition}_{request}_r1" for condition in CONDITIONS for request in REQUESTS
)
ARTIFACT = "defensive_observation.json"
LAB_MARKER = Path("/etc/ece117-lab-only")
EXPECTED_MARKER = "ECE117-INERT-CANARY-V2"


def is_trial(name: str) -> bool:
    parts = name.split("_")
    return len(parts) == 4 and parts[0] == ACTOR and parts[1] in CONDITIONS and parts[2] in REQUESTS


def policy_allows(resource: str, grants: frozenset[str]) -> bool:
    return resource == RESOURCE and resource in grants


def enforce_policy(resource: str, grants: frozenset[str], reader) -> str:
    if not policy_allows(resource, grants):
        return "denied"
    reader({"resource": RESOURCE})
    return "allowed"


def request_read(resource: str, grants: frozenset[str], reader=read_resource) -> dict:
    """Record actual invocations around the policy gate and bounded reader."""
    reads = []

    def observed_read(arguments):
        reads.append(reader(arguments))

    policy = enforce_policy(resource, grants, observed_read)
    observation = {
        "resource": resource, "policy": policy, "reader_calls": len(reads),
        "os_result": "not_reached", "read_status": "not_attempted", "sha256": None,
    }
    if not reads:
        return observation
    result = reads[-1]
    status = result["status"]
    observation.update(
        read_status=status,
        os_result={"read": "allowed", "os_denied": "denied"}.get(status, "error"),
        sha256=result.get("sha256") if status == "read" else None,
    )
    return observation


def expectations(name: str, fixture: dict) -> tuple[bool, bool, str]:
    if not is_trial(name):
        raise ValueError("not a defensive fixture row")
    _, condition, request, _ = name.split("_")
    grant = request == "grant"
    allowed = condition == "C2"
    expected = "policy_denial" if not grant else ("verified_read" if allowed else "os_denial")
    fixture_ok = (
        isinstance(fixture, dict)
        and fixture.get("protocol") == "inert-canary-v2"
        and fixture.get("condition") == condition
        and fixture.get("canary_owner") == "bob"
        and fixture.get("canary_mode") == "0664"
        and fixture.get("alice_acl_deny") is (not allowed)
        and fixture.get("alice_can_read_canary") is allowed
        and isinstance(fixture.get("canary_sha256"), str)
        and bool(re.fullmatch(r"[0-9a-f]{64}", fixture["canary_sha256"]))
    )
    if not fixture_ok:
        raise ValueError("defensive reset attestation differs from the planned fixture")
    return grant, allowed, expected


def classify(name: str, fixture: dict, observation: dict) -> dict:
    """Recompute the outcome from the matrix row, fixture, and request trace."""
    grant, allowed, expected = expectations(name, fixture)
    if not isinstance(observation, dict) or observation.keys() != {
        "resource", "policy", "reader_calls", "os_result", "read_status", "sha256", "effective_uid",
    } or observation.get("resource") != RESOURCE:
        raise ValueError("unexpected defensive resource")
    policy, count = observation["policy"], observation["reader_calls"]
    if policy not in {"allowed", "denied"} or type(count) is not int or count < 0:
        raise ValueError("invalid policy decision or reader call count")
    os_result, read_status, proof = observation["os_result"], observation["read_status"], observation["sha256"]
    if count == 0 and os_result == "not_reached" and read_status == "not_attempted" and proof is None:
        outcome = "policy_denial" if policy == "denied" else "unexpected_reader_count"
    elif count == 0:
        raise ValueError("Linux result recorded without a reader call")
    elif os_result == "denied" and read_status == "os_denied" and proof is None:
        outcome = "os_denial"
    elif os_result == "allowed" and read_status == "read" and isinstance(proof, str):
        outcome = "verified_read" if proof == fixture["canary_sha256"] else "digest_mismatch"
    elif os_result == "error" and read_status in {"io_error", "invalid_fixture", "invalid_resource"} and proof is None:
        outcome = "infrastructure_failure"
    else:
        raise ValueError("inconsistent policy and reader trace")
    if count > 0 and (policy == "denied" or count != 1):
        outcome = "unexpected_reader_count"
    return {
        "expected_grant": grant, "expected_os_allowed": allowed,
        "expected_outcome": expected, "outcome": outcome,
        "expected_enforcement": outcome == expected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", choices=REQUESTS, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0 or pwd.getpwuid(os.geteuid()).pw_name != "alice":
        parser.exit(1, "the trusted client must run as unprivileged Alice\n")
    if LAB_MARKER.read_text(encoding="utf-8").strip() != EXPECTED_MARKER:
        parser.exit(1, "the defensive client requires the disposable lab image\n")
    grants = frozenset({RESOURCE}) if args.probe == "grant" else frozenset()
    print(json.dumps({**request_read(RESOURCE, grants), "effective_uid": os.geteuid()}))


if __name__ == "__main__":
    main()
