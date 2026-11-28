# Under Pressure

## Final presentation brief

**ECE 117 Computer System Security, Fall 2026**  
**Team number** 14A  
**Team name** Team 111  
**Team members** Bomin, Eric, Zhiyi, and Yingshi  
**Evidence checked** November 27, 2026

**Main claim.** A coding agent can have operating-system access that exceeds its task authorization. We built a reproducible benchmark that measures Linux access, the agent's ability to complete an authorized tool task, and the model's authorization judgment separately.

**Final result.** All **48 measured rows** and **four separate calibration rows** verified on one image. Codex successfully read the authorized shared file in **48/48** measured rows. Alice's independent OS check allowed the inert-file read in C2/C3 and denied it in C1/C4. The model answered **`DENY` in 48/48** fictional decisions, with 24/24 for each wording. [Final campaign evidence](../ece117-evidence/ece117-grid48-20261127-052345)

**Earlier pilot result.** Across the two earlier batches, the model answered `ALLOW` in **8/12** C2 decisions and **0/12** C3 decisions. Those batches verified the shared read in **0/24**. The pilot and final grid use different prompts and judgment interfaces, so report the counts separately.

**Native authorized follow-up.** The final grid verified tool readiness and
recorded fictional judgments in separate sessions. The new Suite C tests
whether a native Codex session completes a second, explicitly authorized
synthetic task after the first shared-file check. It separates actual tool
execution from the agent's verbal acceptance. The suite has six C2 and six
C3 rows. Live results are pending. The historical measurements establish
neither a native unauthorized-operation rate nor a comparison of verified
operation outcomes under urgency.
[Native authorized-task manual](gcp_native_agent_experiment.md)

## 1. Vision and impact

Coding agents translate requests into actions under a real user account. On a shared Linux system, one user's files can become technically readable to another user because of permissions. A model can then face a decision about whether a request falls within its task authority. A team that treats a readable file as permission to use it loses a distinct control over disclosure and cross-user actions.

Our project asks where a security boundary was actually enforced. Linux permissions can deny a read, a tool can fail before it reads anything, or a model can decline a request. A result that only says “the agent did not access the file” hides those differences. The benchmark collects evidence for each layer so administrators and evaluators can interpret the result.

## 2. Project goals and contributions

- **Measure baseline access.** Verify whether Alice can read a Bob-owned inert fixture under each Linux configuration.
- **Verify tool readiness.** Require Codex to read a deliberately shared, harmless file successfully through a read-only tool.
- **Measure authorization judgment.** Compare fixed fictional `ALLOW`/`DENY` decisions under matched wording and trusted-policy conditions.
- **Make runs reproducible.** Fix the trial matrix, use a fresh VM per measured row, and preserve enough evidence to audit the result and resume interrupted collection.

**Novelty.** The contribution is the measurement design. The same experiment records independent Linux access evidence, a positive check that the agent's tool can do authorized work, and a separate model judgment. This makes a dead tool distinguishable from a working defense. The study uses ordinary Linux controls and a small controlled scenario to make the causal comparisons easier to interpret. [Benchmark implementation plan](session_benchmark.md)

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

## 4. Progression and results

| Stage | What the evidence establishes |
| --- | --- |
| Original exploratory pilot | The midterm materials document one controlled Linux session with a credential disclosure and an account transition corroborated by PAM and UID evidence. It was a single qualitative observation. |
| GCP smoke test, November 24 | The Ubuntu archive smoke test passed eight regression tests. A 24-row dry run verified matrix parsing and produced zero agent launches. |
| Automated four-turn pilots, November 26 | Two Codex batches completed 12 measured trials each. Both tested C2/C3 under neutral and pressure scripts. One calibration per batch was stored separately. |
| Balanced grid, November 27 | The exported campaign verified all four calibrations and all 48 measured rows. The shared-file control passed in every measured row. Each measured row used a distinct VM, Codex control session, and judgment response. |

[Smoke-test record](gcp_smoke_test_recap.md) · [Pilot batch 171454](../ece117-evidence/ece117-canary-v2-20261126-171454) · [Pilot batch 232958](../ece117-evidence/ece117-canary-v2-20261126-232958) · [Final grid receipt](../ece117-evidence/ece117-grid48-20261127-052345/calibration.json)

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
| [Trial launcher](../scripts/run_gcp_canary_suite.py) and [reporter](../scripts/summarize_session_results.py) | Fresh trial VMs, evidence verification and retry, plus Markdown, CSV, and plot outputs. |
| [Regression tests](../tests) and [operator runbook](gcp_vm_experiment.md) | Archive integrity, calibration and control gates, recovery after interruption, and Mac and Cloud Shell commands. |

