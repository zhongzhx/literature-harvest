"""Post-download processing hook — PDF verification, dedup, and KB ingest interface.

After a paper is downloaded, this module:
  1. Verifies the PDF is real and readable.
  2. Computes a SHA-256 hash.
  3. Checks for duplicates by SHA-256 and DOI.
  4. Writes per-paper ingest status.
  5. Provides a **stub** for future ResearchOS KB ingestion.

Compliance:
  1. Only uses locally available legitimate access rights.
  2. No paywall bypass, captcha bypass, account restriction bypass.
  3. No Sci-Hub, pirate sources, or unauthorized mirrors.
  4. No credentials, cookies, or tokens in logs or output files.
  5. Low concurrency, respect publisher access rules.
  6. Non-OA papers that cannot be auto-downloaded -> manual_download_required.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from literature_harvest.status import (
    DUPLICATE_SKIPPED,
    INGESTED_TO_KB,
    INGEST_FAILED,
    INGEST_PENDING,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_pdf(path: str | Path) -> bool:
    """Check that a file is a valid PDF.

    Criteria:
      - File exists and is > 8 bytes.
      - File starts with the ``%PDF`` magic bytes.
      - File is readable (no read errors).

    Args:
        path: Path to the file.

    Returns:
        True if the file appears to be a valid PDF.
    """
    path = Path(path)
    try:
        if not path.is_file():
            return False
        if path.stat().st_size < 8:
            return False
        header = path.read_bytes()[:8]
        return header.startswith(b"%PDF")
    except (OSError, PermissionError):
        return False


def compute_sha256(path: str | Path) -> str:
    """Compute the SHA-256 hex digest of a file.

    Args:
        path: Path to the file.

    Returns:
        SHA-256 hex string, or empty string on error.
    """
    path = Path(path)
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return ""


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def _load_manifest(manifest_path: str | Path) -> list[dict[str, Any]]:
    """Load an existing manifest file (JSONL or CSV)."""
    path = Path(manifest_path)
    if not path.is_file():
        return []

    if path.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records
    # Fallback: CSV
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def check_duplicate_by_sha256(sha256: str, manifest: list[dict[str, Any]]) -> bool:
    """Return True if the SHA-256 already exists in the manifest."""
    if not sha256:
        return False
    for entry in manifest:
        if entry.get("sha256") == sha256:
            return True
    return False


def check_duplicate_by_doi(doi: str, manifest: list[dict[str, Any]]) -> bool:
    """Return True if the DOI already exists in the manifest."""
    if not doi:
        return False
    doi_norm = doi.strip().lower()
    for entry in manifest:
        entry_doi = (entry.get("doi") or "").strip().lower()
        if entry_doi == doi_norm:
            return True
    return False


# ---------------------------------------------------------------------------
# Ingest status management
# ---------------------------------------------------------------------------


_INVEST_STATUS_FIELDS = [
    "record_id",
    "doi",
    "title",
    "path",
    "sha256",
    "file_size_bytes",
    "ingest_status",
    "ingest_error",
    "updated_at",
]


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def read_ingest_status(ingest_csv: str | Path) -> list[dict[str, Any]]:
    """Read the ingest status CSV into a list of dicts."""
    path = Path(ingest_csv)
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def mark_ingest_pending(
    record: dict[str, Any],
    ingest_csv: str | Path,
) -> None:
    """Record a paper as ``ingest_pending`` in the ingest status CSV.

    Args:
        record: Dict with at minimum ``record_id``, ``doi``, ``title``, ``path``.
        ingest_csv: Path to the ingest status CSV.
    """
    path = Path(ingest_csv)
    path.parent.mkdir(parents=True, exist_ok=True)

    sha256 = compute_sha256(record.get("path", ""))
    entry = {
        "record_id": record.get("record_id", ""),
        "doi": record.get("doi", ""),
        "title": record.get("title", ""),
        "path": record.get("path", ""),
        "sha256": sha256,
        "file_size_bytes": str(Path(record.get("path", "")).stat().st_size)
        if record.get("path") else "0",
        "ingest_status": INGEST_PENDING.value,
        "ingest_error": "",
        "updated_at": _now_iso(),
    }

    file_exists = path.is_file()
    with path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_INVEST_STATUS_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(entry)


# ---------------------------------------------------------------------------
# Duplicate check + mark pipeline
# ---------------------------------------------------------------------------


def process_downloaded_paper(
    record: dict[str, Any],
    output_dir: str | Path,
    manifest: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Run the full post-download pipeline for a single paper.

    Steps:
      1. Verify PDF.
      2. Compute SHA-256.
      3. Check for duplicates.
      4. Mark ingest_pending.

    Args:
        record: Dict with ``record_id``, ``doi``, ``title``, ``path``.
        output_dir: Output directory for ingest status CSV.
        manifest: Optional existing manifest for dedup check.

    Returns:
        A ``DownloadStatus`` string indicating the result.
    """
    pdf_path = record.get("path", "")
    if not pdf_path or not Path(pdf_path).is_file():
        return "metadata_only"

    if not verify_pdf(pdf_path):
        return "downloaded_but_not_parseable"

    sha256 = compute_sha256(pdf_path)
    doi = record.get("doi", "")

    # Duplicate check
    if manifest is not None:
        if check_duplicate_by_sha256(sha256, manifest):
            return DUPLICATE_SKIPPED.value
        if doi and check_duplicate_by_doi(doi, manifest):
            return DUPLICATE_SKIPPED.value

    # Mark as pending ingest
    ingest_csv = Path(output_dir) / "ingest_status.csv"
    mark_ingest_pending(record, ingest_csv)

    return INGEST_PENDING.value


# ---------------------------------------------------------------------------
# ResearchOS KB ingest stub
# ---------------------------------------------------------------------------


def call_researchos_ingest_api(record: dict[str, Any]) -> bool:
    """Stub: send a paper to ResearchOS KB for ingestion.

    **This is a placeholder.**  When the ResearchOS ingest API is available,
    implement the actual HTTP call here.

    Args:
        record: Paper data including ``path``, ``doi``, ``title``, etc.

    Returns:
        True if ingestion was successful, False otherwise.
    """
    _ = record  # placeholder
    # TODO: implement call_researchos_ingest_api() when KB API is ready
    return False
