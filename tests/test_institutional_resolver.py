"""Tests for the institutional resolver (HTML parsing and DOI normalisation).

These tests verify the pure-logic functions (DOI normalisation, publisher
detection, HTML extraction, access barrier detection) without requiring
external dependencies beyond BeautifulSoup.
"""

from __future__ import annotations

import unittest

try:
    from literature_harvest.institutional_resolver import InstitutionalResolver
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


@unittest.skipIf(not HAS_DEPS, "requires bs4 / lxml / literature_harvest.institutional_resolver")
class TestInstitutionalResolver(unittest.TestCase):
    def setUp(self):
        self.resolver = InstitutionalResolver(timeout=5)

    def test_normalise_doi_strips_prefixes(self):
        """DOI normalisation removes common URL prefixes."""
        self.assertEqual(self.resolver._normalise_doi("10.1038/nature12373"), "10.1038/nature12373")
        self.assertEqual(self.resolver._normalise_doi("https://doi.org/10.1038/nature12373"), "10.1038/nature12373")
        self.assertEqual(self.resolver._normalise_doi("http://dx.doi.org/10.1038/nature12373"), "10.1038/nature12373")
        self.assertEqual(self.resolver._normalise_doi("doi:10.1038/nature12373"), "10.1038/nature12373")
        self.assertEqual(self.resolver._normalise_doi(""), "")

    def test_detect_publisher_from_url(self):
        """Publisher is detected from landing page URL."""
        self.assertEqual(self.resolver._detect_publisher("https://www.nature.com/articles/s41586-023-00000-0"), "Springer Nature")
        self.assertEqual(self.resolver._detect_publisher("https://www.sciencedirect.com/science/article/pii/..."), "Elsevier")
        self.assertEqual(self.resolver._detect_publisher("https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/"), "PubMed Central")
        self.assertEqual(self.resolver._detect_publisher("https://unknown-publisher.org/article/123"), "")

    def test_extract_citation_pdf_url(self):
        """Extract PDF URL from meta[name=citation_pdf_url]."""
        html = """<html><head>
          <meta name="citation_pdf_url" content="https://example.com/article.pdf">
        </head></html>"""
        candidates = self.resolver._extract_pdf_urls(html, "https://example.org/article")
        self.assertIn("https://example.com/article.pdf", candidates)

    def test_extract_link_application_pdf(self):
        """Extract PDF URL from link[type=application/pdf]."""
        html = """<html><head>
          <link rel="alternate" type="application/pdf" href="https://example.org/paper.pdf">
        </head></html>"""
        candidates = self.resolver._extract_pdf_urls(html, "https://example.org/article")
        self.assertIn("https://example.org/paper.pdf", candidates)

    def test_extract_pdf_anchor_with_keyword_text(self):
        """Extract PDF URL from anchor tags with PDF-related text."""
        html = """<html><body>
          <a href="https://example.org/download">Download PDF</a>
        </body></html>"""
        candidates = self.resolver._extract_pdf_urls(html, "https://example.org/article")
        self.assertIn("https://example.org/download", candidates)

    def test_relative_url_resolution(self):
        """Relative PDF URLs are resolved to absolute."""
        html = """<html><head>
          <meta name="citation_pdf_url" content="/files/paper.pdf">
        </head></html>"""
        candidates = self.resolver._extract_pdf_urls(html, "https://journal.org/article/123")
        self.assertIn("https://journal.org/files/paper.pdf", candidates)

    def test_detect_access_barriers_login(self):
        """Login form markers are detected."""
        html = "<html><body>Please log in through your institution to access this content</body></html>"
        markers = self.resolver._detect_access_barriers(html, "https://example.com")
        self.assertTrue(len(markers) > 0)
        self.assertIn(markers[0], ["login", "log in"])

    def test_detect_access_barriers_paywall(self):
        """Paywall markers are detected."""
        html = "<html><body>Subscription required to purchase this article</body></html>"
        markers = self.resolver._detect_access_barriers(html, "https://example.com")
        self.assertTrue(any("subscription" in m for m in markers))

    def test_institutional_access_text_not_failure(self):
        """'Access through your institution' should NOT cause immediate failure.
        In institutional mode, this text means we should try the institutional flow.
        The resolver should still return pdf_candidates if any exist."""
        html = (
            "<html><body>Access through your institution"
            '<meta name="citation_pdf_url" content="https://example.com/paper.pdf">'
            "</body></html>"
        )
        candidates = self.resolver._extract_pdf_urls(html, "https://example.com")
        self.assertIn("https://example.com/paper.pdf", candidates)

    def test_empty_doi_returns_early(self):
        """Empty DOI returns manual_download_required status."""
        result = self.resolver.resolve("")
        self.assertEqual(result.status, "manual_download_required")
        self.assertEqual(result.access_mode, "manual_required")


if __name__ == "__main__":
    unittest.main()
