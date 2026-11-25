import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts import run_session_trial

with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1] / "scripts"), *sys.path]):
    from scripts import run_gcp_canary_suite as suite


class CanarySuiteTest(unittest.TestCase):
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
                    "--output", directory, "--execute",
                ]
                with (
                    patch.object(sys, "argv", argv),
                    patch.object(run_session_trial, "LAB_MARKER", marker),
                    patch.object(run_session_trial, "preflight", return_value={}),
                    patch.object(run_session_trial, "cli_version", return_value="test-version"),
                    patch.object(run_session_trial.shutil, "which", return_value=agent),
                    patch.object(run_session_trial.uuid, "uuid4", return_value=session_id),
                    patch.object(
                        run_session_trial.subprocess, "run",
                        return_value=subprocess.CompletedProcess(
                            [], 0, "\n".join(json.dumps(event) for event in events), ""
                        ),
                    ) as mock_run,
                ):
                    run_session_trial.main()
                commands = [call.args[0] for call in mock_run.call_args_list]
                self.assertEqual(len(commands), 4)
                resume = "resume" if agent == "codex" else "--resume"
                self.assertNotIn(resume, commands[0])
                for command in commands[1:]:
                    self.assertEqual(command[command.index(resume) + 1], session_id)
                result = root / f"{agent}_C3_pressure_r1"
                manifest = json.loads((result / "manifest.json").read_text())
                self.assertEqual(manifest["protocol"], suite.PROTOCOL)
                self.assertEqual(manifest["turns_completed"], 4)
                self.assertIn("Do not use tools", (result / "turn_03_prompt.txt").read_text())

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
