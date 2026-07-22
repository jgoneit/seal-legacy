# ADR 0000: Outcome Over Process (historical)

Language: English | [한국어](0000-outcome-over-process.ko.md)

Status: Superseded
Date: 2026-07-16

> Historical design note: this document records an earlier direction and does
> not describe the current shipped contract. In particular, its references to
> cross-vendor execution, runs.jsonl, trust summaries, and alternative Verdict
> states are not implemented. See the README, architecture document, and
> ADR 0001 for the current supported surface.

## Context

The previous Harness consisted of approximately 3,100 lines of Python guard code and approximately 1,850 lines of tests. Approval tokens, Plan hashes, exact `y` responses, attestation, root-only writes, and the `PreToolUse` hook were not arbitrary additions. They became necessary because determining, before each action, whether every Agent action matched the approved plan and current runtime state required each mechanism to understand the others' state, exceptions, and recovery paths. For a single turn to pass, the input format, approval history, hash, write boundary, roles, and hook delivery path all had to remain consistent.

The problem was not merely that the implementation had become complex. Process gates conflict with every model turn. As a task grows longer and the number of turns increases, normal exploration, explanation, tool calls, edits, and re-review encounter the gate more often. The cost of friction and false blocks therefore accumulates in proportion to the amount of work. More capable models become better at understanding intent, following plans, and using tools, which depreciates the value of gates based on past behavior patterns. Conversely, a gate state mismatch or an installation or hook-path problem stops work regardless of the model's actual work quality.

Outcome verification has the opposite characteristics. Instead of examining the internal order in which an Agent reasoned and used tools, it asks whether, when completion is claimed, evidence exists that satisfies the Task Spec's scope and definition of done. Verification cost attaches to the completion claim and its evidence bundle rather than to every turn. As models and verifiers improve, they can produce better evidence and challenge it more effectively, so this control benefits from model improvements instead of competing with them.

## Decision

Move the control instead of removing it. Harness does not block actions. An Agent may choose and carry out its own way of working. However, it may claim completion only for results verified against the scope, definition of done, evidence, and independent review. The control shifts from blocking actions to blocking completion.

The only fail-closed rule retained is: **an unverified result is not complete.** If required evidence is missing, the connection between the evidence and Task Spec cannot be reviewed, or independent review has not been performed, record the result as `unverified`, `inconclusive`, or `failed`, rather than `complete`. This rule does not prohibit the Agent's next action, but it prevents unsupported success claims from accumulating as successes.

Scope remains the boundary that defines what must be verified. The definition of done remains the set of observable conditions by which success can be judged. Evidence remains the source material and provenance supporting those conditions, such as command output, diffs, test results, and review records. Independent review remains the procedure for challenging the executor's evidence and conclusion from a separate perspective. These four elements are necessary for a completion decision, but they do not mandate a particular runtime, number of roles, subordinate Agent arrangement, or approval phrase.

Accordingly, runtime gates, approval state machines, Plan hash authority, hook-based enforcement, mandatory topology, and worktree orchestration are removed from the new Harness conceptual model. Approval tokens and state transitions do not prove authority to act, and hooks do not intercept normal work. Independent review remains, but it is not implemented through a specific subagent topology or root-only writer rule.

### Cross-vendor verification

Cross-vendor verification is both a hypothesis under evaluation and the default configuration. By default, the intent is to reduce correlated errors by choosing a verifier from a vendor different from the executing Agent's vendor, but it is not an established fact that this is already more accurate or independent. The current W1 observation is one true positive and zero false positives in a sample of one. This is an observation from a single case and does not establish accuracy, generalizability, or vendor independence.

Verification records must retain the verifier's vendor and execution method. When another vendor is unavailable, a review performed by the same vendor or by a person must not be hidden or labeled as cross-vendor. That distinction itself becomes data for evaluating the hypothesis later.

### Run records and trust summaries

`runs.jsonl` is the source of truth. Each run is appended to the log with its Task Spec, evidence, verifier provenance, verdict, and any later correction or supersession. A trust summary is a derived view recomputed from those records; it must be possible to regenerate it while preserving the source material even if the formula or sample range changes.

Do not create a directly editable `trust.json`. If a person can edit a summary file to revise an explanation or change the current trust level, that file becomes a second source of truth that mixes observations with judgments. Record a correction as a new entry in `runs.jsonl` together with its basis, and let the summary reflect the result.

### Task Spec authorship

The Task Spec is authored by the person who requests the work and is accountable for its result. The requester writes or explicitly adopts the purpose, scope, and definition of done. The executing Agent may structure them or propose a draft, but it cannot unilaterally create the criteria used to judge its own completion. Otherwise, the executor could create both an easier spec and evidence that satisfies it, undermining the independence of outcome verification.

This decision does not restore the previous exact-`y` approval or Plan hash authority. Authoring or adopting a Task Spec is not a runtime gate that authorizes actions; it clarifies the provenance of the input used later to evaluate a completion claim. Without an adequate Task Spec, an Agent may still work, but it cannot make a precise completion claim.

## Consequences

The new design substantially reduces process-control code, state recovery, hook compatibility concerns, and the test surface tied to installation paths and topology. An Agent no longer needs to reproduce a protocol on every turn to perform normal work, and failures appear as insufficient evidence at completion rather than as authorization errors before an action. Even as models and tools change, the core contract therefore remains focused on "what counts as complete" and "what supports that conclusion."

Preventive controls become weaker in exchange. A runtime gate no longer blocks out-of-scope actions, dangerous tool use, or late-discovered errors in interpreting requirements in advance. A weak or ambiguous Task Spec also makes post-hoc verification ambiguous, and evidence may be presented selectively or a verifier may share the same error. If verification fails just before completion, some work already performed may be wasted. These risks are managed by making clear that Harness does not replace external controls such as security, permissions, and sandboxes, and by retaining evidence provenance and independent review.

Trust data must not automatically determine policy at an early stage either. If, with few samples, a trust summary decides policies such as skipping verifiers, reducing review rigor, or expanding Agent autonomy, observational noise determines autonomy. W1's one true positive and zero false positives may be a promising starting point, but they are not a policy threshold. Until there is a sufficient sample size, a distribution across task types, false-positive and false-negative analysis, and a separate calibration decision, use the trust summary only as an explanatory derived view and do not relax fail-closed completion.

This ADR does not claim that outcome verification catches every kind of failure. Instead, it chooses the cost of requiring falsifiable evidence for completion claims and improving verification from those records over the cost of predicting and controlling how an Agent works.
