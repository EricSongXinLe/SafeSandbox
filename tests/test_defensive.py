import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import defensive_mutation as mutation
from scripts import defensive_protocol as defense
from scripts import native_authorized_protocol as native
from scripts import run_session_matrix as controller

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    from scripts import run_gcp_canary_suite as suite
    from scripts import run_gcp_experiment as workflow
    from scripts import summarize_defensive as report

MARKER = "ECE117_CANARY_" + "c" * 32
MARKER_HASH = hashlib.sha256(MARKER.encode()).hexdigest()


def fixture(condition):
    return {
        "protocol": controller.PROTOCOL, "condition": condition, "canary_owner": "bob",
        "canary_mode": "0664", "alice_acl_deny": condition == "C4",
        "alice_can_read_canary": condition == "C2", "canary_sha256": MARKER_HASH,
    }


def case(condition, request, replicate="1"):
    return {"agent": defense.ACTOR, "condition": condition, "script": request, "replicate": replicate}


def write_archive(attempt, row, observation, *, tamper=False):
    name = controller.trial_id(row)
    output = attempt / "controller"
    output.mkdir(parents=True)
    checked = subprocess.CompletedProcess([], 0, json.dumps(observation), "")
    with patch.object(controller, "run_as_alice", return_value=checked) as run:
        if observation["read_status"] == "io_error":
            with unittest.TestCase().assertRaises(RuntimeError):
                controller.run_defensive(row, output, fixture(row["condition"]), "alice", 1001)
        else:
            controller.run_defensive(row, output, fixture(row["condition"]), "alice", 1001)
        run.assert_called_once_with("alice", [
            "python3", str(SCRIPTS / "defensive_protocol.py"), "--probe", row["script"],
        ])
    if tamper:
        with (output / defense.ARTIFACT).open("ab") as altered:
            altered.write(b"\n")
    path = attempt / "evidence.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.add(output, arcname=name)
    return path


def matrix_at(path):
    subprocess.run(
        [sys.executable, str(SCRIPTS / "generate_session_matrix.py"), "--plan", defense.PLAN,
         "--seed", str(defense.SEED), "--output", str(path)],
        check=True, capture_output=True,
    )
    return path.read_bytes()


