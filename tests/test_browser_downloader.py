"""Tests for the BrowserDownloader."""

from __future__ import annotations

import unittest

from literature_harvest.browser_downloader import _PLAYWRIGHT_AVAILABLE


class TestBrowserDownloader(unittest.TestCase):
    def test_playwright_not_installed_raises(self):
        """If Playwright is not installed, instantiation raises ImportError."""
        if not _PLAYWRIGHT_AVAILABLE:
            with self.assertRaises(ImportError):
                from literature_harvest.browser_downloader import BrowserDownloader
                BrowserDownloader()
        else:
            # Playwright is installed — just verify it imports
            from literature_harvest.browser_downloader import BrowserDownloader
            self.assertTrue(callable(BrowserDownloader))

    def test_login_page_markers_detected(self):
        """Login page markers produce correct status."""
        from literature_harvest.access_markers import (
            _CAPTCHA_MARKERS_RE,
            _LOGIN_MARKERS_RE,
            _PAYWALL_MARKERS_RE,
        )

        # Test marker logic directly
        def _detect_barrier(text):
            if _CAPTCHA_MARKERS_RE.search(text):
                return "captcha_or_bot_check"
            if _LOGIN_MARKERS_RE.search(text):
                return "institution_login_required"
            if _PAYWALL_MARKERS_RE.search(text):
                return "paywall_detected_no_entitlement"
            return ""

        self.assertEqual(_detect_barrier("Please sign in through your institution"), "institution_login_required")
        self.assertEqual(_detect_barrier("Verify you are human to continue"), "captcha_or_bot_check")
        self.assertEqual(_detect_barrier("Purchase this article for $30"), "paywall_detected_no_entitlement")
        self.assertEqual(_detect_barrier("Open access article with free PDF"), "")


if __name__ == "__main__":
    unittest.main()
