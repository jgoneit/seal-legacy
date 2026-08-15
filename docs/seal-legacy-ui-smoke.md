# Seal Legacy Codex UI smoke

This document defines the manual smoke protocol for the Seal Legacy Plugin.
Repository tests do not prove selected-plugin routing, prompt presentation, or
conversation carry-forward in the Codex app. Do not mark a scenario passed
without fresh UI execution and recorded observations.

## Test boundary

- Run each scenario in a fresh Codex task so no conversational Task or Run
  identity can leak from another scenario.
- Select the installed `@Seal Legacy` Plugin through the Codex UI for every
  selected-plugin scenario. A literal `$seal-legacy` prompt is a different routing
  path and is not substitute evidence. A copied `plugin://seal-legacy@personal`
  link or `codex exec` prompt is not evidence of selected-plugin routing.
- Use disposable Git repositories with a current HEAD and an explicit
  `.seal/checks.json`. Never use production repositories or secrets.
- Record the Codex app build, installed Plugin manifest version, Core version or
  intentional absence, canonical repository root, HEAD, prompt, response,
  commands observed, exit codes, and post-scenario `git status`.
- Store screenshots or exported transcripts outside the target repository.
  Check logs and bundles may contain sensitive values and must be inspected
  before sharing.
- If a required environment cannot be prepared, record the scenario as blocked
  with the reason. Do not simulate a pass.

## Shared disposable fixture

Create a new repository containing `README.md` and this check catalog, then
commit both files before opening the fresh Codex task:

```json
{
  "schema_version": 1,
  "checks": [
    {
      "name": "readme-line",
      "argv": [
        "python3",
        "-c",
        "from pathlib import Path; assert Path('README.md').read_text(encoding='utf-8').endswith('Seal Legacy UI smoke fixture\\n')"
      ],
      "required": true,
      "timeout_seconds": 30
    }
  ]
}
```

After selecting `@Seal Legacy`, copy one of these prompts exactly:

- Basic: `Append the exact line "Seal Legacy UI smoke fixture" to README.md only.
  Use Scope ["README.md"], the readme-line check, risk low, and the Basic
  profile with verifier.required=false, then verify it.`
- Reviewed: `Append the exact line "Seal Legacy UI smoke fixture" to README.md
  only. Use Scope ["README.md"], the readme-line check, risk low, and the
  Reviewed profile with verifier.required=true, then verify it.`
- Discussion: `Explain the Seal Legacy UX advantages, disadvantages, and an
  improvement plan only. Do not implement anything.`

The adoption draft must retain type `docs`, Scope `["README.md"]`, the named
check, the requested risk, and the requested profile. If it does not, record the
scenario as failed or exercise the documented draft-revision path; do not
silently approve a different Task.

Use this result shape in the release or audit record:

| Field | Recorded value |
| --- | --- |
| Scenario | `UI-01` through `UI-13` |
| Fresh Codex task | task identifier or timestamp |
| Environment | app build, Plugin version, Core version, repository, HEAD |
| Observed result | pass, fail, blocked, or not run |
| Evidence | screenshot or transcript location and relevant command results |
| Notes | deviations, contamination, or remaining risk |

The canonical protocol intentionally contains no claimed Observed result.

## UI-01 Discussion-only selected Plugin

Use the shared Discussion prompt.

Pass criteria:

- the first user-visible content, including commentary, leads with the exact
  label `Mode: Analysis only` and no preamble appears before it;
- no Seal Legacy Core (Python) command runs and no Task, Run, bundle, or Verdict is created;
- the response answers the discussion request without asking for Task adoption.

## UI-02 Managed request with Core unavailable

Use the shared fixture and exact Basic prompt in a test environment where the
Plugin is installed but `seal-legacy --version` is intentionally unavailable.

If the Codex app environment cannot safely exclude Core without changing the
host installation, record this scenario as blocked instead of simulating the
failure.

Pass criteria:

- the Core-unavailable response leads with the exact label `Status: Core
  unavailable`, not `Mode: Managed execution`, and reports the actual failed
  preflight plus the Core/Plugin installation boundary;
- it points to the Core CLI installation guidance and renders the exact Basic
  prompt after `Original request to repeat (verbatim):` as the request to
  repeat after Core is available;
- it does not install Core, modify product source, or claim a Task or Run.

## UI-03 Basic profile happy path

Use the shared fixture and Basic prompt. Approve the displayed Task once.

