"""Regression checks for the tool-free matched behavioral study."""

import io
import itertools
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import behavioral_protocol as protocol
import behavioral_multiturn as multi
import run_behavioral_suite as runner
import summarize_behavioral as report


def response(decision, response_id="resp_a", model="test-model-v1"):
    return {
        "id": response_id, "model": model, "status": "completed", "output": [{
            "type": "message", "content": [{"type": "output_text", "text": json.dumps({"decision": decision})}],
        }],
    }


def evaluated(decision, response_id="resp_a", model="test-model-v1"):
    return "evaluated", {"response": response(decision, response_id, model), "decision": decision}


class BehavioralTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "campaign"
        self.plan = runner.create_campaign(self.directory, "test-model", 117)

    def inspect(self):
        plan, plan_hash = runner.load_campaign(self.directory)
        return runner.inspect_campaign(self.directory, plan, plan_hash)

    def run_with(self, side_effect):
        with patch.dict(os.environ, OPENAI_API_KEY="test-secret-key"), patch.object(
            runner, "request_decision", side_effect=side_effect,
        ) as request, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            status = runner.collect(self.directory, execute=True, timeout=20)
        return status, request.call_count

    def test_matrix_is_balanced_seeded_and_matched(self):
        rows = self.plan["rows"]
        self.assertEqual(self.plan["plan"], "behavioral-d72")
        self.assertEqual(len(rows), 72)
        self.assertEqual(len({row["trial_id"] for row in rows}), 72)
        cells = Counter((row["authorization"], row["policy"], row["wording"]) for row in rows)
        self.assertEqual(list(sorted(cells.values())), [6] * 12)
        self.assertEqual(self.plan, protocol.make_plan(self.plan["scenarios"], 117, "test-model"))
        self.assertNotEqual(rows, protocol.make_plan(self.plan["scenarios"], 118, "test-model")["rows"])
        indexed = {(row["scenario"], row["authorization"], row["policy"], row["wording"]): row for row in rows}
        for scenario, authorization, policy in itertools.product(
            (s["id"] for s in self.plan["scenarios"]), protocol.AUTHORIZATIONS, protocol.POLICIES,
        ):
            neutral = indexed[scenario, authorization, policy, "neutral"]
            for wording, sentence in (
                ("urgent", protocol.URGENCY), ("claimed-grant", protocol.CLAIMED_GRANT),
            ):
                variant = indexed[scenario, authorization, policy, wording]
                self.assertEqual(variant["input"].splitlines()[-2], sentence)
                self.assertEqual(variant["input"].replace(f"{sentence}\n", ""), neutral["input"])
                self.assertEqual(variant["instructions"], neutral["instructions"])
                self.assertEqual(variant["expected"], neutral["expected"])
            baseline = indexed[scenario, authorization, "baseline", "neutral"]
            reinforced = indexed[scenario, authorization, "reinforced", "neutral"]
            self.assertEqual(baseline["input"], reinforced["input"])
            self.assertEqual(baseline["instructions"] + protocol.REINFORCEMENT, reinforced["instructions"])
            granted = indexed[scenario, "granted", policy, "neutral"]
            ungranted = indexed[scenario, "ungranted", policy, "neutral"]
            self.assertEqual(ungranted["input"].count("status: inactive."), 1)
            self.assertEqual(ungranted["input"].replace("status: inactive.", "status: active."), granted["input"])
            self.assertEqual((granted["expected"], ungranted["expected"]), ("ALLOW", "DENY"))

    def test_legacy_campaign_verifies_with_original_plan_hash(self):
        plan = protocol.make_plan(self.plan["scenarios"], 117, "test-model", "ece117-behavioral-d-v1")
        runner.write_envelope(self.directory / "plan.json", plan)
        (self.directory / "matrix.csv").write_bytes(protocol.matrix_bytes(plan))
        _, plan_hash = runner.load_campaign(self.directory)
        self.assertEqual(plan_hash, "ee6df0f5c756beebe0ecdd48a4dadc52454c8aa4bee35fc2865b3a2605c49df9")
        records, _ = self.inspect()
        rows = report.outcomes(records)
        self.assertEqual(len(rows), 48)
        self.assertEqual(len(report.cells(rows)), 8)
        self.assertEqual(len(report.contrasts(rows)), 8)

    def test_preview_is_offline_and_request_has_no_tools_or_ground_truth(self):
        with patch.object(runner, "request_decision") as request, patch.object(
            runner, "prompt_provider_keys",
        ) as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(runner.collect(self.directory, execute=False, timeout=20), 0)
        request.assert_not_called()
        prompt.assert_not_called()
        self.assertFalse((self.directory / "attempts").exists())
        payload = protocol.payload(self.plan, self.plan["rows"][0])
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertIs(payload["store"], False)
        self.assertTrue(payload["text"]["format"]["strict"])
        self.assertNotIn("expected", payload)
        self.assertNotIn("previous_response_id", payload)

    def test_contract_and_transport(self):
        refusal = response("ALLOW")
        refusal["output"][0]["content"] = [{"type": "refusal", "refusal": "declined"}]
        self.assertEqual(protocol.decode_decision(refusal), ("provider_refusal", None))
        self.assertEqual(protocol.decode_decision(response("uncertain")), ("invalid_decision", None))
        self.assertEqual(protocol.decode_decision(response("UNCLEAR")), ("evaluated", "UNCLEAR"))
        item = response("ALLOW")
        item["output"].append({"type": "function_call"})
        self.assertEqual(protocol.decode_decision(item), ("unexpected_output", None))
        raw = {**response("DENY"), "output": [
            {"type": "reasoning", "summary": [{"text": "reasoning details"}]}, *response("DENY")["output"],
        ]}
        with patch.object(runner.http.client, "HTTPSConnection") as https:
            connection = https.return_value
            connection.getresponse.return_value.status = 200
            connection.getresponse.return_value.read.return_value = json.dumps(raw).encode()
            status, saved = runner.request_decision(protocol.payload(self.plan, self.plan["rows"][0]), "test-key", 20)
        https.assert_called_once_with("api.openai.com", timeout=20)
        self.assertEqual(connection.request.call_args.args, ("POST", "/v1/responses"))
        self.assertEqual(status, "evaluated")
        self.assertEqual(saved["response"]["output"][0], {"type": "reasoning"})
        self.assertNotIn("test-key", json.dumps(saved))

    def test_resume_skips_evaluated_and_unscorable_responses(self):
        failure = ("http_error", {"http_status": 429})
        refusal = response("ALLOW", "resp_refused")
        refusal["output"][0]["content"] = [{"type": "refusal", "refusal": "declined"}]
        status, calls = self.run_with([evaluated("ALLOW"), ("provider_refusal", {"response": refusal, "decision": None}), failure])
        self.assertEqual((status, calls), (1, 3))
        with self.assertRaises(KeyboardInterrupt):
            self.run_with([KeyboardInterrupt()])
        records, model = self.inspect()
        self.assertEqual(model, "test-model-v1")
        self.assertEqual([a["status"] for a in records[2]["attempts"]], ["http_error", "started"])
        remaining = len(self.plan["rows"]) - 2
        responses = [evaluated("UNCLEAR", f"resp_{index}") for index in range(remaining)]
        status, calls = self.run_with(responses)
        self.assertEqual((status, calls), (0, remaining))
        records, _ = self.inspect()
        rows = report.outcomes(records)
        self.assertEqual(rows[0]["attempts"], 1)
        self.assertEqual(rows[1]["outcome"], "provider_refusal")
        self.assertEqual(rows[2]["attempts"], 3)
        self.assertEqual(sum(row["outcome"] == "unclear" for row in rows), remaining)
        self.assertEqual(self.run_with([]), (0, 0))

    def test_model_drift_and_duplicate_responses_stop_collection(self):
        self.assertEqual(self.run_with([evaluated("DENY"), evaluated("ALLOW", "resp_b", "test-model-v2")]), (1, 2))
        records, model = self.inspect()
        self.assertEqual(model, "test-model-v1")
        self.assertEqual(records[1]["attempts"][-1]["status"], "model_mismatch")
        self.assertEqual(self.run_with([evaluated("ALLOW")]), (1, 1))
        records, _ = self.inspect()
        self.assertEqual(records[1]["attempts"][-1]["status"], "duplicate_response")

    def test_verification_detects_matrix_and_attempt_changes(self):
        self.assertEqual(self.run_with([evaluated("DENY"), ("transport_error", {})]), (1, 2))
        attempt = next((self.directory / "attempts" / self.plan["rows"][0]["trial_id"]).glob("*.json"))
        attempt.write_bytes(attempt.read_bytes().replace(b'"decision":"DENY"', b'"decision":"ALLOW"', 1))
        records, _ = self.inspect()
        self.assertEqual(report.outcomes(records)[0]["status"], "unverified")
        with self.assertRaisesRegex(ValueError, "unverified attempt evidence"):
            self.run_with([])
        path = self.directory / "matrix.csv"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.inspect()

    def test_scoring_and_paired_denominators(self):
        def decision(request, _key, _timeout):
            row = next(r for r in self.plan["rows"] if protocol.payload(self.plan, r) == request)
            label = row["expected"]
            if row["scenario"] == "D01" and row["policy"] == "baseline" and row["authorization"] == "ungranted":
                label = "UNCLEAR" if row["wording"] == "neutral" else "ALLOW"
            if (row["scenario"], row["policy"], row["authorization"], row["wording"]) == ("D02", "reinforced", "granted", "neutral"):
                label = "DENY"
            return evaluated(label, f"resp_{row['trial_id']}")

        self.assertEqual(self.run_with(decision), (0, 72))
        records, _ = self.inspect()
        rows = report.outcomes(records)
        counts = Counter(r["outcome"] for r in rows)
        self.assertEqual(counts, {
            "correct_acceptance": 35, "correct_rejection": 33, "over_refusal": 1,
            "incorrect_acceptance": 2, "unclear": 1,
        })
        cell = next(c for c in report.cells(rows) if (c["authorization"], c["policy"], c["wording"]) == ("ungranted", "baseline", "neutral"))
        self.assertEqual((cell["unclear"], cell["evaluated"], cell["error_rate"]), (1, 6, 0))
        comparisons = report.contrasts(rows)
        self.assertEqual(len(comparisons), 14)
        wording = [c for c in comparisons if (c["factor"], c["authorization"], c["held_fixed"]) == (
            "wording", "ungranted", "policy=baseline",
        )]
        self.assertEqual([c["variant"] for c in wording], ["urgent", "claimed-grant"])
        for comparison in wording:
            self.assertEqual((comparison["evaluated_pairs"], comparison["resolved_pairs"]), (6, 5))
            self.assertEqual(comparison["worsened_resolved"], 0)
            self.assertAlmostEqual(comparison["change_pp"], 100 / 6)
        reinforcement = next(c for c in comparisons if (c["factor"], c["authorization"], c["held_fixed"]) == (
            "policy", "ungranted", "wording=claimed-grant",
        ))
        self.assertAlmostEqual(reinforcement["change_pp"], -100 / 6)

    def use_multiturn(self):
        self.directory = self.directory.with_name("multiturn")
        self.plan = runner.create_campaign(self.directory, "test-model", 117, design="multi-turn")

    def test_multiturn_plan_changes_only_the_assigned_final_turn(self):
        self.use_multiturn()
        rows = self.plan["rows"]
        self.assertEqual(len(rows), 108)
        self.assertEqual(len({row["session_id"] for row in rows}), 36)
        indexed = {(row["scenario"], row["initial_authorization"], row["arm"], row["turn"]): row for row in rows}
        for scenario, initial in itertools.product(self.plan["scenarios"], protocol.AUTHORIZATIONS):
            for turn in (1, 2, 3):
                neutral, claimed, updated = (indexed[scenario["id"], initial, arm, turn] for arm in multi.ARMS)
                self.assertEqual(claimed["expected"], neutral["expected"])
                self.assertEqual(updated["expected"] == neutral["expected"], turn < 3)
                self.assertEqual(claimed["instructions"], neutral["instructions"])
                self.assertEqual(claimed["input"], neutral["input"] if turn < 3 else f"{protocol.CLAIMED_GRANT}\n{neutral['input']}")
                self.assertEqual(updated["input"], neutral["input"])
                if turn < 3:
                    self.assertEqual(updated["instructions"], neutral["instructions"])
                else:
                    active, inactive = sorted((neutral["instructions"], updated["instructions"]))
                    first = [line for line in active.splitlines() if line not in inactive.splitlines()]
                    second = [line for line in inactive.splitlines() if line not in active.splitlines()]
                    self.assertEqual(len(first), 1)
                    self.assertEqual(first[0].replace("status: active.", "status: inactive."), second[0])

    def test_multiturn_resumes_with_verified_visible_history_and_reports_transitions(self):
        self.use_multiturn()
        first, second, third = self.plan["rows"][:3]
        first_reply = evaluated(first["expected"], "resp_initial")
        first_reply[1]["response"]["output"][0]["phase"] = "final_answer"
        self.assertEqual(self.run_with([first_reply, ("http_error", {"http_status": 429})]), (1, 2))
        seen = []
        remaining = iter(self.plan["rows"][1:])

        def mock(request, _key, _timeout):
            row = next(remaining)
            seen.append(request)
            answer = row["expected"]
            if row["turn"] == 3 and row["arm"] == "claimed-grant" and row["initial_authorization"] == "ungranted":
                answer = "ALLOW"
            return evaluated(answer, f"resp_{row['trial_id']}")

        self.assertEqual(self.run_with(mock), (0, 107))
        self.assertEqual(seen[0]["input"], [
            {"role": "user", "content": first["input"]},
            {"role": "assistant", "content": json.dumps({"decision": first["expected"]}), "phase": "final_answer"},
            {"role": "user", "content": second["input"]},
        ])
        self.assertEqual(len(seen[1]["input"]), 5)
        self.assertEqual(seen[1]["instructions"], third["instructions"])
        self.assertEqual(len(seen[2]["input"]), 1)
        self.assertTrue(all(request["tool_choice"] == "none" and not request["tools"] and not request["store"] for request in seen))
        records, model = self.inspect()
        rows = report.outcomes(records)
        text, sessions = report.multiturn_report(self.plan, "hash", model, rows)
        self.assertIn("36/36", text)
        self.assertIn("108/108", text)
        self.assertEqual(sum(s["incorrect_flip"] is True for s in sessions), 6)
        self.assertEqual(sum(s["correct_update"] is True for s in sessions), 12)
        self.assertEqual(sum(s["first_incorrect_turn"] == 3 for s in sessions), 6)
        self.assertEqual(self.run_with([]), (0, 0))

    def test_multiturn_missing_or_changed_history_is_visible(self):
        self.use_multiturn()
        refusal = response("ALLOW", "resp_refused")
        refusal["output"][0]["content"] = [{"type": "refusal", "refusal": "declined"}]
        denied = ("provider_refusal", {"response": refusal, "decision": None})
        failure = ("transport_error", {})
        self.assertEqual(self.run_with([denied, evaluated("ALLOW"), evaluated("ALLOW", "resp_b"), failure]), (1, 4))
        records, _ = self.inspect()
        self.assertEqual([row["status"] for row in report.outcomes(records)[:3]], [
            "provider_refusal", "blocked_history", "blocked_history",
        ])
        completed = self.directory / "attempts" / self.plan["rows"][3]["trial_id"] / "000001.json"
        evidence = runner.read_envelope(completed)
        evidence["decision"] = "DENY"
        evidence["response"] = response("DENY")
        runner.write_envelope(completed, evidence)
        records, _ = self.inspect()
        self.assertIn("attempt metadata mismatch", records[4]["verification_error"])
        self.assertIn("without verified prior turns", records[5]["verification_error"])


if __name__ == "__main__":
    unittest.main()
