"""Package version tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness import __version__


class VersionTests(unittest.TestCase):
    """Verify that the package exposes a version."""

    def test_core_version_opens_v0_3_development_line(self) -> None:
        self.assertEqual(__version__, "0.3.0.dev0")
