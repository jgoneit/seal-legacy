# Codex credential boundary

Language: English | [한국어](credential-boundary.ko.md)

## Purpose

Harness does not control how a coding Agent works. When Codex's permission-profile
path is active, credential confidentiality is therefore enforced outside Harness
Core through the repository's profile in `.codex/config.toml`.

The profile extends Codex's built-in `:workspace` permissions. It preserves normal
workspace inspection, editing, and command execution while denying reads and writes
for a narrow set of credential-bearing paths. It does not add lifecycle hooks,
command parsing, approval state, or a Harness runtime state machine.

## Default-denied material

The workspace rules deny:

- `.env`, `.env.*`, and `.envrc` beneath configured workspace roots, subject to
  the portable scan-depth limit below;
- private-key files ending in `.key`;
- common credential JSON filenames such as `key.json`, `credentials.json`, and
  service-account variants; and
- common SSH private-key filenames.

The profile also denies exact user-level credential locations for Codex, SSH, AWS,
Azure, Google Cloud, GitHub CLI, Docker, Kubernetes, npm, PyPI, Git, and netrc.
Directories and files outside those entries retain the built-in `:workspace`
behavior.

On Linux, WSL, and native Windows, Codex may pre-expand unbounded `**` deny globs
before starting the sandbox. This profile keeps `glob_scan_max_depth = 8` to bound
that startup work. The portable guarantee for workspace-relative globs therefore
stops at the configured scan depth on those platforms; files nested more deeply are
outside this repository policy's guarantee.

The exact `.env.example` name is excluded from the deny patterns so an Agent can
inspect the documented variable contract without seeing runtime values. Codex
permission profiles intentionally allow only `deny` access for filesystem globs, so
the profile expresses the exception with negative character classes instead of a
weaker read hook. Example files must contain placeholder values only; the exception
cannot make an accidentally committed secret safe.

## Process environment

Codex's default case-insensitive environment filtering for names containing
`KEY`, `SECRET`, or `TOKEN` stays enabled. The project adds filters for names
containing `CREDENTIAL`, `PASSWORD`, or `PASSWD`. Other environment variables are
still inherited so ordinary build and test discovery remains available.

This policy applies to subprocesses launched by Codex. Harness still records check
stdout and stderr verbatim, so checks must not print secret values obtained from an
external source.

## Activation and override boundary

Permission profiles do not compose with legacy sandbox settings. If any loaded
configuration contains `sandbox_mode`, the CLI receives `--sandbox`, or the selected
configuration profile sets `sandbox_mode`, Codex uses the legacy sandbox and ignores
`default_permissions`. Remove `sandbox_mode` and `[sandbox_workspace_write]` before
relying on this boundary. Managed deployments should use
`allowed_permission_profiles` with a managed `default_permissions` value and remove
the legacy settings rather than adding a repository runtime guard.

Project-scoped `.codex/config.toml` is loaded only for a trusted project and takes
effect when a new Codex session resolves its configuration. It does not retroactively
change the permissions of an already-running session.

The profile is a safe default, not an administrator-enforced immutable policy. A
user can deliberately select a different permission profile or approve an
out-of-sandbox command when access is genuinely required. Such an override should
identify the exact file and purpose; broad permanent exceptions defeat this
boundary.

Codex permission profiles require Codex 0.138.0 or later and are currently beta.
Older clients must be upgraded rather than relying on a partial hook-based fallback.

## Verification

The repository test suite validates the checked-in profile contract. When a
compatible `codex` executable is available, it also runs a local sandbox smoke test
with synthetic values to confirm that `.env`, representative `.env.*` variants,
`.envrc`, and `key.json` cannot be read while the exact `.env.example` name remains
readable at the root and within the configured scan depth. The smoke test selects the
profile explicitly, so it validates the profile definition rather than proving that
every user's default session selected it.
