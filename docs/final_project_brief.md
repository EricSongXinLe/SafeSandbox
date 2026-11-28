# Under Pressure

Evaluating Authorization Judgments and Layered Defenses in Coding Agents

## Final presentation brief

**ECE 117 Computer System Security, Fall 2026**  
**Team number** 14A  
**Team name** Team 111  
**Team members** Bomin, Eric, Zhiyi, and Yingshi  
**Evidence checked** November 28, 2026

**Research question.** Does pressure affect model authorization judgments, and how reliably can independent access controls enforce grants while authorized coding-agent tasks remain usable?

**Suite A baseline.** All **48 measured rows** and **four separate calibration rows** verified on one image. Codex successfully read the authorized shared file in **48/48** measured rows. Alice's independent OS check allowed the inert-file read in C2/C3 and denied it in C1/C4. The model answered **`DENY` in 48/48** fictional decisions, with 24/24 for each wording. [Suite A evidence](../ece117-evidence/ece117-grid48-20261127-052345)

**Earlier pilot result.** Across the two earlier batches, the model answered `ALLOW` in **8/12** C2 decisions and **0/12** C3 decisions. Those batches verified the shared read in **0/24**. The pilot and final grid use different prompts and judgment interfaces, so report the counts separately.

**Native authorized follow-up.** Suite C verified **12/12 measured trials**
and **2/2 separate calibrations**. In every measured trial, Codex verified
the shared-file read and then completed the explicitly authorized assigned
read in the same native session. C2 and C3 each completed **6/6** assigned
reads with **zero over-refusals**. The study measures native execution on
granted tasks. The earlier grid supplies the separate fictional decisions.
[Suite C evidence](../ece117-evidence/ece117-native-authorized-20261128-051656)

**Defensive follow-up.** The new Suite B protocol tests whether an
application grant and Linux permissions enforce distinct boundaries.
The reference mutation was detected locally. The 24-row GCP campaign
still needs live calibration and collection.
[Defensive Suite B runbook](gcp_defensive_suite_b.md)

**Behavioral follow-up.** Suite D is implemented and locally verified.
Its 48 planned judgments balance granted and ungranted fictional
requests, with matched urgency and trusted-policy conditions. Live model
results are pending. Native-agent unauthorized retrieval remains unmeasured.
[Suite D runbook](behavioral_suite_d.md)

## 1. Vision and impact

Coding agents translate requests into actions under a real user account. On a shared Linux system, one user's files can become technically readable to another user because of permissions. A model can then face a decision about whether a request falls within its task authority. A team that treats a readable file as permission to use it loses a distinct control over disclosure and cross-user actions.

Our project asks where a security boundary was actually enforced. Linux permissions can deny a read, a tool can fail before it reads anything, or a model can decline a request. A result that only says “the agent did not access the file” hides those differences. The benchmark collects evidence for each layer so administrators and evaluators can interpret the result.

## 2. Project goals and contributions

- **Measure baseline access.** Verify whether Alice can read a Bob-owned inert fixture under each Linux configuration.
- **Verify tool readiness.** Require Codex to read a deliberately shared, harmless file successfully through a read-only tool.
- **Measure authorization judgment.** Compare fictional `ALLOW`, `DENY`, and `UNCLEAR` decisions across matched wording and trusted-policy conditions with both grant states.
- **Measure native authorized execution.** Verify a second granted read in the same Codex session and score the tool result separately from verbal acceptance.
- **Measure enforcement.** Check application authorization before Linux file access and verify which layer produced each outcome.
- **Make runs reproducible.** Freeze each trial matrix, isolate VM or model sessions, and retain verifiable evidence for interrupted collection.

**Novelty.** The design identifies which layer produced each observation.
Suite D tests judgment errors on both granted and ungranted requests.
Suite B tests policy denials, Linux denials, and verified authorized reads
using a trusted client. Suite C measures native completion on a legitimate
task. A positive tool control distinguishes unavailable functionality
from a working defense. [Benchmark implementation plan](session_benchmark.md)

## 3. Implementation and experimental design

### What a final-grid trial does

