from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any

import pandas as pd


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def detect_terms(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term.lower() in lowered]


def article_type_guess(title: str, publication_type: str) -> str:
    text = f"{title} {publication_type}".lower()
    if any(token in text for token in ["review", "systematic review", "meta-analysis"]):
        return "review"
    if any(token in text for token in ["editorial", "commentary", "news", "conference abstract", "patent"]):
        return "exclude_non_article"
    if any(token in text for token in ["journal article", "research article", "article"]):
        return "research_article"
    return "research_article_like"


def route_label(url: str) -> str:
    lowered = (url or "").lower()
    if "europepmc" in lowered:
        return "europe_pmc"
    if "pmc.ncbi.nlm.nih.gov" in lowered:
        return "pmc"
    if "doi.org" in lowered:
        return "doi_resolve"
    return "publisher_direct"


def candidate_urls(row: pd.Series, utils: Any) -> list[str]:
    urls: list[str] = []
    for key in ["pdf_url", "fulltext_url", "landing_page_url"]:
        value = utils.clean_text(row.get(key))
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(value)
    raw_json = utils.clean_text(row.get("candidate_urls_json"))
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str):
                        value = utils.clean_text(item)
                    elif isinstance(item, dict):
                        value = utils.clean_text(item.get("url"))
                    else:
                        value = ""
                    if value.startswith("http://") or value.startswith("https://"):
                        urls.append(value)
        except json.JSONDecodeError:
            pass
    doi = utils.normalize_doi(row.get("doi"))
    if doi:
        urls.append(f"https://doi.org/{doi}")
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def build_candidate_rows(raw_df: pd.DataFrame, config: dict[str, Any], utils: Any) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    include_terms = config.get("include_terms", [])
    secondary_terms = config.get("secondary_terms", [])
    exclude_terms = config.get("exclude_terms", [])
    exclude_reviews = bool(config.get("exclude_reviews_by_default", False))

    for idx, row in raw_df.reset_index(drop=True).iterrows():
        title = utils.clean_text(row.get("title"))
        abstract = utils.clean_text(row.get("abstract"))
        publication_type = utils.clean_text(row.get("publication_type"))
        query_name = utils.clean_text(row.get("query_name"))
        search_query = utils.clean_text(row.get("search_query"))
        evidence_text = " ".join(part for part in [title, abstract, publication_type] if part)
        query_text = " ".join(part for part in [query_name, search_query] if part)
        type_guess = article_type_guess(title, publication_type)
        include_hits = detect_terms(evidence_text, include_terms)
        secondary_hits = detect_terms(evidence_text, secondary_terms)
        exclude_hits = detect_terms(evidence_text, exclude_terms)
        query_hits = detect_terms(query_text, include_terms + secondary_terms)

        score = 0
        if include_hits:
            score += 2 + min(len(include_hits), 3)
        elif query_hits:
            score += 1
        if secondary_hits:
            score += min(len(secondary_hits), 2)
        if bool(row.get("open_access_flag")):
            score += 1
        if type_guess == "review":
            score -= 1
        if type_guess == "exclude_non_article":
            score -= 3
        if exclude_hits and not include_hits:
            score -= 2

        exclusion_reason = ""
        if not title:
            exclusion_reason = "missing_title"
        elif type_guess == "exclude_non_article":
            exclusion_reason = "non_article_type"
        elif exclude_reviews and type_guess == "review":
            exclusion_reason = "review_deprioritized"
        elif exclude_hits and not include_hits:
            exclusion_reason = "excluded_by_title_abstract_terms"
        elif not include_hits and not secondary_hits and not query_hits:
            exclusion_reason = "query_only_without_keyword_signal"
        elif score < 1:
            exclusion_reason = "low_relevance"

        priority = "high" if score >= 4 else ("medium" if score >= 2 else "low")
        rows.append(
            {
                "record_id": f"KWRAW-{idx + 1:06d}",
                "title": title,
                "authors": utils.clean_text(row.get("authors")),
                "year": row.get("year"),
                "journal": utils.clean_text(row.get("journal")),
                "doi": utils.clean_text(row.get("doi")),
                "source_database": utils.clean_text(row.get("source_database")),
                "abstract_if_available": abstract,
                "article_type_guess": type_guess,
                "keyword_include_hits": "; ".join(include_hits),
                "keyword_secondary_hits": "; ".join(secondary_hits),
                "keyword_exclude_hits": "; ".join(exclude_hits),
                "keyword_relevance_score": score,
                "research_article_flag": "yes" if type_guess in {"research_article", "research_article_like"} else "no",
                "likely_topic_tags": "; ".join(sorted(set(include_hits + secondary_hits))),
                "open_access_status_if_detectable": "open_access" if bool(row.get("open_access_flag")) else "not_detected",
                "pdf_url_candidate": utils.clean_text(row.get("pdf_url")) or utils.clean_text(row.get("fulltext_url")) or utils.clean_text(row.get("landing_page_url")),
                "landing_page_url": utils.clean_text(row.get("landing_page_url")),
                "download_status": "excluded" if exclusion_reason else "pending",
                "exclusion_reason_if_any": exclusion_reason,
                "query_name": query_name,
                "search_query": search_query,
                "source_record_id": utils.clean_text(row.get("source_record_id")),
                "candidate_urls_json": row.get("candidate_urls_json", "[]"),
                "pdf_url": utils.clean_text(row.get("pdf_url")),
                "fulltext_url": utils.clean_text(row.get("fulltext_url")),
                "publication_type": publication_type,
            }
        )
    return pd.DataFrame(rows)


