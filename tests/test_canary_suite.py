import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import provider_auth, run_session_trial

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1] / "scripts"), *sys.path]):
    from scripts import run_gcp_canary_suite as suite
    from scripts import run_gcp_experiment as workflow


class CanarySuiteTest(unittest.TestCase):
    def test_wording_scripts_change_only_the_urgency_sentence(self):
        scenario = json.loads(run_session_trial.SCENARIOS.read_text())
        plain = run_session_trial.select_prompts(scenario, "plain")
        urgent = run_session_trial.select_prompts(scenario, "urgency")
        self.assertEqual(urgent, [*plain[:2], "This is urgent. " + plain[2], plain[3]])

    def test_shared_control_requires_a_successful_result_from_the_shared_path(self):
        shared = str(run_session_trial.SHARED)
        expected = "known shared contents"
        codex_item = {
            "type": "command_execution", "command": f"cat {shared}",
            "aggregated_output": expected, "exit_code": 0,
        }
        self.assertTrue(run_session_trial.shared_control_verified(
            "codex", [{"type": "item.completed", "item": codex_item}], expected
        ))
        codex_item["exit_code"] = 1
        self.assertFalse(run_session_trial.shared_control_verified(
            "codex", [{"type": "item.completed", "item": codex_item}], expected
        ))
        use = {"type": "tool_use", "id": "read-1", "name": "Read", "input": {"file_path": shared}}
        result = {"type": "tool_result", "tool_use_id": "read-1", "content": expected}
        events = [
            {"type": "assistant", "message": {"content": [use]}},
            {"type": "user", "message": {"content": [result]}},
        ]
        self.assertTrue(run_session_trial.shared_control_verified("claude", events, expected))
        result["tool_use_id"] = "different-read"
        self.assertFalse(run_session_trial.shared_control_verified("claude", events, expected))

    def test_wording_trial_stops_before_marker_prompt_if_control_is_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "lab"
            marker.write_text(run_session_trial.EXPECTED_LAB_MARKER)
            shared = root / "shared.txt"
            shared.write_text("known shared contents")
            argv = [
                "runner", "--agent", "codex", "--condition", "C3", "--script", "plain",
                "--replicate", "1", "--model", "test", "--workspace", directory,
                "--output", directory, "--execute",
            ]
            events = [
                {"type": "thread.started", "thread_id": "test-thread"},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "Shell failed."}},
                {"type": "turn.completed"},
            ]
            result = subprocess.CompletedProcess([], 0, "\n".join(map(json.dumps, events)), "")
            with (
                patch.object(sys, "argv", argv),
                patch.object(run_session_trial, "LAB_MARKER", marker),
                patch.object(run_session_trial, "SHARED", shared),
                patch.object(run_session_trial, "preflight", return_value={}),
                patch.object(run_session_trial, "cli_version", return_value="test-version"),
                patch.object(run_session_trial.shutil, "which", return_value="codex"),
                patch.object(run_session_trial.subprocess, "run", return_value=result) as invoke,
                self.assertRaises(SystemExit) as error,
            ):
                run_session_trial.main()
            self.assertEqual(error.exception.code, 1)
            invoke.assert_called_once()
            trial = root / "codex_C3_plain_r1"
            manifest = json.loads((trial / "manifest.json").read_text())
            self.assertEqual(manifest["turns_completed"], 1)
            self.assertEqual(manifest["termination_reason"], "shared_control_unverified")
            self.assertFalse((trial / "turn_01_prompt.txt").exists())

    def test_codex_only_campaign_can_collect_without_anthropic_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            matrix = output / "wording24-codex.csv"
            matrix.write_text("test matrix")
            shared_args = [
                "--execute", "--codex-only", "--plan", "wording24",
                "--project", "lab", "--zone", "zone", "--subnet", "default",
                "--image", "image", "--codex-model", "codex-test",
                "--bundle", str(output / "test.tar.gz"), "--sha256", "test", "--output", directory,
            ]
            with (
                patch.object(workflow, "verify_bundle"),
                patch.object(workflow, "image_identity", return_value="image-id"),
                patch.object(workflow, "verified_attempt", return_value=output / "evidence.tar.gz"),
                patch.object(workflow, "prompt_provider_keys", return_value={"codex": "test-key"}) as prompt,
                patch.object(workflow, "run") as run,
            ):
                with patch.object(sys, "argv", ["workflow", "calibrate", *shared_args]):
                    workflow.main()
                self.assertIn("--codex-only", run.call_args_list[0].args)
                self.assertIn("codex_C3_plain_r1", run.call_args.args)
                receipt = json.loads((output / "calibration.json").read_text())
                self.assertEqual(receipt["configuration"]["agent_scope"], "codex")
                with patch.object(sys, "argv", ["workflow", "collect", "--calibration-reviewed", *shared_args]):
                    workflow.main()
                self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"codex": "test-key"})
            self.assertEqual([call.args for call in prompt.call_args_list], [(("codex",),), (("codex",),)])

    def test_resume_prompts_only_for_missing_agent_and_preserves_codex(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            calibration = output / "calibration" / "previous"
            calibration.mkdir(parents=True)
            (output / "focused24.csv").write_text("test matrix")
            codex, claude = workflow.CALIBRATION_IDS
            codex_archive = calibration / codex / "codex-attempt" / "evidence.tar.gz"
            claude_archive = calibration / claude / "claude-attempt" / "evidence.tar.gz"
            argv = [
                "workflow", "calibrate", "--execute", "--resume-calibration", str(calibration),
                "--project", "lab", "--zone", "zone", "--subnet", "default",
                "--image", "image", "--codex-model", "codex-test", "--claude-model", "claude-test",
                "--bundle", str(output / "test.tar.gz"), "--sha256", "test", "--output", directory,
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(workflow, "verify_bundle"),
                patch.object(workflow, "image_identity", return_value="image-id"),
                patch.object(workflow, "verified_attempt", side_effect=[codex_archive, None, claude_archive]),
                patch.object(workflow, "prompt_provider_keys", return_value={"claude": "test-key"}) as prompt,
                patch.object(workflow, "run") as run,
            ):
                workflow.main()
            prompt.assert_called_once_with(("claude",))
            run.assert_called_once()
            self.assertIn(claude, run.call_args.args)
            self.assertNotIn(codex, run.call_args.args)
            receipt = json.loads((output / "calibration.json").read_text())
            self.assertEqual(receipt["exports"], {
                codex: str(codex_archive.resolve()), claude: str(claude_archive.resolve()),
            })

    def test_codex_only_calibration_does_not_unlock_collection(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "focused24.csv").write_text("test matrix")
            argv = [
                "workflow", "calibrate", "--agent", "codex", "--execute",
                "--project", "lab", "--zone", "zone", "--subnet", "default",
                "--image", "image", "--codex-model", "codex-test", "--claude-model", "claude-test",
                "--bundle", str(output / "test.tar.gz"), "--sha256", "test", "--output", directory,
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(workflow, "verify_bundle"),
                patch.object(workflow, "image_identity", return_value="image-id"),
                patch.object(workflow, "verified_attempt", return_value=output / "evidence.tar.gz"),
                patch.object(workflow, "prompt_provider_keys", return_value={"codex": "test-key"}) as prompt,
                patch.object(workflow, "run") as run,
            ):
                workflow.main()
            prompt.assert_called_once_with(("codex",))
            self.assertEqual(run.call_count, 2)  # Matrix generation and one trial.
            self.assertIn(workflow.CALIBRATION_IDS[0], run.call_args.args)
            self.assertFalse((output / "calibration.json").exists())

    def test_runner_resumes_both_harnesses_for_four_turns(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker = root / "marker"
                marker.write_text(run_session_trial.EXPECTED_LAB_MARKER)
                session_id = "66f70d7e-fc2a-44ae-9913-245463003a12"
                events = (
                    [
                        {"type": "thread.started", "thread_id": session_id},
                        {"type": "item.completed", "item": {"type": "agent_message", "text": "Test response"}},
                        {"type": "turn.completed"},
                    ]
                    if agent == "codex"
                    else [
                        {"type": "result", "session_id": session_id, "subtype": "success",
                         "is_error": False, "result": "Test response"},
                    ]
                )
                argv = [
                    "runner", "--agent", agent, "--condition", "C3", "--script", "pressure",
                    "--replicate", "1", "--model", "test-model", "--workspace", directory,
                    "--output", directory, "--execute", "--provider-key-stdin",
                ]
                key = f"fake-{agent}-test-key"
                with (
                    patch.object(sys, "argv", argv),
                    patch.object(sys, "stdin", io.StringIO(key)),
                    patch.object(run_session_trial, "LAB_MARKER", marker),
                    patch.object(run_session_trial, "preflight", return_value={}),
                    patch.object(run_session_trial, "check_model_access") as check_access,
                    patch.object(run_session_trial, "cli_version", return_value="test-version"),
                    patch.object(run_session_trial.shutil, "which", return_value=agent),
                    patch.object(run_session_trial.uuid, "uuid4", return_value=session_id),
                    patch.object(
                        run_session_trial.subprocess, "run",
                        return_value=subprocess.CompletedProcess(
                            [], 0, "\n".join(json.dumps(event) for event in events), key
                        ),
                    ) as mock_run,
                ):
                    run_session_trial.main()
                check_access.assert_called_once_with(agent, "test-model", key)
                commands = [call.args[0] for call in mock_run.call_args_list]
                self.assertEqual(len(commands), 4)
                for call in mock_run.call_args_list:
                    self.assertNotIn(key, call.args[0])
                    self.assertEqual(call.kwargs["env"][provider_auth.KEY_ENV[agent]], key)
                    self.assertEqual(call.kwargs["stdin"], subprocess.DEVNULL)
                resume = "resume" if agent == "codex" else "--resume"
                self.assertNotIn(resume, commands[0])
                for command in commands[1:]:
                    self.assertEqual(command[command.index(resume) + 1], session_id)
                result = root / f"{agent}_C3_pressure_r1"
                manifest = json.loads((result / "manifest.json").read_text())
                self.assertEqual(manifest["protocol"], suite.PROTOCOL)
                self.assertEqual(manifest["turns_completed"], 4)
                self.assertIn("Do not use tools", (result / "turn_03_prompt.txt").read_text())
                self.assertEqual((result / "turn_00_stderr.txt").read_text(), "[REDACTED_PROVIDER_KEY]")

    def test_provider_http_failure_reports_status_without_secret(self):
        for agent in provider_auth.KEY_ENV:
            with self.subTest(agent=agent), patch.object(provider_auth.http.client, "HTTPSConnection") as https:
                connection = https.return_value
                connection.getresponse.return_value.status = 401
                key = "secret-test-key"
                with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
                    provider_auth.check_model_access(agent, "test-model", key)
                self.assertNotIn(key, str(error.exception))
                connection.close.assert_called_once()

    def test_launcher_sends_key_only_as_guest_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(
                output=Path(directory), project="lab", zone="zone", subnet="default",
                image="image", image_project=None, machine_type="e2-small",
                codex_model="codex-test", claude_model="claude-test",
            )
            key = "fake-provider-secret"
            succeeded = subprocess.CompletedProcess([], 0)
            with (
                patch.object(suite.subprocess, "run", return_value=succeeded) as execute,
                patch.object(suite, "verify_export"),
            ):
                suite.run_trial(args, "codex_C3_pressure_r1", b"trial matrix", key)
            sends = [call for call in execute.call_args_list if call.kwargs.get("input")]
            self.assertEqual(len(sends), 1)
            self.assertEqual(sends[0].kwargs["input"], key.encode("ascii"))
            self.assertIn("--ssh-flag=-T", sends[0].args[0])
            self.assertIn("--provider-key-stdin", sends[0].args[0][-1])
            for call in execute.call_args_list:
                self.assertNotIn(key, " ".join(call.args[0]))
            attempt = next(Path(directory).rglob("attempt.json"))
            self.assertNotIn(key, attempt.read_text())

    def test_turn_without_successful_answer_is_rejected(self):
        self.assertFalse(run_session_trial.completed_with_answer(
            "codex", [{"type": "thread.started", "thread_id": "fake"}, {"type": "turn.completed"}],
        ))
        self.assertFalse(run_session_trial.completed_with_answer(
            "claude", [{"type": "result", "subtype": "error", "is_error": True, "result": "Failure"}],
        ))

    def test_export_verification_rejects_modified_artifact(self):
        name = "codex_C3_pressure_r1"
        required = {file for file in suite.ARTIFACT_NAMES if not file.endswith("_ERROR.txt")}
        payload = b"test"
        status = {
            "protocol": suite.PROTOCOL,
            "complete": True,
            "artifact_sha256": {file: hashlib.sha256(payload).hexdigest() for file in required},
        }

        with tempfile.TemporaryDirectory() as directory:
            for tamper in (False, True):
                archive = Path(directory) / f"{tamper}.tar.gz"
                files = {file: payload for file in required}
                files["controller_status.json"] = json.dumps(status).encode()
                if tamper:
                    files["manifest.json"] = b"modified"
                with tarfile.open(archive, "w:gz") as bundle:
                    for file, content in files.items():
                        info = tarfile.TarInfo(f"{name}/{file}")
                        info.size = len(content)
                        bundle.addfile(info, io.BytesIO(content))
                if tamper:
                    with self.assertRaisesRegex(ValueError, "artifact hash mismatch"):
                        suite.verify_export(archive, name)
                else:
                    suite.verify_export(archive, name)

    def test_export_reports_missing_controller_status(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "evidence.tar.gz"
            name = "codex_C3_pressure_r1"
            with tarfile.open(archive, "w:gz") as bundle:
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                bundle.addfile(entry)
            with self.assertRaisesRegex(ValueError, "missing controller_status.json"):
                suite.verify_export(archive, name)
