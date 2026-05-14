"""Unified CLI entry point for literature-harvest.

Usage::

    python -m literature_harvest harvest "query" [--limit N] [--download]
                                             [--institutional] [--browser-assisted]
                                             [--browser-profile-dir DIR] [--headless]
    python -m literature_harvest resume --run-root PATH [--retry-failed]
    python -m literature_harvest dedup --run-root PATH

Compliance:
  1. Only uses locally available legitimate access rights.
  2. No paywall bypass, captcha bypass, account restriction bypass.
  3. No Sci-Hub, pirate sources, or unauthorized mirrors.
  4. No credentials, cookies, or tokens in logs or output files.
  5. Low concurrency, respect publisher access rules.
  6. Non-OA papers that cannot be auto-downloaded -> manual_download_required.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from literature_harvest.models import DownloadResult, HarvestSummary, ManualDownloadItem
from literature_harvest.status import DownloadStatus


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_harvest(args: argparse.Namespace) -> None:
    """Run a full harvest: search + download + report."""
    from literature_harvest.download_session import DownloadSession
    from literature_harvest.ingest_hook import process_downloaded_paper
    from literature_harvest.institutional_resolver import InstitutionalResolver

    output_root = Path(args.output_root or Path.cwd() / "harvest_output").resolve()
    run_name = args.run_name or f"run_{int(time.time())}"
    run_root = output_root / run_name
    run_root.mkdir(parents=True, exist_ok=True)

    query = args.query
    limit = args.limit or 20
    started_at = _now_iso()

    print(f"Query: {query}")
    print(f"Limit: {limit}")
    print(f"Output: {run_root}")
    print()

    # ── Step 1: Search all sources ──────────────────────────────
    import os
    import tempfile

    os.environ["ASPERGILLUS_HARVEST_ROOT"] = str(run_root)

    from literature_harvest.scripts.harvest_utils import ensure_directories
    from literature_harvest.scripts.merge_and_deduplicate import load_sources, normalize_columns, deduplicate

    ensure_directories()

    # Build a temporary config that enables all 4 sources
    config = {
        "tool_name": "literature_harvest_cli",
        "email": args.email or "",
        "sources": {
            "pubmed": True,
            "pmc": True,
            "europepmc": True,
            "crossref": True,
            "openalex": True,
        },
        "max_results_per_query": {
            "pubmed": limit,
            "pmc": limit,
            "europepmc": limit,
            "crossref": limit,
            "openalex": limit,
        },
        "page_size": {
            "europepmc": 100,
            "crossref": 100,
            "openalex": 100,
        },
        "delay_seconds": {
            "pubmed": 0.34,
            "pmc": 0.34,
            "europepmc": 0.34,
            "crossref": 0.5,
            "openalex": 0.34,
            "download": 0.25,
        },
        "download": {
            "enabled": False,
        },
        "queries": [
            {"name": "cli_query", "query": query},
        ],
    }

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".json")
    tmp_config = Path(tmp_path)
    os.close(tmp_fd)
    try:
        _write_json(tmp_config, config)
        config_path = str(tmp_config)

        from literature_harvest.scripts.search_pubmed import search_pubmed_and_pmc
        from literature_harvest.scripts.search_europepmc import search_europepmc
        from literature_harvest.scripts.search_crossref import search_crossref
        from literature_harvest.scripts.search_openalex import search_openalex

        print(f"Searching PubMed/PMC for: {query}...")
        try:
            search_pubmed_and_pmc(config_path)
        except Exception as exc:
            print(f"  PubMed/PMC search failed: {exc}")

        print(f"Searching EuropePMC for: {query}...")
        try:
            search_europepmc(config_path)
        except Exception as exc:
            print(f"  EuropePMC search failed: {exc}")

        print(f"Searching Crossref for: {query}...")
        try:
            search_crossref(config_path)
        except Exception as exc:
            print(f"  Crossref search failed: {exc}")

        print(f"Searching OpenAlex for: {query}...")
        try:
            search_openalex(config_path)
        except Exception as exc:
            print(f"  OpenAlex search failed: {exc}")

    finally:
        if tmp_config.is_file():
            tmp_config.unlink()

    # Load and merge results from all sources
    merged_raw, source_stats = load_sources()
    if merged_raw.empty:
        print("Error: no results found from any source")
        return

    merged_raw = normalize_columns(merged_raw)
    dedup_df, dedup_stats = deduplicate(merged_raw)

    print(f"\nSearch results:")
    for stat in source_stats:
        if stat["exists"]:
            print(f"  {stat['source_file']}: {stat['raw_rows']} rows")
    print(f"  After dedup: {len(dedup_df)} unique papers")
    print()

    # Use dedup_df as our candidate DataFrame (instead of df from single source)
    df = dedup_df

    # ── Step 1b: Agent-driven scoring (optional) ──────────────────
    # The scoring_table.csv is produced by the Agent (Claude) after
    # reading harvest_candidates.jsonl.  If the user passes --papers-file,
    # use that for download ordering.  Otherwise fall back to search order.
    scored_records: list[dict[str, Any]] = []
    if args.papers_file:
        papers_path = Path(args.papers_file)
        if papers_path.is_file():
            import csv as _csv
            with papers_path.open("r", encoding="utf-8-sig") as f:
                reader = _csv.DictReader(f)
                scored_records = list(reader)
            print(f"Loaded {len(scored_records)} papers from {papers_path.name}")
            for r in scored_records:
                try:
                    r["relevance_score"] = int(r.get("relevance_score", 0))
                except (ValueError, TypeError):
                    r["relevance_score"] = 0
            scored_records.sort(key=lambda p: p.get("relevance_score", 0), reverse=True)
        else:
            print(f"Warning: papers file not found: {papers_path}")
    if not scored_records:
        scored_records = df.head(limit).to_dict(orient="records")

    # ── Step 1c: Output candidates CSV (for Agent scoring) ──────
    candidates_csv_path = run_root / "harvest_candidates.csv"
    if scored_records:
        cand_fields = ["title", "authors", "journal", "year", "doi", "pmid", "pmcid",
                        "abstract", "relevance_score"]
        cand_rows = []
        for r in scored_records:
            cand_rows.append({
                "title": r.get("title", ""),
                "authors": str(r.get("authors", "")),
                "journal": r.get("journal", ""),
                "year": r.get("year", ""),
                "doi": r.get("doi", ""),
                "pmid": r.get("pmid", ""),
                "pmcid": r.get("pmcid", ""),
                "abstract": (r.get("abstract", "") or "")[:500],
                "relevance_score": r.get("relevance_score", ""),
            })
        _write_csv(candidates_csv_path, cand_fields, cand_rows)

    # ── Fast path: --score-only (search only, no download) ──────
    if args.score_only:
        print(f"\nScore-only mode: candidates written to {candidates_csv_path}")
        print(f"Agent: read this file, score relevance, write scoring_table.csv,")
        print(f"then re-run with --papers-file scoring_table.csv --download")
        return

    # ── Step 2: Download (in score order) ────────────────────────
    download_results: list[DownloadResult] = []
    manual_queue: list[ManualDownloadItem] = []
    pdf_dir = run_root / "downloaded_pdfs"

    downloader = DownloadSession()
    # Share the same requests.Session so cookies from DOI redirects are preserved
    resolver = InstitutionalResolver(session=downloader.session) if args.institutional else None

    # Initialise browser ONCE, not per-paper (fixes the 300-popup issue)
    browser_downloader = None
    if args.browser_assisted:
        try:
            from literature_harvest.browser_downloader import BrowserDownloader
            browser_downloader = BrowserDownloader()
            print("Browser: Playwright ready")
        except ImportError:
            print("Browser: Playwright not installed (skipping)")

    for idx, row in enumerate(scored_records[:limit], start=1):
        doi = str(row.get("doi", "") or "")
        title = str(row.get("title", "") or "")
        url = str(row.get("pdf_url", "") or str(row.get("fulltext_url", "") or ""))
        landing = str(row.get("landing_page_url", "") or "")
        pmcid = str(row.get("pmcid", "") or "")
        pmid = str(row.get("pmid", "") or "")
        journal = str(row.get("journal", "") or "")
        authors = str(row.get("authors", "") or "")
        year = row.get("year", None)
        score = row.get("relevance_score", None)
        score_tag = f" [score={score}]" if score is not None else ""
        print(f"  [{idx}/{limit}]{score_tag} {title[:60]}... ", end="", flush=True)

        dr = DownloadResult(
            record_id=f"CLI-{idx:06d}",
            doi=doi,
            title=title,
        )

        # 2a: OA download — only PDF counts as final; HTML/XML are placeholders
        oa_urls = [u for u in [url, landing] if u.startswith("http")]
        downloaded = False
        oa_html_status = ""
        oa_html_path = ""
        oa_html_url = ""
        oa_html_format = ""

        for oa_url in oa_urls:
            out_path = pdf_dir / f"cli_{idx:06d}"
            dl_result = downloader.download_to_file(oa_url, out_path)
            status = dl_result["status"]
            if DownloadStatus.is_pdf_success(status):
                dr.download_status = status
                dr.final_pdf_path = dl_result["path"]
                dr.final_pdf_url = dl_result["url"]
                dr.content_format = "pdf"
                dr.access_route = "oa"
                downloaded = True
                print(f"✓ OA PDF (score={score})" if score else "✓ OA PDF")
                break
            elif status in ("html_saved", "xml_saved"):
                # Keep as fallback but don't stop — try resolver first
                oa_html_status = status
                oa_html_path = dl_result["path"]
                oa_html_url = dl_result["url"]
                oa_html_format = dl_result["content_format"]
                # Continue to try resolver before deciding it's "html_saved"

        if downloaded:
            ingest_result = process_downloaded_paper(
                {"record_id": dr.record_id, "doi": doi, "title": title, "path": dr.final_pdf_path},
                str(run_root),
            )
            dr.ingest_status = ingest_result
            download_results.append(dr)
            continue

        # 2b: Institutional resolver (tried even if OA returned HTML)
        if resolver and doi:
            resolve_result = resolver.resolve(doi, {"title": title})
            if resolve_result.status in ("oa_pdf_downloaded", "institution_pdf_downloaded"):
                if resolve_result.payload:
                    out_path = pdf_dir / f"cli_{idx:06d}.pdf"
                    out_path.write_bytes(resolve_result.payload)
                    if downloader.check_pdf_magic(out_path):
                        dr.download_status = resolve_result.status
                        dr.final_pdf_path = str(out_path.resolve())
                        dr.final_pdf_url = resolve_result.selected_pdf_url
                        dr.content_format = "pdf"
                        dr.access_route = "institutional"
                        dr.publisher = resolve_result.publisher
                        ingest_status = process_downloaded_paper(
                            {"record_id": dr.record_id, "doi": doi, "title": title, "path": dr.final_pdf_path},
                            str(run_root),
                        )
                        dr.ingest_status = ingest_status
                        print(f"✓ Institutional PDF (score={score})" if score else "✓ Institutional PDF")
                        download_results.append(dr)
                        continue
            # Not downloadable via resolver, but track the reason
            dr.download_status = resolve_result.status
            dr.failure_reason = resolve_result.reason
            dr.publisher = resolve_result.publisher
            print(f"Institutional: {resolve_result.reason[:40]}")

        # 2c: Browser-assisted (if enabled) — reuses one browser instance
        if browser_downloader is not None and doi and not downloaded:
            try:
                br_result = browser_downloader.download(
                    doi=doi,
                    landing_url=landing,
                    profile_dir=args.browser_profile_dir,
                    headless=not args.show_browser,
                    output_dir=str(pdf_dir),
                    session=downloader.session,
                )
                if DownloadStatus.is_pdf_success(br_result.download_status):
                    dr.download_status = br_result.download_status
                    dr.final_pdf_path = br_result.final_pdf_path
                    dr.final_pdf_url = br_result.final_pdf_url
                    dr.content_format = "pdf"
                    dr.access_route = "browser"
                    downloaded = True
                    ingest_status = process_downloaded_paper(
                        {"record_id": dr.record_id, "doi": doi, "title": title, "path": dr.final_pdf_path},
                        str(run_root),
                    )
                    dr.ingest_status = ingest_status
                    print(f"✓ Browser PDF (score={score})" if score else "✓ Browser PDF")
                    download_results.append(dr)
                    continue
                else:
                    dr.download_status = br_result.download_status
                    dr.failure_reason = br_result.failure_reason
                    print(f"  Browser: {br_result.failure_reason[:40]}")
            except ImportError:
                print("  Browser: Playwright not installed (skipping)")
            except Exception as exc:
                dr.download_status = "download_failed"
                dr.failure_reason = str(exc)
                print(f"  Browser error: {str(exc)[:40]}")

        if not downloaded:
            # All routes exhausted — fall back to OA HTML if we had it
            if oa_html_status:
                dr.download_status = oa_html_status
                dr.final_pdf_path = oa_html_path
                dr.final_pdf_url = oa_html_url
                dr.content_format = oa_html_format
                dr.access_route = "oa"
                dr.failure_reason = "no_pdf_available_oa_html_fallback"
                print(f"! OA only, no PDF — non-OA download failed (score={score})" if score else "! OA only, no PDF")
                downloaded = True
            else:
                print(f"! Non-OA — cannot auto-download (score={score})" if score else "! Non-OA — cannot auto-download")
                publisher_url = landing or f"https://doi.org/{doi}"
                manual_queue.append(ManualDownloadItem(
                    doi=doi,
                    title=title,
                    authors=authors,
                    year=year,
                    journal=journal,
                    publisher_url=publisher_url,
                    reason=dr.failure_reason or "no_auto_download_route",
                    suggested_action=f"Open {publisher_url} in browser → login via institution → download PDF → save to {pdf_dir}",
                ))

        download_results.append(dr)

    downloader.close()

    # ── Step 3: Write output files ─────────────────────────────
    candidates = df.head(limit).to_dict(orient="records")
    _write_jsonl(run_root / "harvest_candidates.jsonl", candidates)
    _write_jsonl(run_root / "download_status.jsonl", [r.to_dict() for r in download_results])

    # Summary
    summary = HarvestSummary.from_results(query, download_results, str(run_root))
    summary.query = query
    summary.started_at = started_at
    summary.finish()

    # Manual download queue
    queue_csv = run_root / "manual_download_queue.csv"
    if manual_queue:
        queue_fields = ["title", "authors", "year", "journal", "doi", "publisher_url",
                        "reason", "suggested_action"]
        _write_csv(queue_csv, queue_fields, [m.to_csv_row() for m in manual_queue])
        summary.manual_download_queue = str(queue_csv)

    # Write summary
    _write_json(run_root / "download_summary.json", summary.to_dict())

    # Failed downloads
    failed = [r.to_dict() for r in download_results
              if r.download_status in ("download_failed", "broken_link", "rate_limited",
                                        "publisher_blocked", "paywall_detected_no_entitlement")]
    if failed:
        failed_fields = list(failed[0].keys()) if failed else []
        _write_csv(run_root / "failed_downloads.csv", failed_fields, failed)

    print()
    print("=" * 60)
    print("Harvest complete")
    print(f"  Total candidates: {summary.total_candidates}")
    print(f"  OA PDF downloaded: {summary.oa_pdf_downloaded}")
    print(f"  Institutional PDF: {summary.institution_pdf_downloaded}")
    print(f"  Browser PDF: {summary.browser_pdf_downloaded}")
    print(f"  HTML saved (no PDF available): {summary.html_saved}")
    print(f"  Manual download required: {summary.manual_download_required}")
    print(f"  Failed: {summary.failed}")
    print()
    if summary.oa_pdf_downloaded > 0:
        print(f"  ✅ OA papers downloaded successfully: {summary.oa_pdf_downloaded}")
    if summary.institution_pdf_downloaded > 0 or summary.browser_pdf_downloaded > 0:
        total_non_oa = summary.institution_pdf_downloaded + summary.browser_pdf_downloaded
        print(f"  ✅ Non-OA papers downloaded via institutional/browser: {total_non_oa}")
    if summary.html_saved > 0:
        print(f"  ⚠️  {summary.html_saved} papers only have OA HTML (no PDF)")
    if summary.manual_download_required > 0:
        print(f"  ❌ {summary.manual_download_required} non-OA papers could not be auto-downloaded")
        print(f"     → See manual_download_queue.csv for the full list")
    if summary.failed > 0:
        print(f"  ❌ {summary.failed} downloads failed")
    print(f"  Output: {run_root}")


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume downloads from a previous harvest run."""
    from literature_harvest.download_session import DownloadSession
    from literature_harvest.ingest_hook import process_downloaded_paper
    from literature_harvest.institutional_resolver import InstitutionalResolver

    run_root = Path(args.run_root).resolve()
    pdf_dir = run_root / "downloaded_pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # Load existing status
    status_path = run_root / "download_status.jsonl"
    existing: list[dict[str, Any]] = []
    if status_path.is_file():
        with status_path.open("r") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing.append(json.loads(line))

    existing_ids = {r.get("record_id") for r in existing
                    if DownloadStatus.is_success(r.get("download_status", ""))
                    or (args.retry_failed and not DownloadStatus.is_success(r.get("download_status", "")))}
    # If retry_failed, also exclude previously failed items from blocking retry
    if args.retry_failed:
        existing_ids = {r.get("record_id") for r in existing
                        if DownloadStatus.is_pdf_success(r.get("download_status", ""))}

    # Load candidates
    candidates_path = run_root / "harvest_candidates.jsonl"
    if not candidates_path.is_file():
        print("Error: no harvest_candidates.jsonl found in", run_root)
        sys.exit(1)

    candidates: list[dict[str, Any]] = []
    with candidates_path.open("r") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    # Find candidates that need download
    pending = [c for c in candidates if c.get("id", c.get("record_id", "")) not in existing_ids]
    to_process = pending[:args.limit] if args.limit else pending

    print(f"Resuming: {len(to_process)} papers to download out of {len(candidates)} total")

    downloader = DownloadSession()
    resolver = InstitutionalResolver(session=downloader.session) if args.institutional else None

    # Initialise browser once
    browser_downloader = None
    if args.browser_assisted:
        try:
            from literature_harvest.browser_downloader import BrowserDownloader
            browser_downloader = BrowserDownloader()
            print("Browser: Playwright ready")
        except ImportError:
            print("Browser: Playwright not installed (skipping)")

    for idx, candidate in enumerate(to_process, start=1):
        doi = str(candidate.get("doi", "") or "")
        title = str(candidate.get("title", "") or "")
        url = str(candidate.get("pdf_url", "") or candidate.get("fulltext_url", "") or "")
        landing = str(candidate.get("landing_page_url", "") or "")
        print(f"  [{idx}/{len(to_process)}] {title[:60]}... ", end="", flush=True)

        dr = DownloadResult(
            record_id=f"resume-{idx:06d}",
            doi=doi,
            title=title,
        )
        downloaded = False

        # 1: OA download
        oa_urls = [u for u in [url, landing] if u.startswith("http")]
        for oa_url in oa_urls:
            out_path = pdf_dir / f"resume_{idx:06d}"
            dl_result = downloader.download_to_file(oa_url, out_path)
            status = dl_result["status"]
            if DownloadStatus.is_pdf_success(status):
                dr.download_status = status
                dr.final_pdf_path = dl_result["path"]
                dr.final_pdf_url = dl_result["url"]
                dr.content_format = "pdf"
                dr.access_route = "oa"
                downloaded = True
                print("✓ OA PDF")
                break
            elif DownloadStatus.is_success(status):
                dr.download_status = status
                dr.final_pdf_path = dl_result["path"]
                dr.final_pdf_url = dl_result["url"]
                dr.content_format = dl_result["content_format"]
                dr.access_route = "oa"

        # 2: Institutional resolver
        if not downloaded and doi and resolver:
            resolve_result = resolver.resolve(doi, {"title": title})
            if resolve_result.status in ("oa_pdf_downloaded", "institution_pdf_downloaded"):
                if resolve_result.payload:
                    out_path = pdf_dir / f"resume_{idx:06d}.pdf"
                    out_path.write_bytes(resolve_result.payload)
                    if downloader.check_pdf_magic(out_path):
                        dr.download_status = resolve_result.status
                        dr.final_pdf_path = str(out_path.resolve())
                        dr.final_pdf_url = resolve_result.selected_pdf_url
                        dr.content_format = "pdf"
                        dr.access_route = "institutional"
                        dr.publisher = resolve_result.publisher
                        downloaded = True
                        print("✓ Institutional PDF")
            elif not downloaded:
                dr.download_status = resolve_result.status
                dr.failure_reason = resolve_result.reason

        # 3: Browser-assisted
        if not downloaded and browser_downloader is not None and doi:
            try:
                br_result = browser_downloader.download(
                    doi=doi,
                    landing_url=landing,
                    profile_dir=args.browser_profile_dir,
                    headless=not args.show_browser,
                    output_dir=str(pdf_dir),
                    session=downloader.session,
                )
                if DownloadStatus.is_pdf_success(br_result.download_status):
                    dr.download_status = br_result.download_status
                    dr.final_pdf_path = br_result.final_pdf_path
                    dr.final_pdf_url = br_result.final_pdf_url
                    dr.content_format = "pdf"
                    dr.access_route = "browser"
                    downloaded = True
                    print("✓ Browser PDF")
                else:
                    dr.download_status = br_result.download_status
                    dr.failure_reason = br_result.failure_reason
                    print(f"Browser: {br_result.failure_reason[:40]}")
            except ImportError:
                print("Browser: Playwright not installed (skipping)")
            except Exception as exc:
                dr.download_status = "download_failed"
                dr.failure_reason = str(exc)
                print(f"Browser error: {str(exc)[:40]}")

        if not downloaded:
            print(f"Failed: {dr.failure_reason or 'no_auto_download_route'}")

        if DownloadStatus.is_pdf_success(dr.download_status):
            process_downloaded_paper(
                {"record_id": dr.record_id, "doi": doi, "title": title, "path": dr.final_pdf_path},
                str(run_root),
            )

    downloader.close()