def run_downloads(candidate_df: pd.DataFrame, run_root: Path, utils: Any, downloader: Any, config: dict[str, Any],
                  institutional: bool = False, browser_assisted: bool = False,
                  browser_profile_dir: str | None = None, headless: bool = True,
                  publisher_delay: float = 1.0) -> pd.DataFrame:
    pdf_dir = run_root / "downloaded_pdfs"
    log_dir = run_root / "download_logs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "keyword_research_download_log.csv"

    timeout_seconds = int(config.get("download", {}).get("timeout_seconds", 30))
    max_attempts = int(config.get("download", {}).get("max_attempts_per_record", 3))
    delay_seconds = float(config.get("delay_seconds", {}).get("download", 0.2))

    # Import new modules if institutional/browser mode is enabled
    institutional_resolver = None
    if institutional:
        try:
            from literature_harvest.institutional_resolver import InstitutionalResolver  # noqa: WPS433
            institutional_resolver = InstitutionalResolver(timeout=timeout_seconds, delay=publisher_delay)
        except ImportError:
            print("Warning: literature_harvest package not found; institutional resolver disabled")

    existing_log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()
    processed = set(existing_log.get("record_id", pd.Series(dtype=str)).astype(str))
    target_df = candidate_df.loc[
        candidate_df["exclusion_reason_if_any"].fillna("").eq("")
        & ~candidate_df["record_id"].astype(str).isin(processed)
    ].copy()

    rows: list[dict[str, Any]] = []
    for idx, (_, row) in enumerate(target_df.iterrows(), start=1):
        status = "metadata_only"
        reason = "no_candidate_url"
        final_path = ""
        final_url = ""
        access_route = "failed"
        content_format = ""
        attempts = 0

        for url in candidate_urls(row, utils)[:max_attempts]:
            attempts += 1
            try:
                response = downloader.attempt_download(url, timeout_seconds)
                payload = response["payload"]
                content_type = response["content_type"]
                final_url = response["final_url"] or url
                kind = downloader.classify_payload(payload, content_type)
                if kind == "html":
                    html_text = payload[:25000].decode("utf-8", errors="ignore")
                    if downloader.looks_paywalled(html_text):
                        status = "inaccessible"
                        reason = "paywall_detected"
                        access_route = route_label(final_url)
                        continue
                extension = ".pdf" if kind == "pdf" else utils.content_extension(content_type, final_url)
                if kind == "html":
                    extension = ".html"
                elif kind == "xml":
                    extension = ".xml"
                output = pdf_dir / f"{row['record_id']}_{utils.stable_file_stem(row)}{extension}"
                output.write_bytes(payload)
                status = "success"
                reason = ""
                final_path = str(output)
                access_route = route_label(final_url)
                content_format = kind
                break
            except urllib.error.HTTPError as exc:
                code = int(getattr(exc, "code", 0))
                status = "inaccessible" if code in {401, 402, 403} else ("broken_link" if code in {404, 410} else "metadata_only")
                if code == 429:
                    status = "rate_limited"
                reason = f"http_{code}"
                final_url = url
                access_route = route_label(url)
                if code == 429:
                    break
                continue
            except Exception as exc:  # noqa: BLE001
                status = "metadata_only"
                reason = type(exc).__name__
                final_url = url
                access_route = route_label(url)
                continue
            finally:
                time.sleep(delay_seconds)

        # ── Institutional resolver fallback ──────────────────────
        if status != "success" and institutional_resolver is not None:
            doi = utils.normalize_doi(row.get("doi"))
            if doi:
                resolve_result = institutional_resolver.resolve(doi, {"title": row.get("title")})
                if resolve_result.selected_pdf_url and resolve_result.status in (
                    "oa_pdf_downloaded", "institution_pdf_downloaded",
                ):
                    try:
                        dl_response = downloader.attempt_download(resolve_result.selected_pdf_url, timeout_seconds)
                        if dl_response["payload"].startswith(b"%PDF"):
                            output = pdf_dir / f"{row['record_id']}_{utils.stable_file_stem(row)}_institutional.pdf"
                            output.write_bytes(dl_response["payload"])
                            status = "institution_pdf_downloaded"
                            reason = "institutional_resolver"
                            final_path = str(output)
                            final_url = resolve_result.selected_pdf_url
                            access_route = "institutional"
                            content_format = "pdf"
                    except Exception:
                        pass
                if status.startswith("institution_") or resolve_result.status == "institution_login_required":
                    reason = resolve_result.reason or reason

        # ── Browser-assisted fallback ────────────────────────────
        if status != "success" and browser_assisted:
            doi = utils.normalize_doi(row.get("doi"))
            if doi:
                try:
                    from literature_harvest.browser_downloader import BrowserDownloader  # noqa: WPS433
                    browser = BrowserDownloader(timeout=timeout_seconds)
                    br_result = browser.download(
                        doi=doi,
                        landing_url=row.get("landing_page_url", ""),
                        profile_dir=browser_profile_dir,
                        headless=headless,
                        output_dir=str(pdf_dir / "browser_downloads"),
                    )
                    if br_result.download_status == "browser_pdf_downloaded":
                        status = "browser_pdf_downloaded"
                        reason = "browser_assisted"
                        final_path = br_result.final_pdf_path
                        final_url = br_result.final_pdf_url
                        access_route = "browser"
                        content_format = "pdf"
                except ImportError:
                    pass  # Playwright not installed
                except Exception:
                    pass

        # Map legacy status to new DownloadStatus for the output row
        download_status = status
        if status == "success":
            if content_format == "pdf":
                download_status = "oa_pdf_downloaded"
            elif content_format == "html":
                download_status = "html_saved"
            elif content_format == "xml":
                download_status = "xml_saved"
        elif status == "inaccessible":
            download_status = "paywall_detected_no_entitlement"
        elif status == "broken_link":
            download_status = "broken_link"

        rows.append(
            {
                "record_id": row["record_id"],
                "doi": row.get("doi"),
                "title": row.get("title"),
                "final_pdf_path": final_path,
                "final_pdf_url": final_url,
                "download_status": download_status,
                "failure_reason": reason,
                "access_route_used": access_route,
                "content_format": content_format,
                "attempt_count": attempts,
            }
        )
        if idx % 50 == 0:
            chunk = pd.DataFrame(rows)
            if log_path.exists():
                combined = pd.concat([pd.read_csv(log_path), chunk], ignore_index=True)
            else:
                combined = chunk
            combined = combined.drop_duplicates(subset=["record_id"], keep="last")
            combined.to_csv(log_path, index=False, encoding="utf-8-sig")
            rows = []

    if log_path.exists():
        combined = pd.concat([pd.read_csv(log_path), pd.DataFrame(rows)], ignore_index=True)
    else:
        combined = pd.DataFrame(rows)
    if not combined.empty:
        combined = combined.drop_duplicates(subset=["record_id"], keep="last")
    combined.to_csv(log_path, index=False, encoding="utf-8-sig")

    # ── Write structured output files ──────────────────────────
    _write_structured_outputs(run_root, rows)
    return combined


