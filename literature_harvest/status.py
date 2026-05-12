"""Fine-grained download and processing status enum.

Compliance:
  - Only uses locally available legitimate access rights.
  - No paywall bypass, captcha bypass, account restriction bypass.
  - No Sci-Hub, pirate sources, or unauthorized mirrors.
  - No credentials, cookies, or tokens in logs or output files.
"""

from __future__ import annotations

from enum import Enum


class DownloadStatus(str, Enum):
    """Fine-grained status for each paper in the harvest pipeline.

    These statuses are used in ``download_status.jsonl``,
    ``download_summary.json`` and all internal result objects
    so that Agents and front-ends can read the real state of
    each paper without ambiguity.
    """

    # ── Metadata ──────────────────────────────────────────────
    METADATA_ONLY = "metadata_only"
    """No full-text payload was obtained; only metadata was saved."""

    # ── Successful downloads ──────────────────────────────────
    OA_PDF_DOWNLOADED = "oa_pdf_downloaded"
    """PDF was downloaded from an open-access URL."""
    INSTITUTION_PDF_DOWNLOADED = "institution_pdf_downloaded"
    """PDF was obtained via institutional resolver (campus IP / VPN / proxy)."""
    BROWSER_PDF_DOWNLOADED = "browser_pdf_downloaded"
    """PDF was obtained via Playwright browser session with user's login."""
    HTML_SAVED = "html_saved"
    """Only the HTML full-text page was saved (no PDF available)."""
    XML_SAVED = "xml_saved"
    """Only the XML full-text (e.g. PMC XML) was saved."""

    # ── Skipped / duplicate ───────────────────────────────────
    DUPLICATE_SKIPPED = "duplicate_skipped"
    """Paper was already present in the local collection (same DOI / SHA256)."""

    # ── Access barriers (non-terminal — may be resolvable) ────
    INSTITUTION_LOGIN_REQUIRED = "institution_login_required"
    """Publisher page shows an institutional / organisation login prompt."""
    PAYWALL_DETECTED_NO_ENTITLEMENT = "paywall_detected_no_entitlement"
    """Paywall was detected and the current network has no entitlement."""
    CAPTCHA_OR_BOT_CHECK = "captcha_or_bot_check"
    """Publisher responded with a captcha or bot-detection page."""

    # ── Hard failures ─────────────────────────────────────────
    MANUAL_DOWNLOAD_REQUIRED = "manual_download_required"
    """Could not be auto-downloaded via any route; user must download manually."""
    PUBLISHER_BLOCKED = "publisher_blocked"
    """Publisher rejected the request (403, 401) with no entitlement detected."""
    RATE_LIMITED = "rate_limited"
    """HTTP 429 or similar rate-limit response."""
    BROKEN_LINK = "broken_link"
    """The URL returned 404/410 or the resource no longer exists."""
    DOWNLOADED_BUT_NOT_PARSEABLE = "downloaded_but_not_parseable"
    """File was downloaded but is not a valid PDF / HTML / XML."""
    DOWNLOAD_FAILED = "download_failed"
    """Generic download failure (timeout, connection error, etc.)."""

    # ── Post-download lifecycle ───────────────────────────────
    INGEST_PENDING = "ingest_pending"
    """Download succeeded; awaiting KB/RAG ingestion."""
    INGESTED_TO_KB = "ingested_to_kb"
    """Paper has been ingested into the knowledge base."""
    INGEST_FAILED = "ingest_failed"
    """KB ingestion was attempted but failed."""

    # ── Legacy alias mapping ──────────────────────────────────
    @classmethod
    def from_legacy(cls, legacy: str) -> "DownloadStatus":
        """Map a legacy coarse status to the nearest new status."""
        mapping = {
            "success": cls.OA_PDF_DOWNLOADED,
            "inaccessible": cls.PAYWALL_DETECTED_NO_ENTITLEMENT,
            "broken_link": cls.BROKEN_LINK,
            "rate_limited": cls.RATE_LIMITED,
            "metadata_only": cls.METADATA_ONLY,
            "pending": cls.METADATA_ONLY,
            "excluded": cls.METADATA_ONLY,
        }
        return mapping.get(legacy, cls.DOWNLOAD_FAILED)

    @classmethod
    def is_success(cls, status: str) -> bool:
        """Return True if the status indicates a successful full-text acquisition."""
        successes = {
            cls.OA_PDF_DOWNLOADED,
            cls.INSTITUTION_PDF_DOWNLOADED,
            cls.BROWSER_PDF_DOWNLOADED,
            cls.HTML_SAVED,
            cls.XML_SAVED,
        }
        return status in successes

    @classmethod
    def is_pdf_success(cls, status: str) -> bool:
        """Return True only if a PDF was actually obtained."""
        pdf_ok = {
            cls.OA_PDF_DOWNLOADED,
            cls.INSTITUTION_PDF_DOWNLOADED,
            cls.BROWSER_PDF_DOWNLOADED,
        }
        return status in pdf_ok


# Convenience aliases for cleaner code
OA_PDF_DOWNLOADED = DownloadStatus.OA_PDF_DOWNLOADED
INSTITUTION_PDF_DOWNLOADED = DownloadStatus.INSTITUTION_PDF_DOWNLOADED
BROWSER_PDF_DOWNLOADED = DownloadStatus.BROWSER_PDF_DOWNLOADED
METADATA_ONLY = DownloadStatus.METADATA_ONLY
HTML_SAVED = DownloadStatus.HTML_SAVED
XML_SAVED = DownloadStatus.XML_SAVED
DUPLICATE_SKIPPED = DownloadStatus.DUPLICATE_SKIPPED
INSTITUTION_LOGIN_REQUIRED = DownloadStatus.INSTITUTION_LOGIN_REQUIRED
PAYWALL_DETECTED_NO_ENTITLEMENT = DownloadStatus.PAYWALL_DETECTED_NO_ENTITLEMENT
CAPTCHA_OR_BOT_CHECK = DownloadStatus.CAPTCHA_OR_BOT_CHECK
MANUAL_DOWNLOAD_REQUIRED = DownloadStatus.MANUAL_DOWNLOAD_REQUIRED
PUBLISHER_BLOCKED = DownloadStatus.PUBLISHER_BLOCKED
RATE_LIMITED = DownloadStatus.RATE_LIMITED
BROKEN_LINK = DownloadStatus.BROKEN_LINK
DOWNLOADED_BUT_NOT_PARSEABLE = DownloadStatus.DOWNLOADED_BUT_NOT_PARSEABLE
DOWNLOAD_FAILED = DownloadStatus.DOWNLOAD_FAILED
INGEST_PENDING = DownloadStatus.INGEST_PENDING
INGESTED_TO_KB = DownloadStatus.INGESTED_TO_KB
INGEST_FAILED = DownloadStatus.INGEST_FAILED
