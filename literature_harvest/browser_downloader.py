"""Playwright-based browser-assisted downloader.

Opens the publisher landing page in a real browser, waits for JavaScript
rendering, then extracts the PDF URL.  Useful when the user has a
browser session with institutional login cookies (campus VPN, Shibboleth,
OpenAthens, etc.).

This module is **optional** — it requires ``playwright`` to be installed.
Install with::

    pip install literature-harvest[browser]

Compliance:
  1. Only uses locally available legitimate access rights.
  2. No paywall bypass, captcha bypass, account restriction bypass.
  3. No Sci-Hub, pirate sources, or unauthorized mirrors.
  4. **No credentials, cookies, or tokens in logs or output files.**
  5. Low concurrency, respect publisher access rules.
  6. Non-OA papers that cannot be auto-downloaded -> manual_download_required.

Security:
  - The browser profile directory is **never** written to logs or output files.
  - Cookies and authentication state stay in the profile directory.
  - The profile directory must **never** be committed to the repository.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Optional

import requests as req

from literature_harvest.access_markers import (
    _CAPTCHA_MARKERS_RE,
    _LOGIN_MARKERS_RE,
    _PAYWALL_MARKERS_RE,
)
from literature_harvest.models import DownloadResult
from literature_harvest.status import (
    BROWSER_PDF_DOWNLOADED,
    CAPTCHA_OR_BOT_CHECK,
    DOWNLOAD_FAILED,
    HTML_SAVED,
    INSTITUTION_LOGIN_REQUIRED,
    MANUAL_DOWNLOAD_REQUIRED,
    PAYWALL_DETECTED_NO_ENTITLEMENT,
)

# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import Browser, Page, sync_playwright  # noqa: F401

    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


_PLAYWRIGHT_NOT_INSTALLED_MSG = (
    "Playwright is not installed.  Install it with:\n"
    "  pip install literature-harvest[browser]\n"
    "  playwright install chromium"
)

# ── Access barrier detection (browser context) ────────────────────
# Regex patterns are imported from access_markers

_PDF_URL_PATTERNS = re.compile(
    r"(/pdf/|/doi/pdf/|/epdf/|downloadpdf|article-pdf|"
    r"citation_pdf_url|application/pdf)",
    re.IGNORECASE,
)

# ── Browser assisted modes ────────────────────────────────────────


class BrowserDownloader:
    """Download papers via Playwright with browser login session.

    Typical usage::

        downloader = BrowserDownloader()
        result = downloader.download(
            doi="10.1038/s41586-023-00000-0",
            profile_dir="./browser_profile",
            headless=False,         # show browser for first-time login
        )

    The browser profile directory persists cookies and login state
    across runs, so subsequent downloads can be headless.
    """

    def __init__(self, timeout: int = 60) -> None:
        if not _PLAYWRIGHT_AVAILABLE:
            raise ImportError(_PLAYWRIGHT_NOT_INSTALLED_MSG)
        self.timeout = timeout * 1000  # Playwright uses ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def download(
        self,
        doi: str,
        landing_url: str = "",
        profile_dir: Optional[str | Path] = None,
        headless: bool = True,
        output_dir: Optional[str | Path] = None,
        session: Optional["req.Session"] = None,
    ) -> DownloadResult:
        """Open the publisher page in a browser and attempt to download the PDF.

        Args:
            doi: The DOI to resolve.
            landing_url: Pre-resolved landing URL.  If empty, resolves from DOI.
            profile_dir: Path to a persistent browser profile directory.
            headless: Run browser in headless mode (default True).
            output_dir: Directory to save the downloaded PDF (optional).
            session: Optional ``requests.Session`` for PDF download (preserves
                institutional cookies/entitlements from prior requests).

        Returns:
            A :class:`DownloadResult` with the outcome.
        """
        from literature_harvest.download_session import USER_AGENT as UA

        result = DownloadResult(doi=doi, download_status=MANUAL_DOWNLOAD_REQUIRED.value)

        with sync_playwright() as pw:
            browser_type = pw.chromium
            launch_options: dict[str, Any] = {
                "headless": headless,
            }
            if profile_dir:
                profile_path = Path(profile_dir).resolve()
                profile_path.mkdir(parents=True, exist_ok=True)
                launch_options["user_data_dir"] = str(profile_path)

            browser = browser_type.launch(**launch_options)
            context = browser.new_context(
                user_agent=UA,
                viewport={"width": 1280, "height": 800},
            )
            page = context.new_page()

            try:
                target_url = landing_url or f"https://doi.org/{doi}"
                page.goto(target_url, wait_until="networkidle", timeout=self.timeout)

                # Wait a moment for JS-rendered content
                time.sleep(2.0)

                # Check for access barriers
                page_text = page.content().lower()
                barrier = self._detect_barrier(page_text)
                if barrier:
                    result.download_status = barrier
                    result.failure_reason = f"barrier_detected_on_page: {barrier}"
                    return result

                # Extract PDF URL
                pdf_url = self._extract_pdf_from_page(page)
                if not pdf_url:
                    result.download_status = MANUAL_DOWNLOAD_REQUIRED.value
                    result.failure_reason = "no_pdf_found_on_page"
                    return result

                # Download the PDF via the provided session (preserves cookies
                # from institutional/campus entitlements) or a bare request
                fetcher: req.Session | Any = session if session is not None else req
                resp = fetcher.get(
                    pdf_url,
                    headers={"User-Agent": UA},
                    timeout=30,
                    allow_redirects=True,
                )
                if resp.status_code >= 400 or not resp.content.startswith(b"%PDF"):
                    result.download_status = DOWNLOAD_FAILED.value
                    result.failure_reason = f"download_failed_status_{resp.status_code}"
                    return result

                # Save
                if output_dir:
                    out = Path(output_dir) / f"{doi.replace('/', '_')}.pdf"
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_bytes(resp.content)
                    result.final_pdf_path = str(out.resolve())
                result.download_status = BROWSER_PDF_DOWNLOADED.value
                result.final_pdf_url = pdf_url
                result.content_format = "pdf"
                result.access_route = "browser"

            except Exception as exc:
                result.download_status = DOWNLOAD_FAILED.value
                result.failure_reason = str(exc)
            finally:
                context.close()
                browser.close()

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _detect_barrier(self, page_text: str) -> str:
        """Check if the page shows an access barrier.

        Returns a DownloadStatus string if a barrier is detected,
        or an empty string if the page appears accessible.
        """
        if _CAPTCHA_MARKERS_RE.search(page_text):
            return CAPTCHA_OR_BOT_CHECK.value
        if _LOGIN_MARKERS_RE.search(page_text):
            return INSTITUTION_LOGIN_REQUIRED.value
        if _PAYWALL_MARKERS_RE.search(page_text):
            return PAYWALL_DETECTED_NO_ENTITLEMENT.value
        return ""

    def _extract_pdf_from_page(self, page: "Page") -> str:
        """Extract PDF URL from a fully loaded Playwright page.

        Tries, in order:
          1. ``meta[name=citation_pdf_url]``
          2. ``link[type=application/pdf]``
          3. ``iframe#pdf``
          4. ``embed[type=application/pdf]``
          5. ``a[href]`` with PDF patterns
        """
        # 1. meta tag
        meta = page.query_selector('meta[name="citation_pdf_url"]')
        if meta:
            url = meta.get_attribute("content")
            if url:
                return url

        # 2. link tag
        link = page.query_selector('link[type="application/pdf"]')
        if link:
            url = link.get_attribute("href")
            if url:
                return page.evaluate(f"new URL('{url}', document.baseURI).href")

        # 3. iframe#pdf
        iframe = page.query_selector("iframe#pdf")
        if iframe:
            src = iframe.get_attribute("src")
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                return src

        # 4. embed
        embed = page.query_selector('embed[type="application/pdf"]')
        if embed:
            src = embed.get_attribute("src")
            if src:
                return src

        # 5. anchor tags with PDF patterns
        anchors = page.query_selector_all("a[href]")
        for a in anchors:
            href = (a.get_attribute("href") or "").strip()
            text = (a.inner_text() or "").strip().lower()
            if _PDF_URL_PATTERNS.search(href):
                return page.evaluate(f"new URL('{href}', document.baseURI).href")
            if re.search(r"download\s+pdf|view\s+pdf|full\s+text\s+pdf", text):
                return page.evaluate(f"new URL('{href}', document.baseURI).href")

        return ""