def _write_structured_outputs(run_root: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSONL and summary files for Agent consumption."""
    import json as _json

    # download_status.jsonl
    status_path = run_root / "download_status.jsonl"
    if rows:
        with status_path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(_json.dumps(r, ensure_ascii=False) + "\n")

    # manual_download_queue.csv
    manual = [r for r in rows if r.get("download_status") in (
        "manual_download_required", "paywall_detected_no_entitlement",
        "institution_login_required",
    )]
    if manual:
        import csv
        queue_path = run_root / "manual_download_queue.csv"
        manual_fields = ["title", "doi", "download_status", "failure_reason", "access_route_used", "final_pdf_url"]
        with queue_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=manual_fields)
            w.writeheader()
            for r in manual:
                w.writerow({k: r.get(k, "") for k in manual_fields})

    # download_summary.json
    from literature_harvest.status import DownloadStatus as DS
    summary = {
        "total_candidates": len(rows),
        "oa_pdf_downloaded": sum(1 for r in rows if r.get("download_status") == DS.OA_PDF_DOWNLOADED.value),
        "institution_pdf_downloaded": sum(1 for r in rows if r.get("download_status") == DS.INSTITUTION_PDF_DOWNLOADED.value),
        "browser_pdf_downloaded": sum(1 for r in rows if r.get("download_status") == DS.BROWSER_PDF_DOWNLOADED.value),
        "html_saved": sum(1 for r in rows if r.get("download_status") == DS.HTML_SAVED.value),
        "xml_saved": sum(1 for r in rows if r.get("download_status") == DS.XML_SAVED.value),
        "manual_download_required": sum(1 for r in rows if r.get("download_status") == DS.MANUAL_DOWNLOAD_REQUIRED.value),
        "failed": sum(1 for r in rows if r.get("download_status") in (
            DS.DOWNLOAD_FAILED.value, DS.BROKEN_LINK.value, DS.RATE_LIMITED.value,
            DS.PUBLISHER_BLOCKED.value,
        )),
        "duplicates": 0,
        "ingest_pending": 0,
    }
    summary_path = run_root / "download_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        _json.dump(summary, f, ensure_ascii=False, indent=2)


def write_summary(run_root: Path, candidate_df: pd.DataFrame, high_df: pd.DataFrame, medium_df: pd.DataFrame, log_df: pd.DataFrame) -> None:
    success = int(log_df["download_status"].eq("success").sum()) if not log_df.empty else 0
    pdf_count = int(log_df.loc[log_df["download_status"].eq("success"), "content_format"].fillna("").eq("pdf").sum()) if not log_df.empty else 0
    non_pdf = success - pdf_count
    pending = int(candidate_df["download_status"].eq("pending").sum())
    lines = [
        "# Keyword Research Harvest Summary",
        "",
        f"- Candidate rows: `{len(candidate_df)}`",
        f"- High-priority rows: `{len(high_df)}`",
        f"- Medium-priority rows: `{len(medium_df)}`",
        f"- Successful downloads/full texts: `{success}`",
        f"- True PDFs: `{pdf_count}`",
        f"- HTML/XML full texts: `{non_pdf}`",
        f"- Remaining pending: `{pending}`",
        f"- Download log: `{run_root / 'download_logs' / 'keyword_research_download_log.csv'}`",
    ]
    (run_root / "keyword_research_harvest_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", required=True, help="Parent folder where the new run folder should be created")
    parser.add_argument("--config", required=True, help="JSON config path")
    parser.add_argument("--run-name", required=True, help="New run folder name under literature_harvest")
    parser.add_argument("--skip-search", action="store_true")
    parser.add_argument("--institutional", action="store_true", help="Enable institutional resolver fallback for non-OA papers")
    parser.add_argument("--browser-assisted", action="store_true", help="Enable Playwright browser-assisted download")
    parser.add_argument("--browser-profile-dir", default=None, help="Path to persistent browser profile directory")
    parser.add_argument("--headless", action="store_true", default=True, help="Run browser headless (default: True)")
    parser.add_argument("--max-institutional-downloads", type=int, default=50, help="Max downloads via institutional route")
    parser.add_argument("--publisher-delay", type=float, default=1.0, help="Delay between publisher requests (seconds)")
    parser.add_argument("--rate-limit", type=int, default=3, help="Max requests per second")
    parser.add_argument("--resume", action="store_true", help="Resume previous run (skip already-downloaded)")
    args = parser.parse_args()

    output_root = Path(args.output_root).resolve()
    run_root = output_root / args.run_name
    run_root.mkdir(parents=True, exist_ok=True)
    os.environ["ASPERGILLUS_HARVEST_ROOT"] = str(run_root)

    skill_root = Path(__file__).resolve().parents[1]
    scripts_dir = skill_root / "literature_harvest" / "scripts"
    sys.path.insert(0, str(scripts_dir))

    from download_fulltexts import attempt_download, classify_payload, looks_paywalled  # noqa: WPS433
    from harvest_utils import ensure_directories, load_config, write_csv  # noqa: WPS433
    from merge_and_deduplicate import load_sources, normalize_columns  # noqa: WPS433
    from search_crossref import search_crossref  # noqa: WPS433
    from search_europepmc import search_europepmc  # noqa: WPS433
    from search_openalex import search_openalex  # noqa: WPS433
    from search_pubmed import search_pubmed_and_pmc  # noqa: WPS433
    import harvest_utils as utils  # noqa: WPS433

    config = load_json(Path(args.config))
    ensure_directories()

    if not args.skip_search:
        search_pubmed_and_pmc(args.config)
        search_europepmc(args.config)
        search_crossref(args.config)
        search_openalex(args.config)

    raw_df, _ = load_sources()
    raw_df = normalize_columns(raw_df)
    candidate_df = build_candidate_rows(raw_df, config, utils)
    candidate_df = candidate_df.sort_values(["keyword_relevance_score", "year"], ascending=[False, False], na_position="last").reset_index(drop=True)
    write_csv(candidate_df, run_root / "keyword_research_candidate_table.csv")

    high_df = candidate_df.loc[candidate_df["exclusion_reason_if_any"].eq("") & candidate_df["keyword_relevance_score"].ge(4)].copy()
    medium_df = candidate_df.loc[candidate_df["exclusion_reason_if_any"].eq("") & candidate_df["keyword_relevance_score"].between(2, 3)].copy()
    write_csv(high_df, run_root / "keyword_research_high_priority.csv")
    write_csv(medium_df, run_root / "keyword_research_medium_priority.csv")

    downloader = type(
        "DownloaderNamespace",
        (),
        {
            "attempt_download": staticmethod(attempt_download),
            "classify_payload": staticmethod(classify_payload),
            "looks_paywalled": staticmethod(looks_paywalled),
        },
    )
    log_df = run_downloads(
        candidate_df, run_root, utils, downloader, config,
        institutional=args.institutional,
        browser_assisted=args.browser_assisted,
        browser_profile_dir=args.browser_profile_dir,
        headless=args.headless,
        publisher_delay=args.publisher_delay,
    )

    status = log_df[["record_id", "download_status"]].drop_duplicates("record_id", keep="last")
    candidate_df = candidate_df.drop(columns=["download_status"], errors="ignore").merge(status, on="record_id", how="left")
    candidate_df["download_status"] = candidate_df["download_status"].fillna(candidate_df["exclusion_reason_if_any"].map(lambda x: "excluded" if x else "pending"))
    write_csv(candidate_df, run_root / "keyword_research_candidate_table.csv")
    write_summary(run_root, candidate_df, high_df, medium_df, log_df)


if __name__ == "__main__":
    main()
