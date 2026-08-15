from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CODEX_CONFIG = REPOSITORY_ROOT / ".codex" / "config.toml"
PROFILE_NAME = "seal-legacy-credential-safe"
READ_TEXT_SCRIPT = (
    "from pathlib import Path; import sys; "
    "sys.stdout.write(Path(sys.argv[1]).read_text(encoding='utf-8'))"
)


def _load_config() -> dict[str, object]:
    with CODEX_CONFIG.open("rb") as config_file:
        return tomllib.load(config_file)


class CodexCredentialProfileContractTest(unittest.TestCase):
    def test_profile_extends_workspace_without_hooks(self) -> None:
        config = _load_config()
        self.assertEqual(config["default_permissions"], PROFILE_NAME)

        profile = config["permissions"][PROFILE_NAME]
        self.assertEqual(profile["extends"], ":workspace")
        self.assertNotIn("hooks", config)
        self.assertNotIn("sandbox_mode", config)
        self.assertNotIn("sandbox_workspace_write", config)
        self.assertEqual(profile["filesystem"]["glob_scan_max_depth"], 8)

    def test_workspace_credential_paths_are_denied_with_example_exception(self) -> None:
        config = _load_config()
        workspace_rules = config["permissions"][PROFILE_NAME]["filesystem"][
            ":workspace_roots"
        ]

        expected_denied = {
            "**/.env",
            "**/.envrc",
            "**/.env.e",
            "**/.env.ex",
            "**/.env.exa",
            "**/.env.exam",
            "**/.env.examp",
            "**/.env.exampl",
            "**/.env.[!e]*",
            "**/.env.e[!x]*",
            "**/.env.ex[!a]*",
            "**/.env.exa[!m]*",
            "**/.env.exam[!p]*",
            "**/.env.examp[!l]*",
            "**/.env.exampl[!e]*",
            "**/.env.example?*",
            "**/*.key",
            "**/credentials.json",
            "**/id_ed25519",
            "**/id_rsa",
            "**/key.json",
            "**/service-account.json",
            "**/service_account.json",
        }
        self.assertEqual(
            {path for path, access in workspace_rules.items() if access == "deny"},
            expected_denied,
        )
        self.assertNotIn("**/.env.example", workspace_rules)

    def test_user_credential_locations_are_exact_denies(self) -> None:
        config = _load_config()
        filesystem = config["permissions"][PROFILE_NAME]["filesystem"]

        expected_denied = {
            "~/.aws/cli/cache",
            "~/.aws/credentials",
            "~/.aws/sso/cache",
            "~/.azure",
            "~/.codex/auth.json",
            "~/.config/gcloud/application_default_credentials.json",
            "~/.config/gcloud/credentials.db",
            "~/.config/gh/hosts.yml",
            "~/.docker/config.json",
            "~/.git-credentials",
            "~/.kube/config",
            "~/.netrc",
            "~/.npmrc",
            "~/.pypirc",
            "~/.ssh",
        }
        self.assertEqual(
            {path for path, access in filesystem.items() if access == "deny"},
            expected_denied,
        )

    def test_shell_environment_keeps_default_filters_and_adds_password_filters(self) -> None:
        config = _load_config()
        environment = config["shell_environment_policy"]

        self.assertEqual(environment["inherit"], "all")
        self.assertIs(environment["ignore_default_excludes"], False)
        self.assertEqual(
            set(environment["exclude"]),
            {"*CREDENTIAL*", "*PASSWORD*", "*PASSWD*"},
        )


@unittest.skipUnless(shutil.which("codex"), "Codex CLI is unavailable")
class CodexCredentialProfileSandboxTest(unittest.TestCase):
    def test_sandbox_denies_credentials_and_allows_env_example(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix="credential-boundary-", dir=REPOSITORY_ROOT
        ) as temporary_directory:
            fixture_root = Path(temporary_directory)
            example_sentinel = "synthetic-.env.example"
            example = fixture_root / ".env.example"
            example.write_text(example_sentinel, encoding="utf-8")
            control = self._sandbox_read(example)
            if "sandbox_apply: Operation not permitted" in control.stderr:
                self.skipTest("the current process cannot start a nested macOS sandbox")
            self.assertEqual(control.returncode, 0, control.stderr)
            self.assertEqual(control.stdout, example_sentinel)

            nested_example = fixture_root / "nested" / "project" / ".env.example"
            nested_example.parent.mkdir(parents=True)
            nested_example.write_text(example_sentinel, encoding="utf-8")
            nested_control = self._sandbox_read(nested_example)
            self.assertEqual(nested_control.returncode, 0, nested_control.stderr)
            self.assertEqual(nested_control.stdout, example_sentinel)

            denied_names = (
                ".env",
                ".envrc",
                ".env.e",
                ".env.ex",
                ".env.exa",
                ".env.exam",
                ".env.examp",
                ".env.exampl",
                ".env.local",
                ".env.evil",
                ".env.exbmple",
                ".env.exanple",
                ".env.examqle",
                ".env.exampme",
                ".env.examplf",
                ".env.example.local",
                ".env.production",
                "key.json",
                "private.key",
                "nested/project/.env",
                "nested/project/.envrc",
                "nested/project/key.json",
            )

            for name in denied_names:
                with self.subTest(path=name):
                    sentinel = f"synthetic-{name}"
                    fixture = fixture_root / name
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    fixture.write_text(sentinel, encoding="utf-8")
                    result = self._sandbox_read(fixture)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(sentinel, result.stdout)

    def _sandbox_read(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "codex",
                "sandbox",
                "--permission-profile",
                PROFILE_NAME,
                "--cd",
                str(REPOSITORY_ROOT),
                "--",
                sys.executable,
                "-c",
                READ_TEXT_SCRIPT,
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
