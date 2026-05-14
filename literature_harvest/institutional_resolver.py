"""Institutional resolver — DOI landing-page → PDF candidate extraction.

Uses ``requests.Session`` to follow DOI redirects and extract PDF links
from publisher landing pages.  This module relies **only** on the user's
local network entitlements (campus IP, VPN, institutional proxy).  It does
**not** bypass paywalls or use unauthorised sources.

Compliance:
  1. Only uses locally available legitimate access rights.
  2. No paywall bypass, captcha bypass, account restriction bypass.
  3. No Sci-Hub, pirate sources, or unauthorized mirrors.
  4. No credentials, cookies, or tokens in logs or output files.
  5. Low concurrency, respect publisher access rules.
  6. Non-OA papers that cannot be auto-downloaded -> manual_download_required.
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from literature_harvest.access_markers import (
    CAPTCHA_MARKERS,
    LOGIN_MARKERS,
    PAYWALL_MARKERS,
)
from literature_harvest.models import InstitutionalResolveResult
from literature_harvest.status import (
    BROKEN_LINK,
    CAPTCHA_OR_BOT_CHECK,
    DOWNLOAD_FAILED,
    INSTITUTION_LOGIN_REQUIRED,
    MANUAL_DOWNLOAD_REQUIRED,
    PAYWALL_DETECTED_NO_ENTITLEMENT,
    PUBLISHER_BLOCKED,
    RATE_LIMITED,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT = 45
DEFAULT_DELAY = 0.5

# Known PDF URL patterns (path-based heuristic)
_PDF_PATH_PATTERNS: list[re.Pattern] = [
    re.compile(r"/pdf/", re.IGNORECASE),
    re.compile(r"/doi/pdf/", re.IGNORECASE),
    re.compile(r"/epdf/", re.IGNORECASE),
    re.compile(r"/downloadpdf", re.IGNORECASE),
    re.compile(r"article-pdf", re.IGNORECASE),
    re.compile(r"pdfdownload", re.IGNORECASE),
    re.compile(r"/pdfdownload", re.IGNORECASE),
    re.compile(r"/pdf\.html", re.IGNORECASE),
]

_PDF_LINK_TEXTS: list[re.Pattern] = [
    re.compile(r"download\s+pdf", re.IGNORECASE),
    re.compile(r"view\s+pdf", re.IGNORECASE),
    re.compile(r"full\s+text\s+pdf", re.IGNORECASE),
    re.compile(r"pdf\s+full\s+text", re.IGNORECASE),
    re.compile(r"article\s+pdf", re.IGNORECASE),
    re.compile(r"get\s+pdf", re.IGNORECASE),
    re.compile(r"pdf\s+download", re.IGNORECASE),
]

# Publisher detection from URL hostname
_PUBLISHER_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"nature\.com", re.IGNORECASE), "Springer Nature"),
    (re.compile(r"springer", re.IGNORECASE), "Springer Nature"),
    (re.compile(r"elsevier", re.IGNORECASE), "Elsevier"),
    (re.compile(r"sciencedirect", re.IGNORECASE), "Elsevier"),
    (re.compile(r"cell\.com", re.IGNORECASE), "Elsevier (Cell Press)"),
    (re.compile(r"wiley", re.IGNORECASE), "Wiley"),
    (re.compile(r"taylor.*francis", re.IGNORECASE), "Taylor & Francis"),
    (re.compile(r"tandfonline", re.IGNORECASE), "Taylor & Francis"),
    (re.compile(r"sagepub", re.IGNORECASE), "SAGE"),
    (re.compile(r"oxford", re.IGNORECASE), "Oxford University Press"),
    (re.compile(r"oup\.com", re.IGNORECASE), "Oxford University Press"),
    (re.compile(r"cambridge\.org", re.IGNORECASE), "Cambridge University Press"),
    (re.compile(r"acs\.org", re.IGNORECASE), "American Chemical Society"),
    (re.compile(r"pubs\.acs\.org", re.IGNORECASE), "American Chemical Society"),
    (re.compile(r"rsc\.org", re.IGNORECASE), "Royal Society of Chemistry"),
    (re.compile(r"pubmed\.ncbi", re.IGNORECASE), "PubMed Central"),
    (re.compile(r"pmc\.ncbi", re.IGNORECASE), "PubMed Central"),
    (re.compile(r"plos\.org", re.IGNORECASE), "PLOS"),
    (re.compile(r"frontiersin", re.IGNORECASE), "Frontiers"),
    (re.compile(r"mdpi\.com", re.IGNORECASE), "MDPI"),
    (re.compile(r"biorxiv", re.IGNORECASE), "bioRxiv"),
    (re.compile(r"medrxiv", re.IGNORECASE), "medRxiv"),
    (re.compile(r"arxiv\.org", re.IGNORECASE), "arXiv"),
    (re.compile(r"researchsquare", re.IGNORECASE), "Research Square"),
    (re.compile(r"pnas\.org", re.IGNORECASE), "PNAS"),
    (re.compile(r"nejm\.org", re.IGNORECASE), "NEJM"),
    (re.compile(r"bmj\.com", re.IGNORECASE), "BMJ"),
    (re.compile(r"thelancet", re.IGNORECASE), "The Lancet"),
    (re.compile(r"ieee", re.IGNORECASE), "IEEE"),
    (re.compile(r"aclweb", re.IGNORECASE), "ACL"),
]

# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class InstitutionalResolver:
    """Resolve a DOI / landing page and extract PDF candidates.

    Uses ``requests.Session`` to follow redirects and parse the publisher
    page for PDF links.  The session carries the user's network entitlements
    (campus IP range, VPN, institutional proxy) transparently.
    """

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        delay: float = DEFAULT_DELAY,
        user_agent: str = USER_AGENT,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self.delay = delay
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, doi: str, metadata: Optional[dict[str, Any]] = None) -> InstitutionalResolveResult:
        """Resolve a DOI and extract PDF candidates from its landing page.

        Args:
            doi: The DOI to resolve (with or without ``doi.org/`` prefix).
            metadata: Optional paper metadata (title, journal, year, etc.).

        Returns:
            An :class:`InstitutionalResolveResult` with all discovered
            PDF candidates and access-barrier information.
        """
        normalised = self._normalise_doi(doi)
        if not normalised:
            return InstitutionalResolveResult(
                doi=doi or "", status="manual_download_required",
                reason="empty_or_invalid_doi",
                access_mode="manual_required",
            )

        # Step 1: resolve DOI → follow redirects → landing page
        doi_url = f"https://doi.org/{normalised}"
        ok, result_or_data = self._follow_doi(doi_url)
        if not ok:
            return result_or_data  # fatal error result

        landing_url, redirect_chain, html = result_or_data

        # Step 2: detect publisher
        publisher = self._detect_publisher(landing_url)

        # Step 3: check for access barriers
        markers = self._detect_access_barriers(html, landing_url)
        if markers:
            status = self._classify_barrier(markers)
            if status in (CAPTCHA_OR_BOT_CHECK, PUBLISHER_BLOCKED):
                return InstitutionalResolveResult(
                    doi=normalised, source_url=doi_url,
                    landing_url=landing_url, publisher=publisher,
                    pdf_candidates=[], status=status.value,
                    reason="; ".join(markers),
                    redirect_chain=redirect_chain,
                    detected_markers=markers,
                    access_mode="institutional",
                )

        # Step 4: extract PDF candidates
        pdf_candidates = self._extract_pdf_urls(html, landing_url)

        # Step 5: if markers indicate login/paywall but we still found no PDF
        if not pdf_candidates and markers:
            barrier_status = self._classify_barrier(markers).value
            return InstitutionalResolveResult(
                doi=normalised, source_url=doi_url,
                landing_url=landing_url, publisher=publisher,
                pdf_candidates=[], status=barrier_status,
                reason="; ".join(markers),
                redirect_chain=redirect_chain,
                detected_markers=markers,
                access_mode="institutional",
            )

        if not pdf_candidates:
            return InstitutionalResolveResult(
                doi=normalised, source_url=doi_url,
                landing_url=landing_url, publisher=publisher,
                pdf_candidates=[], status=MANUAL_DOWNLOAD_REQUIRED.value,
                reason="no_pdf_candidates_found",
                redirect_chain=redirect_chain,
                detected_markers=markers,
                access_mode="institutional",
            )

        # Step 6: try to download the best candidate
        selected_url = pdf_candidates[0]
        final_status, payload = self._try_download_candidate(selected_url)
        pdf_downloaded = final_status in (
            "oa_pdf_downloaded", "institution_pdf_downloaded",
        )

        return InstitutionalResolveResult(
            doi=normalised, source_url=doi_url,
            landing_url=landing_url, publisher=publisher,
            pdf_candidates=pdf_candidates,
            selected_pdf_url=selected_url,
            status=final_status,
            payload=payload,
            reason="pdf_found_and_downloaded" if pdf_downloaded
            else f"pdf_found_but_download_failed: {final_status}",
            redirect_chain=redirect_chain,
            detected_markers=markers,
            access_mode="institutional" if pdf_downloaded else "manual_required",
        )

    # ------------------------------------------------------------------
    # DOI resolution
    # ------------------------------------------------------------------

    def _follow_doi(
        self, doi_url: str,
    ) -> tuple[bool, Any]:
        """Follow DOI redirects and capture the landing page.

        Returns ``(True, (landing_url, redirect_chain, html))`` on success
        or ``(False, InstitutionalResolveResult)`` on fatal error.
        """
        redirect_chain = [doi_url]
        last_url = doi_url

        try:
            resp = self.session.get(
                doi_url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            )
            if resp.history:
                redirect_chain = [r.url for r in resp.history] + [resp.url]
            last_url = resp.url
            html = resp.text

            if resp.status_code == 429:
                return False, InstitutionalResolveResult(
                    doi=doi_url, status=RATE_LIMITED.value,
                    reason="http_429_rate_limited",
                    redirect_chain=redirect_chain,
                )
            if resp.status_code in (404, 410):
                return False, InstitutionalResolveResult(
                    doi=doi_url, status=BROKEN_LINK.value,
                    reason=f"http_{resp.status_code}",
                    redirect_chain=redirect_chain,
                )
            if resp.status_code in (401, 403):
                return False, InstitutionalResolveResult(
                    doi=doi_url, status=PUBLISHER_BLOCKED.value,
                    reason=f"http_{resp.status_code}",
                    redirect_chain=redirect_chain,
                )
            if resp.status_code >= 400:
                return False, InstitutionalResolveResult(
                    doi=doi_url, status=DOWNLOAD_FAILED.value,
                    reason=f"http_{resp.status_code}",
                    redirect_chain=redirect_chain,
                )

            time.sleep(self.delay)
            return True, (last_url, redirect_chain, html)

        except requests.exceptions.Timeout:
            return False, InstitutionalResolveResult(
                doi=doi_url, status=DOWNLOAD_FAILED.value,
                reason="timeout",
            )
        except requests.exceptions.ConnectionError:
            return False, InstitutionalResolveResult(
                doi=doi_url, status=DOWNLOAD_FAILED.value,
                reason="connection_error",
            )
        except requests.exceptions.RequestException as exc:
            return False, InstitutionalResolveResult(
                doi=doi_url, status=DOWNLOAD_FAILED.value,
                reason=f"request_failed: {exc}",
            )

    # ------------------------------------------------------------------
    # PDF URL extraction
    # ------------------------------------------------------------------

    def _extract_pdf_urls(self, html: str, base_url: str) -> list[str]:
        """Extract all PDF candidate URLs from the page HTML."""
        candidates: list[str] = []
        seen: set[str] = set()
        soup = BeautifulSoup(html, "lxml")

        # 1. <meta name="citation_pdf_url" content="...">
        for tag in soup.find_all("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)}):
            url = tag.get("content", "")
            if url and url not in seen:
                absolute = urljoin(base_url, url)
                seen.add(absolute)
                candidates.append(absolute)

        # 2. <link rel="alternate" type="application/pdf" href="...">
        for tag in soup.find_all("link", attrs={"type": "application/pdf"}):
            url = tag.get("href", "")
            if url and url not in seen:
                absolute = urljoin(base_url, url)
                seen.add(absolute)
                candidates.append(absolute)

        # 3. <a href="..."> where the URL matches PDF patterns
        for tag in soup.find_all("a", href=True):
            href = tag.get("href", "")
            if not href or href in seen:
                continue
            text = (tag.get_text() or "").strip().lower()
            # Check path pattern
            if any(p.search(href) for p in _PDF_PATH_PATTERNS):
                absolute = urljoin(base_url, href)
                if absolute not in seen:
                    seen.add(absolute)
                    candidates.append(absolute)
                continue
            # Check link text
            if any(p.search(text) for p in _PDF_LINK_TEXTS):
                absolute = urljoin(base_url, href)
                if absolute not in seen:
                    seen.add(absolute)
                    candidates.append(absolute)

        return candidates

    # ------------------------------------------------------------------
    # Access-barrier detection
    # ------------------------------------------------------------------

    def _detect_access_barriers(self, html: str, url: str) -> list[str]:
        """Detect login walls, captchas, and paywalls in the page."""
        markers: list[str] = []
        text_lower = html.lower()

        for marker in LOGIN_MARKERS:
            if marker in text_lower:
                markers.append(marker)
                break

        for marker in CAPTCHA_MARKERS:
            if marker in text_lower:
                markers.append(marker)
                break

        for marker in PAYWALL_MARKERS:
            if marker in text_lower:
                markers.append(marker)
                break

        return markers

    def _classify_barrier(self, markers: list[str]) -> str:
        """Determine the DownloadStatus based on detected markers."""
        marker_text = " ".join(markers).lower()
        for m in CAPTCHA_MARKERS:
            if m in marker_text:
                return CAPTCHA_OR_BOT_CHECK
        for m in LOGIN_MARKERS:
            if m in marker_text:
                return INSTITUTION_LOGIN_REQUIRED
        for m in PAYWALL_MARKERS:
            if m in marker_text:
                return PAYWALL_DETECTED_NO_ENTITLEMENT
        return MANUAL_DOWNLOAD_REQUIRED

    # ------------------------------------------------------------------
    # Download candidate
    # ------------------------------------------------------------------

    def _try_download_candidate(self, url: str) -> tuple[str, Optional[bytes]]:
        """Try to download a PDF candidate.

        Returns ``(status_string, payload_or_None)``.
        """
        try:
            resp = self.session.get(
                url,
                timeout=self.timeout,
                allow_redirects=True,
                headers={"Accept": "application/pdf, */*;q=0.8"},
            )
            if resp.status_code == 429:
                return RATE_LIMITED.value, None
            if resp.status_code in (401, 403):
                return PUBLISHER_BLOCKED.value, None
            if resp.status_code >= 400:
                return DOWNLOAD_FAILED.value, None

            payload = resp.content
            content_type = (resp.headers.get("Content-Type") or "").lower()

            if payload.startswith(b"%PDF") or "pdf" in content_type:
                return "institution_pdf_downloaded", payload
            if "html" in content_type:
                return PAYWALL_DETECTED_NO_ENTITLEMENT.value, None

            return DOWNLOAD_FAILED.value, None

        except requests.RequestException:
            return DOWNLOAD_FAILED.value, None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_doi(doi: str) -> str:
        """Strip URL prefixes and whitespace from a DOI."""
        if not doi:
            return ""
        d = doi.strip()
        d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d, flags=re.IGNORECASE)
        d = re.sub(r"^doi:\s*", "", d, flags=re.IGNORECASE)
        return d.strip()

    @staticmethod
    def _detect_publisher(url: str) -> str:
        """Detect the publisher name from a URL."""
        for pattern, name in _PUBLISHER_PATTERNS:
            if pattern.search(url):
                return name
        return ""

    # _normalise_url removed — was dead code, use urljoin directly instead