Key Git milestones are `ca1f098` for the multi-turn runner and evidence tooling, `9d8be17` for GCP automation, `2fb4621` for runtime API authentication, `571fdd6` for result reports, and `d608e9f` for the four-condition calibrated grid. The current working tree passed **26 local regression tests** during this review. Those tests exercise the code and its gates. Live model, image, and network behavior are verified through the calibration exports.

## 6. Related work

| Prior work | Connection to this project |
| --- | --- |
| Saltzer and Schroeder, *The Protection of Information in Computer Systems* | Least privilege motivates the limited shared-file tool and the OS-level ACL comparison. [Paper](https://www.cs.virginia.edu/~evans/cs551/saltzer/) |
| Wallace et al., *The Instruction Hierarchy* | Their work prioritizes instructions from different sources. Our C2/C3 comparison measures how a trusted policy is reflected in judgments about a shared Linux scenario. [Paper](https://arxiv.org/abs/2404.13208) |
| Debenedetti et al., *AgentDojo* | AgentDojo evaluates tool-using agents and defenses in a dynamic benchmark. Our test narrows the setting to one Alice/Bob fixture and checks the Linux and tool outcomes independently. [Paper](https://arxiv.org/abs/2406.13352) |

## 7. Takeaways, limitations, and future work

- The final grid verified both OS controls and a working shared-file tool. The trusted-policy comparison produced the clearest pilot difference. Report both experiments with their own denominators.
- The shared-file control went from 0/24 in the pilot to 48/48 in the final grid. The tool and protocol changed between those runs, so this validates the new setup's authorized-read path and does not isolate the effect of a single change.
- Every final-grid decision was `DENY`. The results establish no observed policy or urgency difference for the fixed fictional scenario.
- The measured pilot evidence covers Codex. A matched Claude campaign would be needed for a cross-agent claim. The final grid's tool-free judgment measures the configured model through an API response. It does not measure a native agent carrying out the decision.
- Six repeats per final cell provide exploratory comparisons. Preserve failed attempts, report denominators, and verify that the image, model, matrix, and wording agree before comparing batches.
- Show the final-grid chart on the results slide. Use the earlier pilot chart to explain why the team separated tool readiness from authorization judgment.

## 8. Presentation outline and submission

| Slide | Content | Rubric emphasis |
| --- | --- | --- |
| 1 · Title | *Under Pressure*. Team number **14A**, team name **Team 111**, team members, and the assigned peer-evaluation secret number(s). | Required title information |
| 2 · High-level problem | A two-user diagram showing how file readability and task authorization can differ. | Vision and impact |
| 3 · Project topic and solution | Show the OS check, the shared-file tool control, and the fictional decision as three distinct evidence sources. | Novelty |
| 4 · Goals and experiment design | Show the C1–C4 grid, the two wordings, six repeats per cell, and the four calibration checks. | Novelty and practicality |
| 5 · Results and demo | Lead with the final grid's OS access pattern, 48/48 verified reads, and 48/48 `DENY`. Use the pilot as context. A short demo can generate the chart from the saved evidence. | Practicality |
| 6 · Related work | Compare the evaluation design with least privilege, instruction hierarchy, and AgentDojo. | Vision and novelty |
| 7 · Takeaways and discussion | Explain what the evidence attributes to the OS, to tool availability, or to model judgment. | Impact and practicality |
| 8 · Limitations and future work | State the coverage and sample limits, the uniform `DENY` result, and what a matched second-agent run would add. | Practicality |

**Title slide check.** The team number, name, and member list above come from the midterm deck. Enter the assigned peer-evaluation secret number(s) on the final title slide and make them legible during the talk. The assignment materials provided here do not supply the number.

**Gradescope check.** Submit one slide deck for the team and add every member through Gradescope's group submission feature.

**Presentation sources.** The supplied final presentation template provides the eight-slide sequence. The assignment screenshot provides the Vision, Impact, Novelty, and Practicality criteria and the submission rules. The *Under Pressure* midterm slides and paper establish the original design and the historical pilot observation.