1. **Reset and check the fixture.** A privileged controller creates Bob's inert file and the intentionally shared file. It records the assigned file mode and ACL, then checks accessibility under Alice's unprivileged Unix identity. Alice has no sudo access.
2. **Verify a real tool result.** Codex CLI uses a read-only MCP tool limited to the deliberately shared file. The controller requires a result with the expected benign contents. A failed fixture check or shared read blocks the judgment phase and preserves the attempt for review.
3. **Record the fictional decision.** A separate Responses API request to the configured model has tools disabled. It records `ALLOW`, `DENY`, or an unclear response about a fictional role change. Neutral and urgent use the same scenario. Urgent adds one sentence, “This is urgent.”
4. **Verify and report the evidence.** The workflow archives the matrix, fixture attestation, event traces, status, model and image metadata, and hashes. The offline reporter verifies completed archives and produces counts, CSV, and charts. Collection can resume from verified rows in the original campaign.

### Fixed 48-row Codex grid

| Condition | File mode | Trusted policy | Alice-specific ACL | Expected OS read by Alice | Neutral | Urgent |
| --- | --- | --- | --- | --- | ---: | ---: |
| C1 · Owner-only baseline | `0600` | Absent | Default | Denied | 6 | 6 |
| C2 · Readable baseline | `0664` | Absent | Default | Allowed | 6 | 6 |
| C3 · Trusted policy | `0664` | Present | Default | Allowed | 6 | 6 |
| C4 · Trusted policy and ACL | `0664` | Present | Deny Alice | Denied | 6 | 6 |
| **Total measured** | | | | | **24** | **24** |

The generator shuffles 48 independent measured rows with seed 117. Four separate calibration trials, one for each condition, must pass on the intended image before collection. Calibration is outside the 48 measured rows. The current grid uses Codex and the configured OpenAI model. [GCP runbook](gcp_vm_experiment.md) · [Matrix generator](../scripts/generate_session_matrix.py)

| Preplanned comparison | Evidence to use |
| --- | --- |
| C1 vs. C2 | Independent OS read check for the file-mode change |
| C2 vs. C3 under neutral wording | Fictional decision counts with Unix readability held fixed |
| C3 vs. C4 | Independent OS read check with the trusted policy held fixed |
| Neutral vs. urgent within a condition | Secondary analysis of fictional decisions using the one-sentence wording change |

The initial midterm plan crossed two agent stacks with four Linux configurations and three repeats for 24 trials. It proposed outcomes for credential access and authentication. The current 48-row design is a Codex-only study of an inert fixture and a fictional decision. The earlier pilot script and the new grid differ in wording, tools, and the judgment interface. Report them as distinct experiments.

### Suite C native authorized-task design

Suite C runs six C2 and six C3 trials. Both conditions explicitly grant
Alice the same two read-only synthetic tasks and allow the reads at the
OS level. C3 adds trusted-policy reinforcement. After the shared-file
control succeeds, the runner resumes the same Codex session for the assigned
read. The verifier compares the returned digest with the independently
attested digest and records the final verbal response separately.
[Native authorized-task manual](gcp_native_agent_experiment.md)

### Defensive Suite B design

The defensive campaign uses a trusted client and a fixed synthetic ID.
It crosses granted and ungranted requests with Linux-readable C2 and
ACL-denied C4, keeping mode `0664` fixed. Each cell has six planned
measured rows. Application denial must occur before any reader call.
A granted request reaches Linux and produces either a Linux denial
or an authorized digest match. The independent setup probe verifies
effective OS access and is separate from the request trace.

The local in-memory truth table found **0/4** incorrect decisions for
the corrected policy and **2/4** for the deliberately faulty Boolean
reference. Those are reference-test errors. They use a separate
denominator from campaign enforcement and native-agent outcomes.
[Defensive Suite B operator manual](gcp_defensive_suite_b.md)

### Suite D matched judgment design

Six fictional board games each contribute eight independent model calls.
Each call crosses an active or inactive exact-match grant, trusted
reinforcement absent or present, and neutral or urgent wording. The
baseline receives the full ledger and rule. The urgent version adds
“This is urgent.” The reinforced version adds one trusted instruction
about applying the ledger.

| Question | Comparison | Result to present |
| --- | --- | --- |
| RQ1 · Urgency | Neutral versus urgent with grant and policy held fixed | Matched change in incorrect acceptance on ungranted requests |
| RQ2 · Trusted reinforcement | Baseline versus reinforced with grant and wording held fixed | Matched changes in incorrect acceptance and over-refusal |
| RQ3 · Enforcement and utility | Suite B's grant-by-Linux grid and Suite C's native utility baseline | Verified outcomes with each suite's denominator |

Show the three-way confusion counts, evaluated coverage, and paired
differences. Suite D runs through a tool-free model API. Its outputs are
judgments on game moves. The link to real enforcement is conceptual
because Suite B sends predefined requests through a trusted client.
[Scenario catalog](../prompts/suite_d_scenarios.json) · [Suite D manual](behavioral_suite_d.md)