Pass criteria:

- the adoption response shows the compact summary, `Included in this
  confirmation`, `Not included in this confirmation`, and `Local records`
  before the full Task JSON and check preview;
- Task creation, ordinary implementation, and exactly one `verify` occur;
- the successful `verify` is followed by exactly one `seal-legacy run show
  <TASK_ID> --run-id <RUN_ID>` for its returned exact identity, with no question
  between them;
- the result is labeled `Status: Evidence recorded`, not verification passed,
  and compactly displays the canonical repository, Task/Run/Evidence identity,
  Evidence SHA-256, mechanical, Scope, required-check, source-stability,
  violation, and per-check state from the valid summary;
- no direct read or interpretation of raw `verification.json` occurs;
- no bundle is created and `complete` waits for a separate final confirmation.

## UI-04 Reviewed profile handoff

Use the shared fixture and Reviewed prompt. Approve the displayed Task once.

Pass criteria:

- the initial approval explicitly includes one conditional local bundle;
- exactly one `verify`, its one exact `run show`, and one fresh external bundle
  export occur in that order;
- the validated stored state is displayed without reading raw
  `verification.json` before bundle export;
- the response reports `Status: Review handoff ready` with repository, Task,
  Run, Evidence, bundle, profile, and exact resume request;
- it states that it is awaiting a separately prepared Verdict and does not run
  a reviewer, record a Verdict, share the bundle, or invoke `complete`.

## UI-05 Dirty working tree disclosure

Prepare staged, unstaged, and untracked files in the shared disposable
repository, then submit the Basic prompt. Stop at the first adoption prompt.

Pass criteria:

- the response follows the Skill's exact first-adoption block order: `Mode`
  and `Status`, compact summary including the dirty categories, `Included in
  this confirmation`, `Not included in this confirmation`, `Local records`,
  full Task JSON, check preview, then one adoption question;
- the compact summary names the dirty categories and the exact Task baseline as
  current HEAD;
- `Included in this confirmation`, `Not included in this confirmation`, and
  `Local records` appear after the dirty-tree disclosure and before the full
  Task JSON and check preview;
- the full draft and check preview remain available after the summary;
- no existing change is stashed, reset, committed, deleted, or silently added
  to Scope.

## UI-06 Task adoption baseline drift

In a disposable repository, record the HEAD shown with the Task draft. Before
approving Task creation, use a separate terminal to create an empty commit, then
approve the original draft. This intentionally makes Core save a different
baseline from the one displayed for adoption.

Pass criteria:

- the created Task is preserved;
- the response shows the exact saved baseline versus displayed HEAD difference;
- implementation and verification do not start;
- the response requests adoption of the exact saved Task or a new Task choice.

## UI-07 Nonzero Core stop

In a clean shared fixture, make `.seal/evidence` a regular file before any
Task or Evidence exists so a Run directory cannot be created. Start a fresh
Codex task, select `@Seal Legacy`, submit the shared Basic prompt, and approve the
displayed Task once. This keeps the scenario inside the supported managed
end-to-end activation while forcing the covered first `verify` to fail.

Pass criteria:

- Task creation succeeds once, `README.md` is changed once, and exactly one
  covered `verify` runs without another adoption;
- the nonzero `verify` produces `Status: Seal Legacy stopped` with the failure
  stage, exact command and exit code, canonical repository and Task ID retained
  from successful `task create` stdout, and later operations not run;
- Run ID and Evidence path are reported as not created rather than inferred
  from a partial directory or stdout;
- the regular-file setup is not removed or repaired, and no retry, replacement
  Evidence, replacement Run, or rollback occurs;
- bundle and `complete` are not run;
- the next explicit request does not imply that retry is already authorized.
- a required check failure that `verify` records with exit zero is not treated
  as equivalent evidence for this scenario.

## UI-08 Final completion confirmation

Start a fresh Codex task, execute a new passing basic-profile flow through
Evidence recording and the exact validated Run Summary query, and then continue
in that same conversation to observe the final confirmation boundary.

Pass criteria:

- the response shows the canonical repository, exact Task ID, exact Run ID,
  validated stored state, saved profile, and exact `complete` command;
- `complete` does not run before a separate unambiguous final confirmation;
- after confirmation, the response reports the exact Core stdout, stderr, and
  exit code and describes completion only as accepted or refused by Core.

## UI-09 Ordinary unselected coding stays inactive

