"""Contract coverage for the Seal Legacy Plugin skills."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPOSITORY_ROOT / "skills"
PLUGIN_MANIFEST = REPOSITORY_ROOT / ".codex-plugin" / "plugin.json"
ADAPTER_CONTRACT = REPOSITORY_ROOT / "docs" / "adapter-contract.md"
UI_SMOKE = REPOSITORY_ROOT / "docs" / "seal-legacy-ui-smoke.md"
TASK_SCHEMA = REPOSITORY_ROOT / "schemas" / "task.schema.json"
README = REPOSITORY_ROOT / "README.md"
KOREAN_README = REPOSITORY_ROOT / "README.ko.md"
EXPECTED_SKILLS = ("seal-legacy", "task", "verify", "bundle", "complete")


def _skill_text(name: str) -> str:
    return (SKILLS_ROOT / name / "SKILL.md").read_text(encoding="utf-8")


def _agent_metadata(name: str) -> str:
    return (SKILLS_ROOT / name / "agents" / "openai.yaml").read_text(
        encoding="utf-8"
    )


def _frontmatter_field(contents: str, field: str) -> str | None:
    _, separator, remainder = contents.partition("---\n")
    if not separator:
        return None
    frontmatter, separator, _ = remainder.partition("\n---\n")
    if not separator:
        return None
    match = re.search(rf"(?m)^{re.escape(field)}:\s*([^\n]+)$", frontmatter)
    return None if match is None else match.group(1).strip().strip('"\'')


def _frontmatter_name(contents: str) -> str | None:
    return _frontmatter_field(contents, "name")


def _normalized(contents: str) -> str:
    return " ".join(contents.split())


class PluginSkillContractTests(unittest.TestCase):
    def test_expected_skills_are_namespaced_and_resume_only_when_intended(self) -> None:
        for name in EXPECTED_SKILLS:
            with self.subTest(skill=name):
                skill_path = SKILLS_ROOT / name / "SKILL.md"
                metadata_path = SKILLS_ROOT / name / "agents" / "openai.yaml"
                self.assertTrue(skill_path.is_file())
                self.assertTrue(metadata_path.is_file())

                self.assertEqual(_frontmatter_name(_skill_text(name)), name)
                metadata = _agent_metadata(name)
                expected_policy = "true" if name == "seal-legacy" else "false"
                self.assertIn(
                    f"policy:\n  allow_implicit_invocation: {expected_policy}",
                    metadata,
                )
                invocation = "$seal-legacy" if name == "seal-legacy" else f"$seal-legacy:{name}"
                self.assertIn(invocation, metadata)

        self.assertIn(
            "unambiguous confirmation or resume reply in the same conversation",
            _normalized(_skill_text("seal-legacy")),
        )
        managed = _normalized(_skill_text("seal-legacy"))
        self.assertIn(
            "Start the managed workflow only when `$seal-legacy` or an explicitly selected `@Seal Legacy` Plugin is paired with an executable end-to-end coding outcome",
            managed,
        )
        self.assertIn(
            "The invocation form never overrides that outcome requirement",
            managed,
        )
        self.assertIn("Plugin selection alone", managed)
        self.assertIn(
            "discussion, explanation, planning, audit, review, or status requests do not activate Core",
            managed,
        )
        self.assertIn("ordinary unselected coding request", managed)
        self.assertIn("Within an activation case above", managed)
        self.assertIn(
            "use the carried identity for a bundle, separately prepared Verdict, or completion",
            managed,
        )

        for name in EXPECTED_SKILLS[1:]:
            with self.subTest(explicit_follow_up=name):
                contents = _normalized(_skill_text(name))
                self.assertIn(
                    f"Ask the user to invoke `$seal-legacy:{name}` again",
                    contents,
                )
                self.assertIn(
                    "do not rely on an untagged reply",
                    contents,
                )

    def test_managed_skill_defines_one_approved_initial_verification(self) -> None:
        contents = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "`$seal-legacy`",
            "explicitly selected `@Seal Legacy` Plugin",
            "one conversational confirmation",
            "Task creation, ordinary implementation, the first `verify` exactly once, and one `run show` exactly once",
            "first `verify` exactly once",
            "one `run show` exactly once for the exact Run identity returned by that successful `verify`",
            "No additional question is allowed between successful `verify` and that `run show`",
            "exactly one local bundle export",
            "if and only if the adopted saved Task has `verifier.required=true`",
            "fresh absolute output directory outside the target repository",
            "does not authorize `complete`",
            "restate that adopting it covers ordinary implementation, the first `verify` exactly once, and one `run show` exactly once",
            "same conversation",
            "successful `task create` stdout `id`",
            "successful `verify` stdout to be one JSON object with exactly `run_id` and `evidence_path`",
            "Do not select a latest Task or Run",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

    def test_task_drafts_use_the_public_task_type_enum(self) -> None:
        schema = json.loads(TASK_SCHEMA.read_text(encoding="utf-8"))
        task_types = schema["properties"]["type"]["enum"]
        self.assertIsInstance(task_types, list)
        self.assertGreater(len(task_types), 1)
        self.assertIn("docs", task_types)

        documents = {
            "managed skill": _normalized(_skill_text("seal-legacy")),
            "task skill": _normalized(_skill_text("task")),
            "adapter contract": _normalized(
                ADAPTER_CONTRACT.read_text(encoding="utf-8")
            ),
        }
        for document_name, contents in documents.items():
            with self.subTest(document=document_name):
                enum_guidance = re.search(
                    r"Set `type` to exactly one public Task Schema value: "
                    r"(?P<types>.*?)\. Use `docs`",
                    contents,
                )
                self.assertIsNotNone(enum_guidance)
                assert enum_guidance is not None
                documented_types = re.findall(
                    r"`([^`]+)`",
                    enum_guidance.group("types"),
                )
                self.assertEqual(set(documented_types), set(task_types))
                self.assertEqual(len(documented_types), len(task_types))
                self.assertIn(
                    "Use `docs` when the outcome changes documentation only.",
                    contents,
                )
                self.assertIn(
                    "Do not invent another label such as `implementation`, "
                    "`maintenance`, or `chore`.",
                    contents,
                )
                self.assertIn(
                    "This draft guidance does not replace Core validation.",
                    contents,
                )

    def test_managed_skill_preserves_failure_and_review_boundaries(self) -> None:
        contents = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "blocked or aborted",
            (
                "do not repair source, replace Evidence, create a replacement Run, "
                "retry verification"
            ),
            "nonzero `verify`",
            "Any nonzero Core command",
            "Do not consume partial stdout",
            "alternate output path",
            "outside the target repository",
            "Do not read `<evidence_path>/verification.json`",
            "choose the next branch only from the adopted saved Task's `verifier.required` field",
            "Do not interpret raw Evidence",
            "Failure stage` to `run show`",
            "bundle, Verdict operations, and `complete` as not run",
            "implementation conversation",
            "clean-context",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

    def test_verify_results_adopt_only_the_exact_validated_run_summary(self) -> None:
        for name in ("seal-legacy", "verify"):
            with self.subTest(skill=name):
                contents = _normalized(_skill_text(name))
                self.assertIn(
                    "Do not read `<evidence_path>/verification.json`",
                    contents,
                )
                self.assertIn(
                    "Public `verify` stdout does not expose an integrity-validated mechanical summary",
                    contents,
                )
                self.assertIn(
                    "exactly `run_id` and `evidence_path`",
                    contents,
                )
                self.assertIn(
                    "seal-legacy run show <TASK_ID> --run-id <RUN_ID>",
                    contents,
                )
                self.assertIn("validated-run-summary/v1", contents)
                self.assertIn("Missing or unknown keys", contents)
                self.assertIn("identity mismatch", contents)
                self.assertIn("wrong type", contents)
                self.assertIn("JSON object key ordering", contents)
                self.assertIn("adapter contract failure", contents)
                self.assertIn("fall back to raw Evidence", contents)

        managed = _normalized(_skill_text("seal-legacy"))
        verify_position = managed.index("seal-legacy verify <TASK_ID>")
        run_show_position = managed.index(
            "seal-legacy run show <TASK_ID> --run-id <RUN_ID>"
        )
        self.assertLess(verify_position, run_show_position)

        expected_top_level = (
            "`checks`",
            "`evidence_sha256`",
            "`mechanical_result`",
            "`required_checks_pass`",
            "`run_id`",
            "`schema_version`",
            "`scope_pass`",
            "`scope_violations`",
            "`source_stable_during_checks`",
            "`task_id`",
        )
        summary_section = managed[
            managed.index("Require exactly these top-level keys") :
            managed.index("After a valid summary")
        ]
        for key in expected_top_level:
            with self.subTest(top_level_key=key):
                self.assertIn(key, summary_section)
        for nested_key in (
            "`exit_code`",
            "`name`",
            "`passed`",
            "`required`",
            "`timed_out`",
            "`path`",
            "`previous_path`",
            "`source`",
            "`status`",
        ):
            with self.subTest(nested_key=nested_key):
                self.assertIn(nested_key, summary_section)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn(
            "A direct artifact read is not a Core-validated Run result",
            contract,
        )
        self.assertIn(
            "must not drive lifecycle decisions or completion claims",
            contract,
        )

    def test_managed_profile_handoff_preserves_final_confirmation(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "When `verifier.required=false`, do not create a bundle",
            "continue immediately to the final completion confirmation",
            "When `verifier.required=true`, create exactly one approved local bundle",
            "required check failure, timeout, Scope violation, or source instability",
            "still have `run show` exit 0",
            "neither raw Evidence nor any summary result changes the profile route",
            "including when the valid stored mechanical state is failed",
            "Pause for a separately prepared Verdict",
            "Never run `complete` without the separate final confirmation",
            "Bundle success does not mean a mechanical pass or completion eligibility",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, managed)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("adopted saved Task's `verifier.required` profile", contract)
        self.assertIn("basic profile proceeds directly to final confirmation", contract)
        self.assertIn("reviewed profile exports exactly one approved local bundle", contract)

    def test_managed_skill_leads_with_compact_user_facing_status(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "## User-facing presentation",
            "Mode: Analysis only",
            "Mode: Managed execution",
            "Status: Core unavailable",
            "Included in this confirmation",
            "Not included in this confirmation",
            "Local records",
            "Status: Evidence recorded",
            "must not be described as verification passed",
            "Core validated stored Run integrity and serialized the summary",
            "stored mechanical state",
            "Neither successful command nor that stored state means completion acceptance or completion eligibility",
            "presentation only and are not persisted lifecycle state",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, managed)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        for fragment in (
            "compact presentation summary",
            "Included in this confirmation",
            "Not included in this confirmation",
            "Evidence recorded",
            "not persisted adapter state",
        ):
            with self.subTest(contract_fragment=fragment):
                self.assertIn(fragment, contract)

        display_section = managed[
            managed.index("After a valid summary, compactly show") :
            managed.index("A valid summary may contain")
        ]
        for field in (
            "canonical repository",
            "exact Task ID",
            "exact Run ID",
            "opaque Evidence path",
            "`evidence_sha256`",
            "`mechanical_result`",
            "`scope_pass`",
            "Scope violation",
            "`required_checks_pass`",
            "`source_stable_during_checks`",
            "`required`",
            "`passed`",
            "`timed_out`",
            "`exit_code`",
        ):
            with self.subTest(display_field=field):
                self.assertIn(field, display_section)
        for forbidden_claim in (
            "`verification passed`",
            "`Task completed`",
            "`completion eligible`",
        ):
            with self.subTest(forbidden_claim=forbidden_claim):
                self.assertIn(forbidden_claim, display_section)

        public_labels = (
            "Mode: Analysis only",
            "Status: Core unavailable",
            "Status: Evidence recorded",
            "Status: Seal Legacy stopped",
            "Status: Review handoff ready",
            "Included in this confirmation",
            "Not included in this confirmation",
            "Local records",
        )
        for document in (README, KOREAN_README):
            contents = _normalized(document.read_text(encoding="utf-8"))
            for label in public_labels:
                with self.subTest(document=document.name, public_label=label):
                    self.assertIn(label, contents)

    def test_analysis_and_core_unavailable_responses_have_exact_leads(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        start = managed.index("## User-facing presentation")
        end = managed.index("## Core boundary and preflight", start)
        presentation = managed[start:end]

        required_fragments = (
            (
                "the first user-visible content, including any commentary or "
                "progress update, must begin exactly `Mode: Analysis only`"
            ),
            "Do not emit a Skill-use announcement, preamble, or tool-progress message before that label",
            (
                "the Core-unavailable response must begin exactly "
                "`Status: Core unavailable`"
            ),
            (
                "Do not put `Mode: Managed execution`, a preamble, or another "
                "status ahead of it"
            ),
            "the exact `seal-legacy --version` command, stdout, stderr, and numeric exit code",
            "Quote the original managed request verbatim in the repeat guidance",
            "`Original request to repeat (verbatim):`",
            "Do not replace it with `the same request` or a generic paraphrase",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, presentation)

    def test_analysis_only_lead_is_front_loaded_before_skill_body_reads(self) -> None:
        description = _frontmatter_field(_skill_text("seal-legacy"), "description")
        self.assertIsNotNone(description)
        assert description is not None
        description = _normalized(description)

        self.assertTrue(
            description.startswith(
                "For an explicitly selected `@Seal Legacy` discussion"
            )
        )
        required_fragments = (
            "the first user-visible content must begin exactly `Mode: Analysis only`",
            "use that same label as the Skill-use announcement",
            "state that Core was not started",
            "no file-read or tool-progress commentary before it",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, description)

        self.assertLess(
            description.index("`Mode: Analysis only`"),
            description.index("Manage Seal Legacy end-to-end"),
        )

    def test_core_unavailable_lead_is_front_loaded_before_skill_body_reads(self) -> None:
        description = _frontmatter_field(_skill_text("seal-legacy"), "description")
        self.assertIsNotNone(description)
        assert description is not None
        description = _normalized(description)

        required_fragments = (
            "run `seal-legacy --version` preflight before any user-visible content or Skill-use announcement",
            "missing, unparseable, or unsupported",
            "first user-visible content must begin exactly `Status: Core unavailable`",
            "use that status as the Skill-use announcement",
            "do not emit `Mode: Managed execution`, a preamble, or tool-progress commentary before it",
            "Only after the preflight succeeds with a supported version may managed output begin with `Mode: Managed execution`",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, description)

        self.assertLess(
            description.index("`Mode: Analysis only`"),
            description.index("`seal-legacy --version`"),
        )
        self.assertLess(
            description.index("`seal-legacy --version`"),
            description.index("`Status: Core unavailable`"),
        )
        self.assertLess(
            description.index("`Status: Core unavailable`"),
            description.index("`Mode: Managed execution`"),
        )

    def test_first_adoption_presentation_has_one_explicit_block_order(self) -> None:
        contents = _skill_text("seal-legacy")
        start = contents.index("For every first-adoption response")
        end = contents.index("The three approval", start)
        section = _normalized(contents[start:end])
        ordered_fragments = (
            "`Mode: Managed execution`",
            "a compact summary containing",
            "existing working-tree state",
            "staged, unstaged, and untracked",
            "`Included in this confirmation`",
            "`Not included in this confirmation`",
            "`Local records`",
            "`Task draft:`",
            "catalog-derived check preview",
            "one adoption question",
        )
        positions = [section.index(fragment) for fragment in ordered_fragments]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Do not interleave them", section)
        self.assertIn(
            "The Task JSON and check preview must not appear before the "
            "dirty-tree disclosure or any of the three approval-boundary labels.",
            section,
        )

    def test_managed_failures_and_review_handoffs_include_resume_capsules(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "## Report failures and handoffs",
            "Status: Seal Legacy stopped",
            "Failure stage",
            "Preserved identity",
            "Not run",
            "Next explicit request",
            "Resume capsule",
            "Awaiting a separately prepared Verdict",
            "exact resume request",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, managed)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn("failure or handoff capsule", contract)
        self.assertIn("must not imply that a retry is authorized", contract)

    def test_managed_identity_is_bound_to_the_original_repository_root(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "canonical repository root",
            "Bind the exact Task ID",
            "Bind the returned Run ID and opaque Evidence path to that same root",
            "resolve the selected repository root again",
            "differs from the retained root",
            "require the successful `verify` identity to equal the retained Task ID plus the returned Run ID",
            "seal-legacy run show <TASK_ID> --run-id <RUN_ID>",
            "Do not reuse or search for those IDs in another repository",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, managed)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn(
            "canonical repository root, Task ID, and, when available, Run ID",
            contract,
        )
        self.assertIn("IDs alone are not portable across repositories", contract)

        self.assertIn(
            "original canonical repository root",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "최초 canonical repository root",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )

    def test_bundle_escape_hatch_defaults_an_omitted_output_path(self) -> None:
        bundle = _normalized(_skill_text("bundle"))
        required_fragments = (
            "If the exact Task ID, Run ID, or target repository is missing",
            "An omitted output path is not missing input",
            "choose a unique absolute output path outside the confirmed target repository",
            "final directory does not already exist",
            "pass it through Core's required `--output` argument",
            "do not replace the supplied path silently",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, bundle)
        self.assertNotIn("required path decision is missing", bundle)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn(
            "When an adapter-level bundle request omits an output path",
            contract,
        )
        self.assertIn("Core's required `--output` argument", contract)

    def test_bundle_success_is_not_reported_as_mechanical_pass(self) -> None:
        for name in ("seal-legacy", "bundle"):
            with self.subTest(skill=name):
                contents = _normalized(_skill_text(name))
                self.assertIn("bundle success does not mean", contents.lower())
                self.assertIn("mechanical pass", contents)
                self.assertIn("completion eligibility", contents)

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn(
            "does not establish mechanical pass or completion eligibility",
            contract,
        )

    def test_completion_prompt_does_not_infer_recorded_verdict_state(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        self.assertIn("saved Task's `verifier.required` setting", managed)
        self.assertIn(
            "Do not inspect or claim a recorded Verdict state unless the user separately requested `verifier show`",
            managed,
        )

        contract = _normalized(ADAPTER_CONTRACT.read_text(encoding="utf-8"))
        self.assertIn(
            "must not claim a recorded Verdict state without a separately requested `verifier show`",
            contract,
        )

    def test_managed_completion_preserves_the_raw_core_process_result(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        start = managed.index("## Ask for final completion confirmation")
        end = managed.index("## Explicit single-operation mode", start)
        completion = managed[start:end]

        required_fragments = (
            "after any required compact failure summary",
            "Core stdout (verbatim)",
            "complete captured stdout exactly as emitted",
            "Do not replace it with parsed fields",
            "Core stderr (verbatim)",
            "Core exit code: <INTEGER>",
            "If either stream is empty, label that stream `(empty)`",
            "both exit zero and nonzero results",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, completion)

        ordered_fragments = (
            "required compact failure summary",
            "Core stdout (verbatim)",
            "Core stderr (verbatim)",
            "Core exit code: <INTEGER>",
            "completion accepted or completion refused",
        )
        positions = [completion.index(fragment) for fragment in ordered_fragments]
        self.assertEqual(positions, sorted(positions))

    def test_task_drafts_do_not_invent_optional_check_timeouts(self) -> None:
        for name in ("seal-legacy", "task"):
            with self.subTest(skill=name):
                contents = _normalized(_skill_text(name))
                self.assertIn("catalog-derived check preview", contents)
                self.assertIn(
                    "authoritative normalized checks from successful `task create` stdout",
                    contents,
                )
                self.assertIn("`timeout_seconds` when present", contents)
                self.assertIn("do not infer a numeric default", contents)

    def test_verdict_input_does_not_mutate_verified_product_source(self) -> None:
        contents = _normalized(_skill_text("seal-legacy"))
        self.assertIn("Verdict input outside the target repository", contents)
        self.assertIn("inline Verdict JSON", contents)
        self.assertIn("Do not move or delete a repository-local Verdict", contents)
        for document in (README, KOREAN_README):
            with self.subTest(document=document.name):
                self.assertIn(
                    "<VERDICT_JSON_OUTSIDE_REPOSITORY>",
                    document.read_text(encoding="utf-8"),
                )

    def test_managed_creation_reconciles_the_approved_preview(self) -> None:
        contents = _normalized(_skill_text("seal-legacy"))
        required_fragments = (
            "saved baseline differs from the displayed HEAD",
            "saved Task fields differ from the approved draft",
            "saved checks differ from the approved preview",
            "Preserve the created Task",
            "stop before implementation or verification",
            "new explicit adoption confirmation",
            "drift re-adoption or new-Task choice",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, contents)

        self.assertIn(
            "saved Task fields, baseline, or checks",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "saved Task field, baseline, check",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )

    def test_post_adoption_head_drift_is_reconciled_after_task_create(self) -> None:
        managed = _normalized(_skill_text("seal-legacy"))
        start = managed.index("## Create and carry the Task identity")
        end = managed.index("## Let the coding Agent implement", start)
        creation = managed[start:end]

        required_fragments = (
            "Do not compare the current HEAD with the displayed HEAD before Task creation",
            (
                "If HEAD changed after adoption but the canonical repository is "
                "unchanged and a current HEAD exists, run `seal-legacy task create` "
                "exactly once"
            ),
            (
                "Treat the saved baseline from successful `task create` stdout "
                "as the only post-adoption drift decision point"
            ),
            "Preserve the created Task",
            "stop before implementation or verification",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, creation)

        ordered_fragments = (
            "run `seal-legacy task create` exactly once",
            "saved baseline from successful `task create` stdout",
            "compare the saved baseline with the displayed HEAD",
        )
        positions = [creation.index(fragment) for fragment in ordered_fragments]
        self.assertEqual(positions, sorted(positions))

    def test_readmes_separate_core_and_plugin_installation(self) -> None:
        expected = (
            (README, "does not install the Codex Plugin"),
            (KOREAN_README, "Codex Plugin을 설치하지 않습니다"),
        )
        for document, boundary in expected:
            with self.subTest(document=document.name):
                contents = document.read_text(encoding="utf-8")
                self.assertIn("### Codex Plugin", contents)
                self.assertIn("codex plugin add seal-legacy@personal", contents)
                self.assertIn(boundary, contents)

    def test_escape_hatches_name_only_their_core_operation(self) -> None:
        expected_commands = {
            "task": (
                "seal-legacy task create --file <TASK_JSON>",
                "seal-legacy task show <TASK_ID>",
            ),
            "verify": (
                "seal-legacy verify <TASK_ID>",
                "seal-legacy run show <TASK_ID> --run-id <RUN_ID>",
            ),
            "bundle": (
                "seal-legacy verifier bundle <TASK_ID> --run-id <RUN_ID> --output <OUTPUT_DIR>",
            ),
            "complete": ("seal-legacy complete <TASK_ID> --run-id <RUN_ID>",),
        }
        for name, commands in expected_commands.items():
            with self.subTest(skill=name):
                contents = _skill_text(name)
                if name == "verify":
                    self.assertIn(
                        "Perform only the requested bounded Core sequence",
                        _normalized(contents),
                    )
                    self.assertIn(
                        "Report the exact Evidence identity and validated stored state, or the exact failure, and stop",
                        _normalized(contents),
                    )
                    metadata = _normalized(_agent_metadata(name))
                    self.assertIn("<TASK_ID>", metadata)
                    self.assertIn("exact Run", metadata)
                    self.assertIn("Core-validated", metadata)
                else:
                    self.assertIn("Perform only the requested Core operation", contents)
                for command in commands:
                    self.assertIn(command, contents)

    def test_plugin_listing_leads_with_the_managed_workflow(self) -> None:
        manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
        interface = manifest["interface"]

        self.assertEqual(manifest["name"], "seal-legacy")
        self.assertEqual(manifest["version"], "0.3.0-dev.0")
        self.assertEqual(interface["displayName"], "Seal Legacy")
        self.assertEqual(
            interface["shortDescription"],
            "Evidence-backed completion for coding agents",
        )
        self.assertEqual(manifest["homepage"], "https://github.com/jgoneit/seal-legacy")
        self.assertEqual(manifest["repository"], "https://github.com/jgoneit/seal-legacy")
        self.assertEqual(interface["websiteURL"], "https://github.com/jgoneit/seal-legacy")
        self.assertIn("managed", manifest["description"].lower())
        self.assertIn("managed", interface["longDescription"].lower())
        self.assertIn("core-validated stored run state", interface["longDescription"].lower())
        prompts = interface["defaultPrompt"]
        self.assertLessEqual(len(prompts), 3)
        self.assertTrue(any(prompt.startswith("$seal-legacy ") for prompt in prompts))
        self.assertTrue(any(not prompt.startswith("$seal-legacy") for prompt in prompts))
        verify_prompts = [
            prompt for prompt in prompts if prompt.startswith("$seal-legacy:verify ")
        ]
        self.assertEqual(len(verify_prompts), 1)
        self.assertIn("<TASK_ID>", verify_prompts[0])
        self.assertIn("exact Run", verify_prompts[0])
        self.assertIn("Core-validated", verify_prompts[0])

    def test_current_plugin_surfaces_use_only_the_seal_identity(self) -> None:
        current_surfaces = (
            PLUGIN_MANIFEST,
            README,
            KOREAN_README,
            ADAPTER_CONTRACT,
            UI_SMOKE,
            *(SKILLS_ROOT / name / "SKILL.md" for name in EXPECTED_SKILLS),
            *(
                SKILLS_ROOT / name / "agents" / "openai.yaml"
                for name in EXPECTED_SKILLS
            ),
        )
        forbidden = (
            "$harness",
            "@Harness",
            "harness@personal",
            "plugin://harness@personal",
            "Status: Harness stopped",
            "github.com/jgoneit/harness",
        )
        for surface in current_surfaces:
            contents = surface.read_text(encoding="utf-8")
            for phrase in forbidden:
                with self.subTest(
                    surface=surface.relative_to(REPOSITORY_ROOT),
                    phrase=phrase,
                ):
                    self.assertNotIn(phrase, contents)

        managed = _normalized(_skill_text("seal-legacy"))
        self.assertIn(
            "Seal Legacy Plugin → public `seal-legacy` subprocess CLI → Seal Legacy Core (Python)",
            managed,
        )
        for document in (README, KOREAN_README):
            contents = _normalized(document.read_text(encoding="utf-8"))
            self.assertIn(
                "Seal Legacy Plugin → public seal-legacy subprocess CLI → Seal Legacy Core (Python)",
                contents,
            )
            for non_claim in (
                "signature",
                "remote attestation",
                "tamper-proof",
                "non-repudiation",
                "external trust anchor",
            ):
                self.assertIn(non_claim, contents)

    def test_public_docs_separate_core_and_plugin_workflows(self) -> None:
        expected = (
            (README, "## Core CLI workflow", "## Seal Legacy Plugin managed workflow"),
            (
                KOREAN_README,
                "## Core CLI workflow",
                "## Seal Legacy Plugin 관리형 workflow",
            ),
        )
        for document, core_heading, plugin_heading in expected:
            with self.subTest(document=document.name):
                contents = document.read_text(encoding="utf-8")
                self.assertIn(core_heading, contents)
                self.assertIn(plugin_heading, contents)
                for invocation in (
                    "$seal-legacy:task",
                    "$seal-legacy:verify",
                    "$seal-legacy:bundle",
                    "$seal-legacy:complete",
                ):
                    self.assertIn(invocation, contents)

        self.assertIn(
            "## Managed adapter lifecycle",
            ADAPTER_CONTRACT.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "the user's affirmative reply to the displayed covered actions",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "화면에 표시한 범위에 대한 사용자의 명확한 승인 답변",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "selected `@Seal Legacy` Plugin",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "Both entry forms require an executable coding outcome",
            _normalized(README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "선택한 `@Seal Legacy` Plugin",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )
        self.assertIn(
            "두 진입 방식 모두 실행 가능한 coding outcome이 있어야 합니다",
            _normalized(KOREAN_README.read_text(encoding="utf-8")),
        )

    def test_ui_smoke_contract_covers_selected_plugin_routing_and_handoffs(self) -> None:
        self.assertTrue(UI_SMOKE.is_file())
        contents = UI_SMOKE.read_text(encoding="utf-8")
        normalized = _normalized(contents)
        required_fragments = (
            "Repository tests do not prove selected-plugin routing",
            "fresh Codex task",
            "not evidence of selected-plugin routing",
            "UI-01 Discussion-only selected Plugin",
            "UI-02 Managed request with Core unavailable",
            "UI-03 Basic profile happy path",
            "UI-04 Reviewed profile handoff",
            "UI-05 Dirty working tree disclosure",
            "UI-06 Task adoption baseline drift",
            "UI-07 Nonzero Core stop",
            "UI-08 Final completion confirmation",
            "UI-09 Ordinary unselected coding stays inactive",
            "UI-10 Valid required-check failure",
            "UI-11 Valid required-check timeout",
            "UI-12 Corrupt or unsafe Evidence fail-stop",
            "UI-13 Explicit `$seal-legacy:verify` bounded sequence",
            "Observed result",
            "Pass criteria",
            "pass, fail, blocked, or not run",
            "canonical protocol intentionally contains no claimed Observed result",
            "Do not mark a scenario passed without fresh UI execution",
            "does not install Core",
            "no bundle is created",
            "does not run a reviewer",
            "regular-file setup is not removed or repaired",
            "does not run before a separate unambiguous final confirmation",
            "Any `fail`, `blocked`, or `not run` result keeps that current-source acceptance gate open",
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, normalized)

        for operational_record in (
            "PR2 implementation record",
            "Post-merge fresh-task record",
            "019fffba-0513-7fc1-bfa7-87387c170af8",
            "UI-01 was run and recorded",
        ):
            with self.subTest(operational_record=operational_record):
                self.assertNotIn(operational_record, contents)

        scenario_ids = re.findall(r"(?m)^## (UI-\d{2}) ", contents)
        self.assertEqual(
            scenario_ids,
            [f"UI-{index:02d}" for index in range(1, 14)],
        )

        def scenario(heading: str) -> str:
            match = re.search(
                rf"(?ms)^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
                contents,
            )
            self.assertIsNotNone(match, heading)
            assert match is not None
            return _normalized(match.group("body"))

        discussion = scenario("UI-01 Discussion-only selected Plugin")
        self.assertIn("exact label `Mode: Analysis only`", discussion)
        self.assertIn("first user-visible content, including commentary", discussion)
        self.assertIn("no preamble appears before it", discussion)
        self.assertNotIn("equivalent unambiguous", discussion)

        unavailable = scenario("UI-02 Managed request with Core unavailable")
        self.assertIn("shared fixture and exact Basic prompt", unavailable)
        self.assertIn("`Status: Core unavailable`", unavailable)
        self.assertIn("not `Mode: Managed execution`", unavailable)
        self.assertIn("actual failed preflight", unavailable)
        self.assertIn("Core CLI installation guidance", unavailable)
        self.assertIn("`Original request to repeat (verbatim):`", unavailable)
        self.assertIn("does not install Core", unavailable)

        basic = scenario("UI-03 Basic profile happy path")
        self.assertIn("`Included in this confirmation`", basic)
        self.assertIn("exactly one `verify`", basic)
        self.assertIn("exactly one `seal-legacy run show", basic)
        self.assertIn("for its returned exact identity", basic)
        self.assertIn("`Status: Evidence recorded`", basic)
        self.assertIn("raw `verification.json`", basic)
        self.assertIn("no bundle is created", basic)

        reviewed = scenario("UI-04 Reviewed profile handoff")
        self.assertIn("one conditional local bundle", reviewed)
        self.assertIn(
            "exactly one `verify`, its one exact `run show`, and one fresh external bundle export occur in that order",
            reviewed,
        )
        self.assertIn("without reading raw `verification.json`", reviewed)
        self.assertIn("`Status: Review handoff ready`", reviewed)
        self.assertIn("does not run a reviewer", reviewed)

        dirty = scenario("UI-05 Dirty working tree disclosure")
        self.assertIn(
            "follows the Skill's exact first-adoption block order",
            dirty,
        )
        self.assertIn("staged, unstaged, and untracked", dirty)
        self.assertIn("Stop at the first adoption prompt", dirty)
        self.assertIn(
            "appear after the dirty-tree disclosure and before the full Task "
            "JSON and check preview",
            dirty,
        )
        self.assertIn("no existing change is stashed, reset, committed, deleted", dirty)

        drift = scenario("UI-06 Task adoption baseline drift")
        self.assertIn("create an empty commit", drift)
        self.assertIn("the created Task is preserved", drift)
        self.assertIn("exact saved baseline versus displayed HEAD difference", drift)
        self.assertIn("implementation and verification do not start", drift)
        self.assertIn("exact saved Task or a new Task choice", drift)

        nonzero = scenario("UI-07 Nonzero Core stop")
        self.assertIn("shared Basic prompt", nonzero)
        self.assertIn("supported managed end-to-end activation", nonzero)
        self.assertIn("successful `task create` stdout", nonzero)
        self.assertIn("exactly one covered `verify`", nonzero)
        self.assertIn("regular-file setup is not removed or repaired", nonzero)

        completion = scenario("UI-08 Final completion confirmation")
        self.assertIn("exact validated Run Summary query", completion)
        self.assertIn("exact `complete` command", completion)
        self.assertIn("does not run before a separate unambiguous final confirmation", completion)
        self.assertIn("reports the exact Core stdout, stderr, and exit code", completion)
        self.assertIn("accepted or refused by Core", completion)

        ordinary = scenario("UI-09 Ordinary unselected coding stays inactive")
        self.assertIn("without selecting `@Seal Legacy` or any Seal Legacy Skill", ordinary)
        self.assertIn(
            'Append the exact line "Ordinary coding smoke fixture" to README.md only.',
            ordinary,
        )
        self.assertIn("tests routing rather than missing setup", ordinary)
        self.assertIn("no Seal Legacy mode or status summary appears", ordinary)
        self.assertIn("including `Mode: Analysis only`", ordinary)
        self.assertIn("no Seal Legacy-specific lifecycle language", ordinary)
        self.assertIn("no Seal Legacy Core (Python) command runs", ordinary)

        failed_check = scenario("UI-10 Valid required-check failure")
        self.assertIn("exactly one `verify`", failed_check)
        self.assertIn("exactly one `run show`", failed_check)
        self.assertIn("`mechanical_result=fail`", failed_check)
        self.assertIn("`required_checks_pass=false`", failed_check)
        self.assertIn("`timed_out=false`", failed_check)
        self.assertIn("`exit_code=17`", failed_check)
        self.assertIn("raw `verification.json` is not read", failed_check)
        self.assertIn("saved Basic profile alone", failed_check)

        timeout = scenario("UI-11 Valid required-check timeout")
        self.assertIn("exactly one `verify`", timeout)
        self.assertIn("exactly one matching `run show`", timeout)
        self.assertIn("`timed_out=true`", timeout)
        self.assertIn("raw `verification.json` is not read", timeout)
        self.assertIn("saved Basic profile alone", timeout)

        corrupt = scenario("UI-12 Corrupt or unsafe Evidence fail-stop")
        self.assertIn("variant A corrupts", corrupt)
        self.assertIn("variant B replaces", corrupt)
        self.assertIn("Core returns exit 8", corrupt)
        self.assertIn("`Status: Seal Legacy stopped`", corrupt)
        self.assertIn("`run show` as the failure stage", corrupt)
        self.assertIn("no raw-Evidence fallback", corrupt)
        self.assertIn("replacement Run", corrupt)

        verify_escape = scenario("UI-13 Explicit `$seal-legacy:verify` bounded sequence")
        self.assertIn("exact `task show`", verify_escape)
        self.assertIn("exactly one `verify`", verify_escape)
        self.assertIn("exactly one `run show`", verify_escape)
        self.assertIn("without reading raw `verification.json`", verify_escape)
        self.assertIn("stops after `run show`", verify_escape)
        self.assertIn("does not create a bundle", verify_escape)

        release = scenario("Current-source interpretation")
        self.assertIn("All thirteen required scenarios", release)
        self.assertIn("fresh Observed result of `pass`", release)
        self.assertIn("current Seal Legacy selected-Plugin", release)
        self.assertIn("historical `v0.2.1` release evidence", release)
        self.assertNotIn("creating the `v0.2.1` release tag", release)

        self.assertIn("Seal Legacy Codex UI smoke", README.read_text(encoding="utf-8"))
        self.assertIn("Seal Legacy Codex UI smoke", KOREAN_README.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
