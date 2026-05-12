"""Tests for the DownloadSession wrapper.

These tests verify the internal logic (PDF magic bytes, content classification,
paywall detection, file operations) without making network requests.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    from literature_harvest.download_session import DownloadSession
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipIf(not HAS_DEPS, "requires requests / literature_harvest.download_session")
class TestDownloadSession(unittest.TestCase):
    def setUp(self):
        self.session = DownloadSession(timeout=5)
        # Use a mock session that doesn't make network calls
        import unittest.mock
        self.session.session = unittest.mock.MagicMock()

    def test_check_pdf_magic_valid(self):
        """A file starting with %PDF is recognised as a valid PDF."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\nsome content here\n")
            path = f.name
        try:
            self.assertTrue(self.session.check_pdf_magic(path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_check_pdf_magic_invalid(self):
        """A file without %PDF header is rejected."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"<html>not a pdf</html>")
            path = f.name
        try:
            self.assertFalse(self.session.check_pdf_magic(path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_check_pdf_magic_empty(self):
        """A file smaller than 8 bytes is rejected."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"short")
            path = f.name
        try:
            self.assertFalse(self.session.check_pdf_magic(path))
        finally:
            Path(path).unlink(missing_ok=True)

    def test_classify_payload_pdf_by_magic(self):
        """Payload starting with %PDF is classified as pdf."""
        self.assertEqual(self.session.classify_payload(b"%PDF-1.4...", "application/octet-stream"), "pdf")

    def test_classify_payload_pdf_by_content_type(self):
        """Content-Type containing pdf is classified as pdf."""
        self.assertEqual(self.session.classify_payload(b"some data", "application/pdf"), "pdf")

    def test_classify_payload_html(self):
        """HTML content is classified as html."""
        self.assertEqual(self.session.classify_payload(b"<html><body>text</body></html>", "text/html"), "html")

    def test_classify_payload_xml(self):
        """XML content is classified as xml."""
        self.assertEqual(self.session.classify_payload(b"<?xml version='1.0'?><root/>", "application/xml"), "xml")

    def test_looks_paywalled(self):
        """Paywall markers are detected in text."""
        self.assertTrue(self.session.looks_paywalled("This article requires a subscription to view"))
        self.assertTrue(self.session.looks_paywalled("Purchase this article for $30"))
        self.assertFalse(self.session.looks_paywalled("This is an open access article"))

    def test_save_payload(self):
        """Payload is saved correctly to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.pdf"
            result = self.session.save_payload(b"%PDF-data", path)
            self.assertTrue(Path(result).is_file())
            self.assertEqual(Path(result).read_bytes(), b"%PDF-data")


if __name__ == "__main__":
    unittest.main()