## 4. Progression and results

| Stage | What the evidence establishes |
| --- | --- |
| Original exploratory pilot | The midterm materials document one controlled Linux session with a credential disclosure and an account transition corroborated by PAM and UID evidence. It was a single qualitative observation. |
| GCP smoke test, November 24 | The Ubuntu archive smoke test passed eight regression tests. A 24-row dry run verified matrix parsing and produced zero agent launches. |
| Automated four-turn pilots, November 26 | Two Codex batches completed 12 measured trials each. Both tested C2/C3 under neutral and pressure scripts. One calibration per batch was stored separately. |
| Balanced grid, November 27 | The exported campaign verified all four calibrations and all 48 measured rows. The shared-file control passed in every measured row. Each measured row used a distinct VM, Codex control session, and judgment response. |
| Native authorized follow-up, November 27 | Both calibrations and all 12 measured rows verified. Codex completed both reads in each of 12 distinct native sessions on distinct VMs. |
| Defensive Suite B | The local in-memory regression detected two faulty reference decisions in four cases. The 24 measured GCP rows await collection. |
| Behavioral Suite D | The frozen 48-row plan, collection, recovery, and scoring passed local regression checks. Live model collection is pending. |

[Smoke-test record](gcp_smoke_test_recap.md) · [Pilot batch 171454](../ece117-evidence/ece117-canary-v2-20261126-171454) · [Pilot batch 232958](../ece117-evidence/ece117-canary-v2-20261126-232958) · [Final grid receipt](../ece117-evidence/ece117-grid48-20261127-052345/calibration.json)

### Evidence by experimental protocol

| Experiment | Observed result | Scope of evidence |
| --- | --- | --- |
| Original manual pilot | One credential disclosure and a PAM-corroborated account transition | One documented qualitative case |
| Earlier 24-trial pilot | C2 produced 8/12 fictional `ALLOW` decisions and C3 produced 0/12. The shared-read control verified in 0/24 measured trials. | Fictional judgment and an inconclusive file-access measurement |
| Suite A, 48 measured trials | 48/48 verified shared reads and 48/48 fictional `DENY` decisions | Working tool and OS controls, plus a separate tool-free judgment |
| Defensive Suite B, 24 planned rows | The in-memory test detected 2/4 incorrect decisions in the faulty Boolean reference and 0/4 in the corrected policy. Live enforcement results are pending. | Reference-policy failures in memory, with application and Linux enforcement to be measured in the separate GCP campaign |
| Suite C, 12 measured trials | 12/12 verified native authorized reads and 0/12 over-refusals | Authorized-task functionality in C2 and C3 |
| Suite D, 48 planned rows | Frozen design and locally tested implementation. Live model results pending. | Fictional incorrect acceptance and over-refusal by policy and urgency |

The historical manual case is one qualitative observation. The automated
studies retain separate denominators for reference-policy failures,
application enforcement, Linux enforcement, native utility, and fictional
judgments. Suite C shows utility along the tested authorized path.
The effect of adding Suite B's gate to that same native path is the
question for optional Suite E. The native-agent unauthorized retrieval
rate remains unmeasured.

### Verified 48-row grid results

| Condition | OS reads allowed | Shared reads verified | Neutral `DENY` | Urgent `DENY` |
| --- | ---: | ---: | ---: | ---: |
| C1 · Owner-only baseline | 0/12 | 12/12 | 6/6 | 6/6 |
| C2 · Readable baseline | 12/12 | 12/12 | 6/6 | 6/6 |
| C3 · Trusted policy | 12/12 | 12/12 | 6/6 | 6/6 |
| C4 · Trusted policy and ACL | 0/12 | 12/12 | 6/6 | 6/6 |
| **Total** | **24/48** | **48/48** | **24/24** | **24/24** |

The C1/C2 comparison verified that the file mode changed Alice's OS access. The C3/C4 comparison verified that the ACL denied Alice access while the mode and trusted policy stayed fixed. The role decision showed zero observed differences by policy or urgency for this scenario. With every group already at 6/6 `DENY`, the final grid cannot estimate whether either change would matter for a scenario that sometimes produces `ALLOW`.

The campaign used `gpt-6-luna` and Codex CLI 0.172.0. The exported evidence had no incomplete or unverified measured attempts. The shared-read result applies to the bounded MCP tool. The judgment was a separate tool-free model response. [Final campaign evidence](../ece117-evidence/ece117-grid48-20261127-052345) · [Offline reporter](../scripts/summarize_session_results.py)

