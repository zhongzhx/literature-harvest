"""Typed data classes for the harvest pipeline.

Compliance:
  - Only uses locally available legitimate access rights.
  - No paywall bypass, captcha bypass, account restriction bypass.
  - No Sci-Hub, pirate sources, or unauthorized mirrors.
  - No credentials, cookies, or tokens in logs or output files.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


# ── helpers ──────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# ── InstitutionalResolver result ─────────────────────────────────


@dataclass
class InstitutionalResolveResult:
    """Structured result from resolving a DOI / landing page for PDF candidates.

    This is the primary output of ``InstitutionalResolver.resolve()``.
    """

    doi: str = ""
    """The DOI that was resolved (normalised)."""

    source_url: str = ""
    """The URL that was actually fetched (after any redirects)."""

    landing_url: str = ""
    """The final publisher landing page URL."""

    publisher: str = ""
    """Detected publisher name (e.g. 'Elsevier', 'Springer Nature')."""

    pdf_candidates: list[str] = field(default_factory=list)
    """All PDF candidate URLs extracted from the page."""

    selected_pdf_url: str = ""
    """The PDF URL that was selected for download (if any)."""

    access_mode: str = "unknown"
    """How access was attempted: 'oa', 'institutional', 'browser_assisted', or 'manual_required'."""

    status: str = "metadata_only"
    """Resolution status — one of the DownloadStatus values."""

    reason: str = ""
    """Human-readable explanation of the outcome."""

    redirect_chain: list[str] = field(default_factory=list)
    """Full URL redirect chain from DOI resolve to final page."""

    detected_markers: list[str] = field(default_factory=list)
    """Access-barrier markers detected on the page (login form, SSO, captcha, etc.)."""

    error: Optional[str] = None
    """Error message if resolution failed."""

    payload: Optional[bytes] = None
    """Raw PDF bytes that were already downloaded by the resolver (saves a re-fetch)."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def error_result(cls, doi: str, error_msg: str) -> "InstitutionalResolveResult":
        return cls(doi=doi, status="download_failed", error=error_msg, reason=error_msg)


# ── Per-paper download result ────────────────────────────────────


@dataclass
class DownloadResult:
    """Complete download outcome for a single paper."""

    record_id: str = ""
    """Unique record identifier."""

    doi: str = ""
    """Normalised DOI."""

    title: str = ""
    """Paper title."""

    download_status: str = "metadata_only"
    """Fine-grained DownloadStatus value."""

    failure_reason: str = ""
    """If status indicates failure, the specific reason."""

    access_route: str = ""
    """Which route succeeded: 'oa', 'institutional', 'browser', or '' if none."""

    final_pdf_path: str = ""
    """Local path to the downloaded PDF (empty if none)."""

    final_pdf_url: str = ""
    """URL from which the PDF was downloaded."""

    content_format: str = ""
    """Format of saved content: 'pdf', 'html', 'xml', or ''."""

    publisher: str = ""
    """Detected publisher name."""

    sha256: str = ""
    """SHA-256 of the downloaded file (set by ingest_hook)."""

    ingest_status: str = "ingest_pending"
    """Lifecycle status: ingest_pending / ingested_to_kb / ingest_failed."""

    attempt_count: int = 0
    """Number of download attempts made."""

    warnings: list[str] = field(default_factory=list)
    """Non-fatal warnings encountered during processing."""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_legacy(cls, row: dict[str, Any]) -> "DownloadResult":
        """Convert a legacy download-log row to a DownloadResult."""
        from literature_harvest.status import DownloadStatus as DS

        legacy_status = row.get("download_status", "metadata_only")
        return cls(
            record_id=str(row.get("record_id", "")),
            doi=str(row.get("doi", "")),
            title=str(row.get("title", "")),
            download_status=DS.from_legacy(legacy_status).value,
            failure_reason=str(row.get("failure_reason", "")),
            access_route=str(row.get("access_route_used", "")),
            final_pdf_path=str(row.get("final_pdf_path", "")),
            final_pdf_url=str(row.get("final_pdf_url", "")),
            content_format=str(row.get("content_format", "")),
            attempt_count=int(row.get("attempt_count", 0)),
        )


# ─── Paper requiring manual download ──────────────────────────────


@dataclass
class ManualDownloadItem:
    """A paper that could not be auto-downloaded and needs manual retrieval."""

    doi: str = ""
    title: str = ""
    authors: str = ""
    year: Optional[int] = None
    journal: str = ""
    publisher_url: str = ""
    reason: str = ""
    suggested_action: str = (
        "Access via your institution's library portal or publisher website"
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year or "",
            "journal": self.journal,
            "doi": self.doi,
            "publisher_url": self.publisher_url,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
        }


# ─── Aggregate summary ────────────────────────────────────────────


@dataclass
class HarvestSummary:
    """Aggregate statistics for a harvest run, serialised to ``download_summary.json``.

    This is the primary file Agents should read to understand run results.
    """

    run_id: str = field(default_factory=_new_id)
    query: str = ""
    started_at: str = field(default_factory=_now_iso)
    finished_at: str = ""
    output_dir: str = ""

    total_candidates: int = 0
    oa_pdf_downloaded: int = 0
    institution_pdf_downloaded: int = 0
    browser_pdf_downloaded: int = 0
    html_saved: int = 0
    xml_saved: int = 0
    manual_download_required: int = 0
    failed: int = 0
    duplicates: int = 0
    ingest_pending: int = 0
    ingested_to_kb: int = 0

    manual_download_queue: str = ""
    """Path to the manual_download_queue.csv file."""

    def finish(self) -> None:
        self.finished_at = _now_iso()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_results(cls, query: str, results: list[DownloadResult],
                     output_dir: str = "") -> "HarvestSummary":
        """Build a summary from a list of DownloadResults."""
        from literature_harvest.status import DownloadStatus as DS

        summary = cls(query=query, output_dir=output_dir)
        summary.total_candidates = len(results)
        for r in results:
            s = r.download_status
            if s == DS.OA_PDF_DOWNLOADED:
                summary.oa_pdf_downloaded += 1
            elif s == DS.INSTITUTION_PDF_DOWNLOADED:
                summary.institution_pdf_downloaded += 1
            elif s == DS.BROWSER_PDF_DOWNLOADED:
                summary.browser_pdf_downloaded += 1
            elif s == DS.HTML_SAVED:
                summary.html_saved += 1
            elif s == DS.XML_SAVED:
                summary.xml_saved += 1
            elif s == DS.MANUAL_DOWNLOAD_REQUIRED:
                summary.manual_download_required += 1
            elif s == DS.DUPLICATE_SKIPPED:
                summary.duplicates += 1
            elif s == DS.INGEST_PENDING:
                summary.ingest_pending += 1
            elif s == DS.INGESTED_TO_KB:
                summary.ingested_to_kb += 1
            elif DS.is_success(s):
                pass  # already counted above
            else:
                summary.failed += 1
        return summary
