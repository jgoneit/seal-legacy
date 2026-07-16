"""Package version tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness import __version__


class VersionTests(unittest.TestCase):
    """Verify that the package exposes a version."""

    def test_version_exists(self) -> None:
        self.assertIsInstance(__version__, str)
        self.assertTrue(__version__)
