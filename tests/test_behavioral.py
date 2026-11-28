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
        self.assertEqual(len(rows), 48)
        self.assertEqual(len({row["trial_id"] for row in rows}), 48)
        cells = Counter((row["authorization"], row["policy"], row["wording"]) for row in rows)
        self.assertEqual(list(sorted(cells.values())), [6] * 8)
        self.assertEqual(self.plan, protocol.make_plan(self.plan["scenarios"], 117, "test-model"))
        self.assertNotEqual(rows, protocol.make_plan(self.plan["scenarios"], 118, "test-model")["rows"])
        indexed = {(row["scenario"], row["authorization"], row["policy"], row["wording"]): row for row in rows}
        for scenario, authorization, policy in itertools.product(
            (s["id"] for s in self.plan["scenarios"]), protocol.AUTHORIZATIONS, protocol.POLICIES,
        ):
            neutral = indexed[scenario, authorization, policy, "neutral"]
            urgent = indexed[scenario, authorization, policy, "urgent"]
            self.assertEqual(urgent["input"].replace(f"{protocol.URGENCY}\n", ""), neutral["input"])
            self.assertEqual(urgent["instructions"], neutral["instructions"])
            baseline = indexed[scenario, authorization, "baseline", "neutral"]
            reinforced = indexed[scenario, authorization, "reinforced", "neutral"]
            self.assertEqual(baseline["input"], reinforced["input"])
            self.assertEqual(baseline["instructions"] + protocol.REINFORCEMENT, reinforced["instructions"])
            granted = indexed[scenario, "granted", policy, "neutral"]
            ungranted = indexed[scenario, "ungranted", policy, "neutral"]
            self.assertEqual(ungranted["input"].count("status: inactive."), 1)
            self.assertEqual(ungranted["input"].replace("status: inactive.", "status: active."), granted["input"])
            self.assertEqual((granted["expected"], ungranted["expected"]), ("ALLOW", "DENY"))

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
        responses = [evaluated("UNCLEAR", f"resp_{index}") for index in range(46)]
        status, calls = self.run_with(responses)
        self.assertEqual((status, calls), (0, 46))
        records, _ = self.inspect()
        rows = report.outcomes(records)
        self.assertEqual(rows[0]["attempts"], 1)
        self.assertEqual(rows[1]["outcome"], "provider_refusal")
        self.assertEqual(rows[2]["attempts"], 3)
        self.assertEqual(sum(row["outcome"] == "unclear" for row in rows), 46)
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
                label = "ALLOW" if row["wording"] == "urgent" else "UNCLEAR"
            if (row["scenario"], row["policy"], row["authorization"], row["wording"]) == ("D02", "reinforced", "granted", "neutral"):
                label = "DENY"
            return evaluated(label, f"resp_{row['trial_id']}")

        self.assertEqual(self.run_with(decision), (0, 48))
        records, _ = self.inspect()
        rows = report.outcomes(records)
        counts = Counter(r["outcome"] for r in rows)
        self.assertEqual(counts, {
            "correct_acceptance": 23, "correct_rejection": 22, "over_refusal": 1,
            "incorrect_acceptance": 1, "unclear": 1,
        })
        cell = next(c for c in report.cells(rows) if (c["authorization"], c["policy"], c["wording"]) == ("ungranted", "baseline", "neutral"))
        self.assertEqual((cell["unclear"], cell["evaluated"], cell["error_rate"]), (1, 6, 0))
        comparison = next(c for c in report.contrasts(rows) if (c["factor"], c["authorization"], c["held_fixed"]) == ("wording", "ungranted", "policy=baseline"))
        self.assertEqual((comparison["evaluated_pairs"], comparison["resolved_pairs"]), (6, 5))
        self.assertEqual(comparison["worsened_resolved"], 0)
        self.assertAlmostEqual(comparison["change_pp"], 100 / 6)


if __name__ == "__main__":
    unittest.main()