def cmd_dedup(args: argparse.Namespace) -> None:
    """Deduplicate downloaded files in a run directory."""
    run_root = Path(args.run_root).resolve()
    pdf_dir = run_root / "downloaded_pdfs"
    if not pdf_dir.is_dir():
        print(f"Error: {pdf_dir} not found")
        sys.exit(1)

    from literature_harvest.ingest_hook import compute_sha256

    seen_hashes: set[str] = set()
    seen_dois: set[str] = set()
    kept = 0
    removed = 0

    for fpath in sorted(pdf_dir.iterdir()):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() != ".pdf":
            continue

        sha256 = compute_sha256(str(fpath))
        if sha256 in seen_hashes:
            fpath.unlink()
            removed += 1
            continue
        seen_hashes.add(sha256)
        kept += 1

    print(f"Dedup: {kept} kept, {removed} removed")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="literature-harvest — scholarly literature harvesting tool",
    )
    parser.add_argument("--email", default="", help="Email for API polite pool")

    sub = parser.add_subparsers(dest="command", required=True)

    # harvest
    hp = sub.add_parser("harvest", help="Run a full harvest (search + download + report)")
    hp.add_argument("query", help="Search query")
    hp.add_argument("--limit", type=int, default=10000, help="Max records (default 10000)")
    hp.add_argument("--download", action="store_true", help="Enable download")
    hp.add_argument("--institutional", action="store_true",
                    help="Enable institutional resolver fallback")
    hp.add_argument("--browser-assisted", action="store_true",
                    help="Enable Playwright browser-assisted download")
    hp.add_argument("--browser-profile-dir", default=None,
                    help="Path to persistent browser profile directory")
    hp.add_argument("--show-browser", action="store_true",
                    help="Show browser window during download (default: headless)")
    hp.add_argument("--output-root", default=None, help="Output root directory")
    hp.add_argument("--run-name", default=None, help="Run folder name")
    hp.add_argument("--papers-file", default=None,
                    help="Path to scoring_table.csv (produced by Agent) for score-ordered download")
    hp.add_argument("--score-only", action="store_true",
                    help="Search only — write harvest_candidates.jsonl for Agent scoring, skip download")
    hp.set_defaults(func=cmd_harvest)

    # resume
    rp = sub.add_parser("resume", help="Resume downloads from a previous run")
    rp.add_argument("--run-root", required=True, help="Path to the run directory")
    rp.add_argument("--retry-failed", action="store_true",
                    help="Retry previously failed downloads")
    rp.add_argument("--institutional", action="store_true",
                    help="Enable institutional resolver fallback")
    rp.add_argument("--browser-assisted", action="store_true",
                    help="Enable Playwright browser-assisted download")
    rp.add_argument("--browser-profile-dir", default=None,
                    help="Path to persistent browser profile directory")
    rp.add_argument("--show-browser", action="store_true",
                    help="Show browser window during download")
    rp.add_argument("--limit", type=int, default=None, help="Max records to process")
    rp.set_defaults(func=cmd_resume)

    # dedup
    dp = sub.add_parser("dedup", help="Deduplicate downloaded files")
    dp.add_argument("--run-root", required=True, help="Path to the run directory")
    dp.set_defaults(func=cmd_dedup)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