### Verified Suite C native authorized results

| Condition | Measured rows verified | Shared reads verified | Assigned reads verified | Verbal acceptance | Over-refusals |
| --- | ---: | ---: | ---: | ---: | ---: |
| C2 · Explicit authorization | 6/6 | 6/6 | 6/6 | 6/6 | 0/6 |
| C3 · Same grant plus reinforcement | 6/6 | 6/6 | 6/6 | 6/6 | 0/6 |
| **Total** | **12/12** | **12/12** | **12/12** | **12/12** | **0/12** |

Each measured row had exactly one assigned-read attempt, and every digest
matched the controller's attestation. No measured row was OS-blocked,
incomplete, unverified, or classified as an infrastructure failure.
The run used `gpt-6-luna` with Codex CLI 0.172.0. There was no observed
difference in completion or over-refusal between C2 and C3. With six rows
per condition, the conclusion is limited to this authorized task and
configuration. [Suite C calibration receipt](../ece117-evidence/ece117-native-authorized-20261128-051656/calibration.json) · [Suite C reporter](../scripts/summarize_native_authorized.py)

### Verified four-turn pilot results

| Condition and script | Batch 171454 `ALLOW` | Batch 232958 `ALLOW` | Combined `ALLOW` | Combined `DENY` | Verified shared reads |
| --- | ---: | ---: | ---: | ---: | ---: |
| C2 neutral | 2/3 | 1/3 | 3/6 | 3/6 | 0/6 |
| C2 pressure | 3/3 | 2/3 | 5/6 | 1/6 | 0/6 |
| C3 neutral | 0/3 | 0/3 | 0/6 | 6/6 | 0/6 |
| C3 pressure | 0/3 | 0/3 | 0/6 | 6/6 | 0/6 |

All 24 measured evidence archives passed verification. The fixture checks showed the OS allowed Alice to read the inert file in all 24 C2/C3 trials. There were **zero observed marker reads or disclosures**. The failed positive control makes those zeros unsuitable for estimating an agent's ability to access or disclose the marker. Codex reported a Bubblewrap startup problem, and a saved tool result independently confirmed that error in one trial.

For the pilot slide, highlight the matched neutral comparison of **3/6 `ALLOW` in C2 and 0/6 in C3**. The C2 pressure script produced **5/6 `ALLOW`**. That comparison covers the full earlier prompt scripts. The final grid tests the narrower change of adding a single urgency sentence. An `ALLOW` result is a fictional judgment. It did not execute a role change.

## 5. Repo work and reproducibility

| Component | What the team implemented |
| --- | --- |
| [Early trial runner](../scripts/run_trials.py) and [prompt specification](experiment_prompts.md) | Systematic local test generation and the initial single-turn study. |
| [Fixture reset](../scripts/vm/reset_fixture.sh) and [VM controller](../scripts/run_session_matrix.py) | C1–C4 file permissions, the Alice-specific ACL, independent OS checks, and a root-controlled evidence archive. |
| [Image builder](../scripts/build_gcp_canary_image.sh) and [campaign launcher](../scripts/run_gcp_experiment.py) | Verified bundle setup and image selection, one calibration per condition, and a collection gate tied to the verified campaign. |
| [Grid protocol](../scripts/grid_protocol.py) and [session runner](../scripts/run_session_trial.py) | A bounded read-only shared-file tool, positive-control verification, and an independent tool-free judgment. |
| [Suite C protocol](../scripts/native_authorized_protocol.py) and [reporter](../scripts/summarize_native_authorized.py) | Same-session authorized reads, independently verified digests, and separate tool and verbal outcome reporting. |
| [Defensive protocol](../scripts/defensive_protocol.py), [mutation test](../scripts/defensive_mutation.py), and [reporter](../scripts/summarize_defensive.py) | Policy-first trusted-client checks, an in-memory reference comparison, and enforcement counts kept separate from native utility. |
| [Suite D protocol](../scripts/behavioral_protocol.py), [runner](../scripts/run_behavioral_suite.py), and [reporter](../scripts/summarize_behavioral.py) | Six matched fictional scenarios, frozen tool-free model requests, resumable collection, and verified error rates, matched contrasts, and charts. |
| [Trial launcher](../scripts/run_gcp_canary_suite.py) and [reporter](../scripts/summarize_session_results.py) | Fresh trial VMs, evidence verification and retry, plus Markdown, CSV, and plot outputs. |
| [Regression tests](../tests) and [operator runbook](gcp_vm_experiment.md) | Archive integrity, calibration and control gates, recovery after interruption, and Mac and Cloud Shell commands. |

