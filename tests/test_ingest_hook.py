"""Tests for the ingest hook (PDF verification, SHA-256, dedup)."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from literature_harvest.ingest_hook import (
    check_duplicate_by_doi,
    check_duplicate_by_sha256,
    compute_sha256,
    mark_ingest_pending,
    process_downloaded_paper,
    verify_pdf,
)


class TestIngestHook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_verify_pdf_valid(self):
        """File with %PDF header is verified as PDF."""
        path = self.tmp_path / "test.pdf"
        path.write_bytes(b"%PDF-1.4\ncontents\n")
        self.assertTrue(verify_pdf(str(path)))

    def test_verify_pdf_invalid(self):
        """File without %PDF header is not verified."""
        path = self.tmp_path / "test.pdf"
        path.write_bytes(b"<html>fake</html>")
        self.assertFalse(verify_pdf(str(path)))

    def test_verify_pdf_too_small(self):
        """File smaller than 8 bytes is not a valid PDF."""
        path = self.tmp_path / "test.pdf"
        path.write_bytes(b"%PDF")
        self.assertFalse(verify_pdf(str(path)))

    def test_verify_pdf_missing(self):
        """Non-existent file is not a valid PDF."""
        self.assertFalse(verify_pdf(str(self.tmp_path / "nonexistent.pdf")))

    def test_compute_sha256(self):
        """SHA-256 is computed correctly."""
        path = self.tmp_path / "test.pdf"
        data = b"test data for hashing"
        path.write_bytes(data)
        import hashlib
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(compute_sha256(str(path)), expected)

    def test_check_duplicate_by_sha256(self):
        """Duplicate SHA-256 is detected."""
        manifest = [{"sha256": "abc123"}, {"sha256": "def456"}]
        self.assertTrue(check_duplicate_by_sha256("abc123", manifest))
        self.assertFalse(check_duplicate_by_sha256("xyz789", manifest))

    def test_check_duplicate_by_doi(self):
        """Duplicate DOI is detected (case-insensitive)."""
        manifest = [{"doi": "10.1038/nature12373"}, {"doi": "10.1126/science.123"}]
        self.assertTrue(check_duplicate_by_doi("10.1038/nature12373", manifest))
        self.assertFalse(check_duplicate_by_doi("10.1038/nature99999", manifest))

    def test_mark_ingest_pending_creates_csv(self):
        """mark_ingest_pending creates the ingest status CSV."""
        record = {"record_id": "test001", "doi": "10.1234/test", "title": "Test", "path": ""}
        csv_path = self.tmp_path / "ingest_status.csv"
        mark_ingest_pending(record, str(csv_path))
        self.assertTrue(csv_path.is_file())
        with csv_path.open("r", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["record_id"], "test001")

    def test_process_downloaded_paper_marks_pending(self):
        """A valid PDF goes through the pipeline and is marked ingest_pending."""
        pdf_path = self.tmp_path / "paper.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\nsome content\n")
        record = {"record_id": "p1", "doi": "10.1234/abc", "title": "Test", "path": str(pdf_path)}
        status = process_downloaded_paper(record, str(self.tmp_path))
        self.assertEqual(status, "ingest_pending")
        # CSV should exist
        csv_path = self.tmp_path / "ingest_status.csv"
        self.assertTrue(csv_path.is_file())

    def test_missing_pdf_returns_metadata_only(self):
        """Non-existent file returns metadata_only."""
        record = {"record_id": "p1", "doi": "10.1234/abc", "title": "Test", "path": "/nonexistent/file.pdf"}
        status = process_downloaded_paper(record, str(self.tmp_path))
        self.assertEqual(status, "metadata_only")


if __name__ == "__main__":
    unittest.main()
