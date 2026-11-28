"""Plan and collect the tool-free Suite D campaign."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from behavioral_protocol import (
    CATALOG, PLAN, SEED, canonical, checksum, decode_decision, make_plan, matrix_bytes,
    payload, response_record,
)
from provider_auth import prompt_provider_keys, validate_key

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
MAX_RESPONSE_BYTES = 1024 * 1024
RETRYABLE = {"started", "transport_error", "http_error"}
TERMINAL = {"evaluated", "provider_incomplete", "provider_refusal", "invalid_decision", "invalid_response", "unexpected_output"}


def atomic_write(path: Path, data: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temporary.write(data)
        temporary_path = Path(temporary.name)
    try:
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_envelope(path: Path, data: dict) -> None:
    encoded = canonical(data)
    atomic_write(path, canonical({"data": data, "sha256": checksum(encoded)}) + b"\n")


def read_envelope(path: Path) -> dict:
    envelope = json.loads(path.read_bytes())
    if not isinstance(envelope, dict) or set(envelope) != {"data", "sha256"}:
        raise ValueError(f"invalid evidence envelope: {path}")
    data = envelope["data"]
    if not isinstance(data, dict) or checksum(canonical(data)) != envelope["sha256"]:
        raise ValueError(f"evidence checksum mismatch: {path}")
    return data


def create_campaign(directory: Path, model: str, seed: int) -> dict:
    if not MODEL_ID.fullmatch(model):
        raise ValueError("specify a valid OpenAI Responses API model ID")
    plan = make_plan(json.loads(CATALOG.read_bytes()), seed, model)
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    atomic_write(directory / "matrix.csv", matrix_bytes(plan))
    write_envelope(directory / "plan.json", plan)
    return plan


def load_campaign(directory: Path) -> tuple[dict, str]:
    plan = read_envelope(directory / "plan.json")
    model, seed = plan.get("model"), plan.get("seed")
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model) or type(seed) is not int:
        raise ValueError("invalid saved model or seed")
    if plan != make_plan(plan.get("scenarios"), seed, model):
        raise ValueError("saved plan does not match the frozen Suite D protocol")
    if (directory / "matrix.csv").read_bytes() != matrix_bytes(plan):
        raise ValueError("matrix.csv does not match the frozen plan")
    return plan, checksum(canonical(plan))


def read_attempts(directory: Path, row: dict, plan_hash: str, request_hash: str) -> list[dict]:
    attempt_dir = directory / "attempts" / row["trial_id"]
    attempts = []
    complete = False
    for index, path in enumerate(sorted(attempt_dir.glob("*.json")), start=1):
        data = read_envelope(path)
        if (
            path.name != f"{index:06}.json" or data.get("sequence") != index
            or data.get("trial_id") != row["trial_id"] or data.get("plan_sha256") != plan_hash
            or data.get("request_sha256") != request_hash or complete
        ):
            raise ValueError(f"attempt metadata mismatch: {path}")
        status = data.get("status")
        if status in TERMINAL or status in {"model_mismatch", "duplicate_response"}:
            derived, decision = decode_decision(data.get("response"))
            if status in {"model_mismatch", "duplicate_response"}:
                consistent = derived == "evaluated" and data.get("decision") is None
            else:
                consistent = derived == status and decision == data.get("decision")
            if not consistent:
                raise ValueError(f"attempt decision mismatch: {path}")
            complete = status in TERMINAL
        elif status not in RETRYABLE or "response" in data or "decision" in data:
            raise ValueError(f"invalid attempt status: {path}")
        attempts.append(data)
    return attempts


def inspect_campaign(directory: Path, plan: dict, plan_hash: str) -> tuple[list[dict], str | None]:
    records = []
    for row in plan["rows"]:
        request_hash = checksum(canonical(payload(plan, row)))
        record = {"row": row, "request_sha256": request_hash, "attempts": [], "verification_error": None}
        try:
            record["attempts"] = read_attempts(directory, row, plan_hash, request_hash)
        except (OSError, TypeError, ValueError) as error:
            record["verification_error"] = str(error)
        records.append(record)

    evaluated_models = {
        attempt["response"]["model"]
        for record in records for attempt in record["attempts"] if attempt["status"] == "evaluated"
    }
    if len(evaluated_models) > 1:
        raise ValueError("campaign contains mixed returned model IDs")
    response_ids = [
        attempt["response"]["id"]
        for record in records for attempt in record["attempts"] if attempt["status"] == "evaluated"
    ]
    if len(response_ids) != len(set(response_ids)):
        raise ValueError("campaign contains duplicate evaluated response IDs")
    return records, next(iter(evaluated_models), None)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_decision(request: dict, key: str, timeout: int) -> tuple[str, dict]:
    connection = http.client.HTTPSConnection("api.openai.com", timeout=timeout)
    try:
        connection.request("POST", "/v1/responses", body=canonical(request), headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json",
        })
        response = connection.getresponse()
        if response.status != 200:
            return "http_error", {"http_status": response.status}
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, http.client.HTTPException):
        return "transport_error", {}
    finally:
        connection.close()
    try:
        decoded = json.loads(raw) if len(raw) <= MAX_RESPONSE_BYTES else None
    except (ValueError, UnicodeError):
        decoded = None
    normalized = response_record(decoded, lambda value: value.replace(key, "[redacted]"))
    status, decision = decode_decision(normalized)
    return status, {"response": normalized, "decision": decision}


@contextmanager
def collection_lock(directory: Path):
    with (directory / ".collect.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Suite D collection is already active in this campaign") from None
        yield


def collect(directory: Path, execute: bool, timeout: int) -> int:
    if not execute:
        plan, plan_hash = load_campaign(directory)
        records, model = inspect_campaign(directory, plan, plan_hash)
        verified = sum(bool(r["attempts"]) and r["attempts"][-1]["status"] in TERMINAL for r in records)
        invalid = sum(bool(r["verification_error"]) for r in records)
        print(f"{PLAN}: {len(records)} planned; {verified} recorded outcomes; {invalid} unverified")
        print(f"Requested model {plan['model']}; returned model {model or 'pending'}; plan SHA-256 {plan_hash}")
        return int(bool(invalid))
    with collection_lock(directory):
        plan, plan_hash = load_campaign(directory)
        records, model = inspect_campaign(directory, plan, plan_hash)
        if any(r["verification_error"] for r in records):
            raise ValueError("unverified attempt evidence; run the Suite D reporter and inspect the original evidence")
        pending = [r for r in records if not r["attempts"] or r["attempts"][-1]["status"] not in TERMINAL]
        if not pending:
            print("All 48 rows have recorded outcomes. Run the reporter to check evaluated coverage.")
            return 0
        key = os.environ.get("OPENAI_API_KEY")
        key = validate_key(key, "codex") if key is not None else prompt_provider_keys(("codex",))["codex"]
        response_ids = {
            attempt["response"]["id"]
            for record in records for attempt in record["attempts"] if attempt["status"] == "evaluated"
        }
        for record in pending:
            row_id = record["row"]["trial_id"]
            sequence = len(record["attempts"]) + 1
            target = directory / "attempts" / row_id / f"{sequence:06}.json"
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            attempt = {
                "trial_id": row_id, "sequence": sequence, "plan_sha256": plan_hash,
                "request_sha256": record["request_sha256"], "status": "started", "started_at_utc": utc_now(),
            }
            write_envelope(target, attempt)
            status, outcome = request_decision(payload(plan, record["row"]), key, timeout)
            if status == "evaluated":
                returned, response_id = (outcome["response"][field] for field in ("model", "id"))
                if model is not None and returned != model:
                    status, outcome["decision"] = "model_mismatch", None
                elif response_id in response_ids:
                    status, outcome["decision"] = "duplicate_response", None
                else:
                    model = returned
                    response_ids.add(response_id)
            attempt.update(outcome, status=status, finished_at_utc=utc_now())
            write_envelope(target, attempt)
            print(f"{row_id} {status}", flush=True)
            if status not in TERMINAL:
                detail = f" (HTTP {outcome['http_status']})" if status == "http_error" else ""
                print(f"Collection stopped at {row_id}{detail}. Evidence saved in {target}.", file=sys.stderr)
                return 1
        print("Collection finished. Run the reporter to check evaluated coverage.")
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_cmd = commands.add_parser("plan", help="freeze the matrix and request settings locally")
    plan_cmd.add_argument("--output", required=True, type=Path)
    plan_cmd.add_argument("--model", required=True)
    plan_cmd.add_argument("--seed", type=int, default=SEED)
    run_cmd = commands.add_parser("run", help="preview or resume the frozen campaign")
    run_cmd.add_argument("--campaign", required=True, type=Path)
    run_cmd.add_argument("--execute", action="store_true", help="send the model requests")
    run_cmd.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    try:
        if args.command == "plan":
            plan = create_campaign(args.output, args.model, args.seed)
            print(f"Froze {len(plan['rows'])} Suite D rows in {args.output}")
            return 0
        if args.timeout < 1:
            raise ValueError("timeout must be positive")
        return collect(args.campaign, args.execute, args.timeout)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Collection interrupted. Resume with the same campaign directory.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