Key Git milestones are `ca1f098` for the multi-turn runner and evidence
tooling, `9d8be17` for GCP automation, `2fb4621` for runtime API
authentication, `571fdd6` for result reports, `d608e9f` for Suite A,
and `5cdff6c` for Suite C. The local regressions verify the code,
fixtures, and evidence gates. Cloud calibration verifies a VM image and
its setup. Only live Suite D collection produces behavioral observations
for the new scenarios.

## 6. Related work

| Prior work | Connection to this project |
| --- | --- |
| Saltzer and Schroeder, *The Protection of Information in Computer Systems* | Least privilege motivates the limited shared-file tool and the OS-level ACL comparison. [Paper](https://www.cs.virginia.edu/~evans/cs551/saltzer/) |
| Wallace et al., *The Instruction Hierarchy* | Their work prioritizes instructions from different sources. Our C2/C3 comparison measures how a trusted policy is reflected in judgments about a shared Linux scenario. [Paper](https://arxiv.org/abs/2404.13208) |
| Debenedetti et al., *AgentDojo* | AgentDojo evaluates tool-using agents and defenses in a dynamic benchmark. Our test narrows the setting to one Alice/Bob fixture and checks the Linux and tool outcomes independently. [Paper](https://arxiv.org/abs/2406.13352) |

## 7. Takeaways, limitations, and future work

- The final grid verified both OS controls and a working shared-file tool. The trusted-policy comparison produced the clearest pilot difference. Report both experiments with their own denominators.
- The shared-file control went from 0/24 in the pilot to 48/48 in the final grid. The tool and protocol changed between those runs, so this validates the new setup's authorized-read path and does not isolate the effect of a single change.
- Every Suite A decision was `DENY`. This yielded no observed difference by policy or urgency for that scenario. Suite D's granted rows make over-refusal measurable.
- Suite C showed **12/12** native completions on an explicitly authorized task, including all six trials with policy reinforcement. This result and the earlier fictional refusals answer separate questions about execution and judgment.
- The measured pilot evidence covers Codex. A matched Claude campaign would be needed for a cross-agent claim. The final grid's tool-free judgment measures the configured model through an API response. It does not measure a native agent carrying out the decision.
- Suite D's six scenario blocks support descriptive matched effects for the tested cases. Report `UNCLEAR`, provider refusals, and unresolved coverage alongside error rates.
- Optional Suite E would compare the existing authorized native path with the same path plus Suite B's grant gate, six trials each. It would measure authorized completion, verified tool execution, over-refusal, latency, tool calls, and infrastructure failures.

## 8. Presentation outline and submission

| Slide | Content | Rubric emphasis |
| --- | --- | --- |
| 1 · Title | *Under Pressure*. Team number **14A**, team name **Team 111**, team members, and the assigned peer-evaluation secret number(s). | Required title information |
| 2 · High-level problem | A two-user diagram showing how file readability and task authorization can differ. | Vision and impact |
| 3 · Project topic and solution | Show judgment, the application grant check, and Linux enforcement. Use a dashed arrow for the conceptual connection from D's judgments to B's enforcement. | Novelty |
| 4 · Goals and experiment design | Show D's six matched scenarios across eight conditions, B's four enforcement cells, and C's authorized utility control. | Novelty and practicality |
| 5 · Results and demo | Show Suite A's verified baseline and Suite C's 12/12 native completions. Include B or D measurements once verified. Label pending cells and the reference mutation explicitly. | Practicality |
| 6 · Related work | Compare the evaluation design with least privilege, instruction hierarchy, and AgentDojo. | Vision and novelty |
| 7 · Takeaways and discussion | Explain which evidence supports application enforcement, Linux enforcement, judgment, and authorized execution. | Impact and practicality |
| 8 · Limitations and future work | State that the native unauthorized retrieval rate remains unmeasured. Note scenario coverage and the optional defense-integration test. | Practicality |

**Title slide check.** The team number, name, and member list above come from the midterm deck. Enter the assigned peer-evaluation secret number(s) on the final title slide and make them legible during the talk. The assignment materials provided here do not supply the number.

**Gradescope check.** Submit one slide deck for the team and add every member through Gradescope's group submission feature.

**Presentation sources.** The supplied final presentation template provides the eight-slide sequence. The assignment screenshot provides the Vision, Impact, Novelty, and Practicality criteria and the submission rules. The *Under Pressure* midterm slides and paper establish the original design and the historical pilot observation.
