"""Tests for the output file formats and completeness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from literature_harvest.models import DownloadResult, HarvestSummary, ManualDownloadItem


class TestHarvestSummary(unittest.TestCase):
    def test_summary_from_results_counts_correctly(self):
        """HarvestSummary aggregates DownloadResults correctly."""
        results = [
            DownloadResult(record_id="1", download_status="oa_pdf_downloaded"),
            DownloadResult(record_id="2", download_status="oa_pdf_downloaded"),
            DownloadResult(record_id="3", download_status="institution_pdf_downloaded"),
            DownloadResult(record_id="4", download_status="browser_pdf_downloaded"),
            DownloadResult(record_id="5", download_status="html_saved"),
            DownloadResult(record_id="6", download_status="manual_download_required"),
            DownloadResult(record_id="7", download_status="download_failed"),
            DownloadResult(record_id="8", download_status="duplicate_skipped"),
        ]
        summary = HarvestSummary.from_results("test_query", results)
        self.assertEqual(summary.total_candidates, 8)
        self.assertEqual(summary.oa_pdf_downloaded, 2)
        self.assertEqual(summary.institution_pdf_downloaded, 1)
        self.assertEqual(summary.browser_pdf_downloaded, 1)
        self.assertEqual(summary.html_saved, 1)
        self.assertEqual(summary.manual_download_required, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.duplicates, 1)

    def test_summary_fields_present(self):
        """All required fields are present in summary.to_dict()."""
        summary = HarvestSummary(query="test")
        d = summary.to_dict()
        required_keys = [
            "run_id", "query", "started_at",
            "total_candidates", "oa_pdf_downloaded", "institution_pdf_downloaded",
            "browser_pdf_downloaded", "html_saved", "manual_download_required",
            "failed", "duplicates", "output_dir",
        ]
        for key in required_keys:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_summary_json_serializable(self):
        """Summary serializes to JSON without error."""
        summary = HarvestSummary(query="test")
        summary.oa_pdf_downloaded = 5
        json_str = json.dumps(summary.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        self.assertEqual(parsed["oa_pdf_downloaded"], 5)

    def test_manual_download_item_csv_fields(self):
        """ManualDownloadItem produces the correct CSV row fields."""
        item = ManualDownloadItem(
            doi="10.1234/test",
            title="Test Paper",
            authors="Author A",
            year=2023,
            journal="Test Journal",
            publisher_url="https://doi.org/10.1234/test",
            reason="no_pdf_found",
        )
        row = item.to_csv_row()
        expected_keys = {"title", "authors", "year", "journal", "doi", "publisher_url", "reason", "suggested_action"}
        self.assertEqual(set(row.keys()), expected_keys)
        self.assertEqual(row["doi"], "10.1234/test")
        self.assertEqual(row["year"], 2023)


if __name__ == "__main__":
    unittest.main()
