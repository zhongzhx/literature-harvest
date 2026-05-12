"""Tests for the DownloadStatus enum and helpers."""

from __future__ import annotations

import unittest

from literature_harvest.status import DownloadStatus


class TestDownloadStatus(unittest.TestCase):
    def test_enum_values(self):
        """All expected status values are present."""
        self.assertEqual(DownloadStatus.METADATA_ONLY.value, "metadata_only")
        self.assertEqual(DownloadStatus.OA_PDF_DOWNLOADED.value, "oa_pdf_downloaded")
        self.assertEqual(DownloadStatus.INSTITUTION_PDF_DOWNLOADED.value, "institution_pdf_downloaded")
        self.assertEqual(DownloadStatus.BROWSER_PDF_DOWNLOADED.value, "browser_pdf_downloaded")
        self.assertEqual(DownloadStatus.HTML_SAVED.value, "html_saved")
        self.assertEqual(DownloadStatus.XML_SAVED.value, "xml_saved")
        self.assertEqual(DownloadStatus.MANUAL_DOWNLOAD_REQUIRED.value, "manual_download_required")

    def test_from_legacy(self):
        """Legacy statuses map correctly."""
        self.assertEqual(DownloadStatus.from_legacy("success"), DownloadStatus.OA_PDF_DOWNLOADED)
        self.assertEqual(DownloadStatus.from_legacy("inaccessible"), DownloadStatus.PAYWALL_DETECTED_NO_ENTITLEMENT)
        self.assertEqual(DownloadStatus.from_legacy("broken_link"), DownloadStatus.BROKEN_LINK)

    def test_is_success(self):
        """Only true download statuses return True."""
        self.assertTrue(DownloadStatus.is_success("oa_pdf_downloaded"))
        self.assertTrue(DownloadStatus.is_success("institution_pdf_downloaded"))
        self.assertTrue(DownloadStatus.is_success("browser_pdf_downloaded"))
        self.assertTrue(DownloadStatus.is_success("html_saved"))
        self.assertTrue(DownloadStatus.is_success("xml_saved"))
        self.assertFalse(DownloadStatus.is_success("metadata_only"))
        self.assertFalse(DownloadStatus.is_success("manual_download_required"))
        self.assertFalse(DownloadStatus.is_success("download_failed"))

    def test_is_pdf_success(self):
        """Only PDF download statuses return True."""
        self.assertTrue(DownloadStatus.is_pdf_success("oa_pdf_downloaded"))
        self.assertTrue(DownloadStatus.is_pdf_success("institution_pdf_downloaded"))
        self.assertTrue(DownloadStatus.is_pdf_success("browser_pdf_downloaded"))
        self.assertFalse(DownloadStatus.is_pdf_success("html_saved"))
        self.assertFalse(DownloadStatus.is_pdf_success("xml_saved"))

    def test_serialization(self):
        """Enum values serialize to strings cleanly via .value."""
        self.assertEqual(DownloadStatus.OA_PDF_DOWNLOADED.value, "oa_pdf_downloaded")
        self.assertEqual(str(DownloadStatus.OA_PDF_DOWNLOADED.value), "oa_pdf_downloaded")


if __name__ == "__main__":
    unittest.main()