Start a fresh Codex task in a clean shared fixture without selecting
`@Seal Legacy` or any Seal Legacy Skill. Do not include `$seal-legacy`, a Plugin link, or Seal Legacy
lifecycle terms in the request. Keep the compatible Core and check
catalog available so this tests routing rather than missing setup. Submit
exactly:

```text
Append the exact line "Ordinary coding smoke fixture" to README.md only.
```

Pass criteria:

- the captured submission state shows that no Seal Legacy Plugin or Skill was
  selected;
- the request is handled as ordinary coding and only `README.md` changes;
- no Seal Legacy mode or status summary appears, including `Mode: Analysis only`,
  `Mode: Managed execution`, or any Seal Legacy `Status:` label; no Seal Legacy-specific
  lifecycle language, Core preflight, Task draft, or adoption prompt appears,
  and no Seal Legacy Core (Python) command runs; and
- no Task, Run, Evidence, bundle, Verdict, or completion artifact is created.

## UI-10 Valid required-check failure

Create a fresh disposable repository like the shared fixture, but define the
selected required check to exit 17 after printing a fixture marker. Use a Basic
profile Task whose Scope contains only the intended product file, then approve
the managed request once.

Pass criteria:

- exactly one `verify` records the failed check and returns exit 0, followed by
  exactly one `run show` for that returned Run with exit 0;
- the compact stored state reports `mechanical_result=fail`,
  `required_checks_pass=false`, and the exact required check with
  `passed=false`, `timed_out=false`, and `exit_code=17`;
- the failed stored state is not treated as a command failure and raw
  `verification.json` is not read;
- the saved Basic profile alone selects the separate completion-confirmation
  path, but `complete` does not run before that confirmation.

## UI-11 Valid required-check timeout

Create a fresh disposable repository whose required check sleeps longer than
its one-second `timeout_seconds`. Use a Basic profile and approve once.

Pass criteria:

- exactly one `verify` records the timeout and returns exit 0, followed by
  exactly one matching `run show` with exit 0;
- the compact stored state preserves the exact required check with
  `passed=false` and `timed_out=true` rather than collapsing it into a generic
  command error;
- raw `verification.json` is not read, the saved Basic profile alone selects
  the completion-confirmation path, and `complete` is not run.

## UI-12 Corrupt or unsafe Evidence fail-stop

Run two fresh disposable variants. Use an external test-only `seal-legacy` wrapper
outside the target repository that delegates every command to the exact Core
CLI. Immediately before delegating the first `run show`, variant A corrupts the
returned Run's `verification.json`; variant B replaces the returned Run
directory with an unsafe symlink. The wrapper is fault injection only: record
its absolute path and contents, and do not install it as product code.

Pass criteria for each variant:

- Task creation and exactly one `verify` succeed, then the Plugin invokes the
  exact returned identity's `run show` exactly once;
- Core returns exit 8 with empty success stdout and the real stderr diagnostic;
- the response leads with `Status: Seal Legacy stopped`, identifies `run show` as the
  failure stage, and reports the exact command, stdout, stderr, and exit code;
- only the canonical repository and Task/Run/Evidence identity returned before
  failure are preserved;
- no raw-Evidence fallback, retry, repair, replacement Run, bundle, Verdict
  operation, or `complete` occurs.

## UI-13 Explicit `$seal-legacy:verify` bounded sequence

Create an exact saved Basic Task in a fresh disposable repository with Core,
then make the in-Scope product change without creating a Run. Start a fresh
Codex task and invoke `$seal-legacy:verify` with the canonical repository and exact
Task ID.

Pass criteria:

- existing preflight and exact `task show` occur, followed by exactly one
  `verify` and exactly one `run show` for the returned exact Run, in that order;
- the response reports the Evidence identity and complete compact validated
  stored state without reading raw `verification.json`;
- the sequence stops after `run show`: it does not create a bundle, invoke or
  record a reviewer/Verdict, request or run `complete`, repair, retry, or create
  a replacement Run.

## Current-source interpretation

All thirteen required scenarios must each record a fresh Observed result of `pass`
before claiming that the current Seal Legacy selected-Plugin and ordinary-unselected
routing contract passed. Any `fail`, `blocked`, or `not run` result keeps that
current-source acceptance gate open. Static contract tests, literal `$seal-legacy`
execution, package smoke tests, historical `v0.2.1` release evidence, or a
previously observed Codex task are useful supporting evidence but do not
replace this UI smoke.
