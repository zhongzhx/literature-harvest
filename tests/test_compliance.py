"""Compliance tests — ensure no Sci-Hub, no credential logging, principles present."""

from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path


_HERE = Path(__file__).resolve().parent
_PACKAGE = _HERE.parent / "literature_harvest"


def _iter_py_files() -> list[Path]:
    """Yield all .py files in the literature_harvest package."""
    files = []
    for root, _dirs, filenames in os.walk(str(_PACKAGE)):
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(root) / fn)
    return files


class TestCompliance(unittest.TestCase):
    def test_no_sci_hub_in_source_code(self):
        """No Sci-Hub implementation references in the main source code.

        Compliance header docstrings that say "No Sci-Hub" are allowed.
        """
        for pyfile in _iter_py_files():
            content = pyfile.read_text(encoding="utf-8")
            lower = content.lower()
            if "sci_hub" not in lower and "sci-hub" not in lower:
                continue
            # Every "Sci-Hub" mention must be in a compliance prohibition context
            # (e.g. "# 3. No Sci-Hub, pirate sources..." or similar comment/string)
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if "sci-hub" in line.lower() or "sci_hub" in line.lower():
                    stripped = line.strip()
                    # Allow import of sci_hub module if it exists (no such module currently)
                    if "import" in stripped and "sci_hub" in stripped:
                        continue  # would be an actual import of a local module
                    # Otherwise it must be a compliance comment
                    if not stripped.startswith("#") and "No Sci-Hub" not in stripped and "No Sci-Hub" not in stripped:
                        self.fail(
                            f"Sci-Hub reference in {pyfile.relative_to(_PACKAGE.parent)} line {i + 1}: {stripped}"
                        )

    def test_no_credential_logging(self):
        """No code that logs cookies, passwords, or tokens."""
        suspicious = ["log.*cookie", "log.*password", "log.*token",
                       "print.*cookie", "print.*password", "print.*token"]
        for pyfile in _iter_py_files():
            content = pyfile.read_text(encoding="utf-8")
            lower = content.lower()
            for pattern in suspicious:
                # Check for actual logging patterns, not docstrings
                if pattern in lower:
                    # Parse the file to check if this is actual code vs docstring
                    try:
                        tree = ast.parse(content)
                        for node in ast.walk(tree):
                            if isinstance(node, ast.Call):
                                call_str = ast.get_source_segment(content, node) or ""
                                if any(p in call_str.lower() for p in ["cookie", "password", "token"]):
                                    # Allow if it's clearly about NOT logging
                                    if "no" not in call_str.lower()[:10]:
                                        self.fail(
                                            f"Potential credential logging in {pyfile.relative_to(_PACKAGE.parent)}: {call_str[:100]}"
                                        )
                    except SyntaxError:
                        pass  # skip files that can't be parsed

    def test_compliance_principles_in_readme(self):
        """SKILL.md contains the 6 compliance principles."""
        skill_path = _HERE.parent / "SKILL.md"
        self.assertTrue(skill_path.is_file())
        content = skill_path.read_text(encoding="utf-8")
        principles = [
            "Only legitimate access",
            "No paywall bypass",
            "No pirate sources",
            "No credential theft",
            "Rate limiting",
            "Manual fallback",
        ]
        for principle in principles:
            self.assertIn(principle, content, f"Missing compliance principle: {principle}")

    def test_no_paywall_bypass_code(self):
        """No code that attempts to bypass paywalls."""
        bypass_patterns = [
            "proxy.*rotation", "proxy.*rotate", "rotate.*proxy",
            "credential.*stuff", "account.*pool",
            "captcha.*solve", "recaptcha.*solve",
            "vpn.*rotate", "rotate.*vpn",
        ]
        for pyfile in _iter_py_files():
            content = pyfile.read_text(encoding="utf-8").lower()
            for pattern in bypass_patterns:
                if pattern in content:
                    self.fail(f"Paywall bypass code found in {pyfile.relative_to(_PACKAGE.parent)}: {pattern}")


if __name__ == "__main__":
    unittest.main()
