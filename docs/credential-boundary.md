# Codex credential boundary

Language: English | [한국어](credential-boundary.ko.md)

## Purpose

Harness does not control how a coding Agent works. Credential confidentiality is
therefore enforced outside Harness Core through the repository's Codex permission
profile in `.codex/config.toml`.

The profile extends Codex's built-in `:workspace` permissions. It preserves normal
workspace inspection, editing, and command execution while denying reads and writes
for a narrow set of credential-bearing paths. It does not add lifecycle hooks,
command parsing, approval state, or a Harness runtime state machine.

## Default-denied material

The workspace rules deny:

- `.env` and `.env.*` at any configured workspace depth;
- private-key files ending in `.key`;
- common credential JSON filenames such as `key.json`, `credentials.json`, and
  service-account variants; and
- common SSH private-key filenames.

The profile also denies exact user-level credential locations for Codex, SSH, AWS,
Azure, Google Cloud, GitHub CLI, Docker, Kubernetes, npm, PyPI, Git, and netrc.
Directories and files outside those entries retain the built-in `:workspace`
behavior.

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
with synthetic values to confirm that `.env`, representative `.env.*` variants, and
`key.json` cannot be read while the exact `.env.example` name remains readable.