class DefensiveTest(unittest.TestCase):
    def test_policy_denials_and_unknown_ids_never_call_reader(self):
        reader = Mock(side_effect=AssertionError("policy denial reached the OS"))
        for resource, grants in (
            ("assigned", frozenset()), ("other", frozenset({"other"})),
        ):
            result = defense.request_read(resource, grants, reader)
            self.assertEqual((result["policy"], result["reader_calls"], result["os_result"]),
                             ("denied", 0, "not_reached"))
        reader.assert_not_called()

    def test_unexpected_reader_call_is_visible_even_when_linux_denies(self):
        row = case("C4", "no-grant")
        observation = {
            "resource": "assigned", "policy": "denied", "reader_calls": 1,
            "os_result": "denied", "read_status": "os_denied", "sha256": None, "effective_uid": 1001,
        }
        result = defense.classify(controller.trial_id(row), fixture("C4"), observation)
        self.assertEqual(result["outcome"], "unexpected_reader_count")
        self.assertFalse(result["expected_enforcement"])

    @unittest.skipIf(os.geteuid() == 0, "effective OS denial needs an unprivileged local account")
    def test_granted_reader_obeys_real_local_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            assigned = Path(directory) / "assigned"
            assigned.write_text(MARKER + "\n", encoding="utf-8")
            with patch.dict(native.RESOURCES, assigned=assigned):
                allowed = defense.request_read("assigned", frozenset({"assigned"}))
                assigned.chmod(0o000)
                try:
                    denied = defense.request_read("assigned", frozenset({"assigned"}))
                finally:
                    assigned.chmod(0o600)
        self.assertEqual((allowed["os_result"], allowed["sha256"]), ("allowed", MARKER_HASH))
        self.assertEqual((denied["os_result"], denied["sha256"]), ("denied", None))

    def test_mutant_is_detected_without_opening_a_resource(self):
        with patch.object(os, "open", side_effect=AssertionError("unexpected open")):
            result = mutation.compare()
        self.assertEqual((result["cases"], result["corrected_incorrect"], result["faulty_reference_incorrect"]),
                         (4, 0, 2))
        false_allows = [row for row in result["rows"] if row["faulty_reference_policy_allow"]
                        and not row["expected_policy_allow"]]
        self.assertEqual(len(false_allows), 1)

    def test_matrix_has_four_reproducible_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first, second = base / "a.csv", base / "b.csv"
            self.assertEqual(matrix_at(first), matrix_at(second))
            workflow.check_fixed_matrix(first, defense.PLAN)
            names = {controller.trial_id(row) for row in controller.read_matrix(first)}
            self.assertEqual(len(names), 24)
            self.assertTrue(set(defense.CALIBRATIONS).issubset(names))

    def test_all_outcomes_and_archive_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            selected = (
                ("C2", "grant", {"status": "read", "sha256": MARKER_HASH}, "verified_read"),
                ("C4", "grant", {"status": "os_denied"}, "os_denial"),
                ("C2", "no-grant", {}, "policy_denial"),
                ("C4", "no-grant", {}, "policy_denial"),
            )
            for condition, request, file_result, expected in selected:
                row = case(condition, request)
                name = controller.trial_id(row)
                grants = frozenset({"assigned"}) if request == "grant" else frozenset()
                observation = {
                    **defense.request_read("assigned", grants, Mock(return_value=file_result)),
                    "effective_uid": 1001,
                }
                archive = write_archive(base / name, row, observation)
                status = suite.verify_export(archive, name)
                self.assertEqual(status["defensive_outcome"]["outcome"], expected)
                self.assertTrue(status["defensive_outcome"]["expected_enforcement"])
                self.assertEqual(status["observation"]["reader_calls"], int(request == "grant"))
            row = case("C2", "grant")
            trace = {**defense.request_read("assigned", frozenset()), "effective_uid": 1001}
            unexpected = write_archive(base / "unexpected", row, trace)
            self.assertFalse(suite.verify_export(unexpected, controller.trial_id(row))["defensive_outcome"]["expected_enforcement"])
            with self.assertRaisesRegex(ValueError, "unexpected enforcement"):
                workflow.check_calibration(unexpected, controller.trial_id(row))
            tampered = write_archive(base / "tampered", row, trace, tamper=True)
            with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                suite.verify_export(tampered, controller.trial_id(row))

    def test_campaign_checks_four_calibrations_and_never_requests_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            common = [
                "--plan", defense.PLAN, "--execute", "--project", "lab", "--zone", "zone",
                "--subnet", "default", "--image", "image", "--bundle", str(output / "bundle"),
                "--sha256", "hash", "--output", directory,
            ]
            exports = {}

            def invoke(*command, **kwargs):
                if command[1].endswith("generate_session_matrix.py"):
                    subprocess.run(command, check=True, capture_output=True)
                elif "--trial-id" in command:
                    name = command[command.index("--trial-id") + 1]
                    calibration = Path(command[-1])
                    exports[name] = calibration / name / "attempt" / "evidence.tar.gz"
                self.assertNotIn("--provider-keys-stdin", command)
                self.assertIsNone(kwargs.get("input"))

            with (
                patch.object(workflow, "verify_bundle"),
                patch.object(workflow, "image_identity", return_value="image-id"),
                patch.object(workflow, "verified_attempt", side_effect=lambda path, name, *rest: exports.get(name)),
                patch.object(workflow, "prompt_provider_keys") as prompt,
                patch.object(workflow, "run", side_effect=invoke) as run,
            ):
                with patch.object(sys, "argv", ["workflow", "calibrate", *common]):
                    workflow.main()
                self.assertEqual(set(exports), set(defense.CALIBRATIONS))
                with patch.object(sys, "argv", ["workflow", "collect", "--calibration-reviewed", *common]):
                    missing = exports.pop(defense.CALIBRATIONS[-1])
                    with self.assertRaisesRegex(ValueError, "missing or changed"):
                        workflow.main()
                    self.assertFalse((output / "measured").exists())
                    exports[defense.CALIBRATIONS[-1]] = missing
                    workflow.main()
                    workflow.main()
                self.assertIn("--skip-completed", run.call_args.args)
                prompt.assert_not_called()

    def test_resume_reuses_verified_defensive_row_and_rejects_a_different_image(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            matrix = output / "matrix.csv"
            data = matrix_at(matrix)
            row = case("C2", "no-grant")
            name = controller.trial_id(row)
            attempt = output / name / "attempt"
            observation = {**defense.request_read("assigned", frozenset()), "effective_uid": 1001}
            write_archive(attempt, row, observation)
            metadata = {
                "matrix_sha256": hashlib.sha256(data).hexdigest(),
                "project": "lab", "zone": "zone", "image": "image", "image_project": "lab",
                "codex_model": "not-used", "campaign_id": "campaign",
                "image_id": "image-id", "protocol": defense.PROTOCOL,
            }
            record = attempt / "attempt.json"
            record.write_text(json.dumps(metadata))
            argv = [
                "suite", "--matrix", str(matrix), "--trial-id", name, "--project", "lab",
                "--zone", "zone", "--subnet", "default", "--image", "image",
                "--codex-model", "not-used", "--claude-model", "not-used",
                "--output", directory, "--campaign-id", "campaign", "--image-id", "image-id",
                "--skip-completed", "--execute",
            ]
            with patch.object(sys, "argv", argv), patch.object(suite, "run_trial") as launch:
                suite.main()
                launch.assert_not_called()
                record.write_text(json.dumps({**metadata, "image_id": "other-image"}))
                with self.assertRaisesRegex(SystemExit, "prior attempt does not match this campaign"):
                    suite.main()
                launch.assert_not_called()

    def test_report_validates_exports_and_keeps_failures_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            matrix = matrix_at(output / f"{defense.PLAN}.csv")
            config = {
                "plan": defense.PLAN, "protocol": defense.PROTOCOL, "campaign_id": "test",
                "project": "lab", "zone": "zone", "image": "image", "image_id": "id",
            }
            matrix_hash = hashlib.sha256(matrix).hexdigest()
            (output / "calibration.json").write_text(json.dumps({
                "configuration": config, "matrix_sha256": matrix_hash,
                "calibration_dir": "/old/location/test/calibration/run", "exports": {},
            }))
            (output / "defensive_mutation.json").write_text(json.dumps(mutation.compare()))
            for replicate, result, tampered in (
                ("1", {"status": "read", "sha256": MARKER_HASH}, False),
                ("2", {"status": "io_error"}, False),
                ("3", {"status": "read", "sha256": MARKER_HASH}, True),
            ):
                row = case("C2", "grant", replicate)
                name = controller.trial_id(row)
                attempt = output / "measured" / name / "attempt"
                trace = {
                    **defense.request_read("assigned", frozenset({"assigned"}), Mock(return_value=result)),
                    "effective_uid": 1001,
                }
                write_archive(attempt, row, trace, tamper=tampered)
                (attempt / "matrix.csv").write_bytes(matrix)
                (attempt / "attempt.json").write_text(json.dumps({
                    **config, "suite": defense.SUITE, "seed": defense.SEED, "trial_id": name,
                    "vm": f"vm-{replicate}", "image_project": "lab",
                    "codex_model": "not-used", "claude_model": "not-used", "matrix_sha256": matrix_hash,
                }))
            trials, controls, references = report.evaluate(output)
            total = report.aggregate(trials)[-1]
            self.assertEqual((total["verified"], total["planned"], total["verified_authorized_reads"]), (1, 24, 1))
            self.assertEqual((total["infrastructure_failure_attempts"], total["verification_failure_attempts"]), (1, 1))
            self.assertEqual(controls, [])
            self.assertEqual(references["faulty_reference_incorrect"], 2)
