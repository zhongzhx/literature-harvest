from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd


USER_AGENT = "keyword-research-harvest/0.1"
PAYWALL_MARKERS = [
    "subscription required",
    "purchase this article",
    "access through your institution",
    "institutional access",
    "paywall",
    "buy article",
    "rent this article",
]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("https://doi.org/", "").replace("http://doi.org/", "")
    text = text.replace("doi:", "").strip().rstrip(".")
    return text


def normalize_title(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def content_extension(content_type: str, url: str) -> str:
    lowered_type = clean_text(content_type).lower()
    lowered_url = url.lower()
    if "pdf" in lowered_type or lowered_url.endswith(".pdf"):
        return ".pdf"
    if "xml" in lowered_type or lowered_url.endswith(".xml"):
        return ".xml"
    if "html" in lowered_type or lowered_type.startswith("text/"):
        return ".html"
    return ".bin"


def classify_payload(payload: bytes, content_type: str) -> str:
    sample = payload[:3000].decode("utf-8", errors="ignore").lower()
    if payload.startswith(b"%PDF") or "pdf" in content_type.lower():
        return "pdf"
    if "xml" in content_type.lower() or sample.lstrip().startswith("<?xml"):
        return "xml"
    if "html" in content_type.lower() or "<html" in sample:
        return "html"
    return "other"


def looks_paywalled(payload: bytes) -> bool:
    text = payload[:50000].decode("utf-8", errors="ignore").lower()
    return any(marker in text for marker in PAYWALL_MARKERS)


def request_url(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf, application/xml, text/xml, text/html;q=0.9, */*;q=0.1",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        return {
            "payload": response.read(),
            "content_type": clean_text(response.headers.get("Content-Type")).lower(),
            "final_url": clean_text(response.geturl()) or url,
        }


def candidate_urls(row: pd.Series) -> list[str]:
    urls: list[str] = []
    for key in ["pdf_url", "fulltext_url", "landing_page_url", "pdf_url_candidate"]:
        value = clean_text(row.get(key))
        if value.startswith("http://") or value.startswith("https://"):
            urls.append(value)
    raw_json = clean_text(row.get("candidate_urls_json"))
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str):
                        value = clean_text(item)
                    elif isinstance(item, dict):
                        value = clean_text(item.get("url"))
                    else:
                        value = ""
                    if value.startswith("http://") or value.startswith("https://"):
                        urls.append(value)
        except json.JSONDecodeError:
            pass
    doi = normalize_doi(row.get("doi"))
    if doi:
        urls.append(f"https://doi.org/{doi}")
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def request_row_download(row: pd.Series, pdf_dir: Path, timeout: int, max_attempts: int) -> dict[str, Any]:
    stem = clean_text(row.get("record_id"))
    status = "metadata_only"
    reason = "no_candidate_url"
    final_path = ""
    final_url = ""
    content_format = ""
    attempts = 0
    for url in candidate_urls(row)[:max_attempts]:
        attempts += 1
        try:
            response = request_url(url, timeout)
            payload = response["payload"]
            final_url = response["final_url"] or url
            kind = classify_payload(payload, response["content_type"])
            if kind == "html" and looks_paywalled(payload):
                status = "inaccessible"
                reason = "paywall_detected"
                continue
            extension = ".pdf" if kind == "pdf" else content_extension(response["content_type"], final_url)
            if kind == "html":
                extension = ".html"
            elif kind == "xml":
                extension = ".xml"
            output = pdf_dir / f"{stem}{extension}"
            output.write_bytes(payload)
            status = "success"
            reason = ""
            final_path = str(output)
            content_format = kind
            break
        except urllib.error.HTTPError as exc:
            code = int(getattr(exc, "code", 0))
            status = "inaccessible" if code in {401, 402, 403} else ("broken_link" if code in {404, 410} else "metadata_only")
            if code == 429:
                status = "rate_limited"
            reason = f"http_{code}"
            final_url = url
            if code == 429:
                break
            continue
        except Exception as exc:  # noqa: BLE001
            status = "metadata_only"
            reason = type(exc).__name__
            final_url = url
            continue
        finally:
            time.sleep(0.15)
    return {
        "record_id": row.get("record_id"),
        "doi": row.get("doi"),
        "title": row.get("title"),
        "final_pdf_path": final_path,
        "final_pdf_url": final_url,
        "download_status": status,
        "failure_reason": reason,
        "content_format": content_format,
        "attempt_count": attempts,
    }


def extract_pdf_links(html_text: str, bases: list[str]) -> list[str]:
    values: list[str] = []
    for pattern in [
        r"""href=["']([^"']+(?:\.pdf|pdf=|/pdf/|download[^"']*pdf)[^"']*)["']""",
        r"""content=["']([^"']+(?:\.pdf|pdf=|/pdf/)[^"']*)["']""",
    ]:
        values.extend(re.findall(pattern, html_text, flags=re.IGNORECASE))
    links: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = html.unescape(value.strip())
        if not value:
            continue
        for base in bases or [""]:
            resolved = urllib.parse.urljoin(base, value) if base else value
            if resolved.startswith("http://") or resolved.startswith("https://"):
                if resolved not in seen:
                    seen.add(resolved)
                    links.append(resolved)
                break
    return links


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--timeout", type=int, default=35)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    candidate_path = run_root / "keyword_research_candidate_table.csv"
    pdf_dir = run_root / "downloaded_pdfs"
    log_dir = run_root / "download_logs"
    log_path = log_dir / "keyword_research_download_log.csv"
    second_pass_path = log_dir / "keyword_research_html_second_pass.csv"
    dedup_dir = run_root / "downloaded_pdfs_deduplicated"
    manifest_path = run_root / "keyword_research_dedup_manifest.csv"

    pdf_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    dedup_dir.mkdir(parents=True, exist_ok=True)

    candidate_df = pd.read_csv(candidate_path)
    log_df = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()
    success_ids = set(log_df.loc[log_df.get("download_status", pd.Series(dtype=str)).eq("success"), "record_id"].astype(str)) if not log_df.empty else set()
    processed_ids = set(log_df.get("record_id", pd.Series(dtype=str)).astype(str)) if not log_df.empty else set()

    if args.retry_failed:
        target = candidate_df.loc[candidate_df["exclusion_reason_if_any"].fillna("").eq("") & ~candidate_df["record_id"].astype(str).isin(success_ids)].copy()
    else:
        target = candidate_df.loc[candidate_df["exclusion_reason_if_any"].fillna("").eq("") & ~candidate_df["record_id"].astype(str).isin(processed_ids)].copy()

    rows: list[dict[str, Any]] = []
    for idx, (_, row) in enumerate(target.iterrows(), start=1):
        rows.append(request_row_download(row, pdf_dir, args.timeout, args.max_attempts))
        if idx % 50 == 0:
            chunk = pd.DataFrame(rows)
            if log_path.exists():
                out = pd.concat([pd.read_csv(log_path), chunk], ignore_index=True)
            else:
                out = chunk
            out = out.drop_duplicates(subset=["record_id"], keep="last")
            out.to_csv(log_path, index=False, encoding="utf-8-sig")
            rows = []
    if rows:
        if log_path.exists():
            out = pd.concat([pd.read_csv(log_path), pd.DataFrame(rows)], ignore_index=True)
        else:
            out = pd.DataFrame(rows)
        out = out.drop_duplicates(subset=["record_id"], keep="last")
        out.to_csv(log_path, index=False, encoding="utf-8-sig")

    # HTML second pass
    second_rows: list[dict[str, Any]] = []
    html_files = [p for p in pdf_dir.iterdir() if p.is_file() and p.suffix.lower() in {".html", ".htm"}]
    done_second = set(pd.read_csv(second_pass_path)["record_id"].astype(str)) if second_pass_path.exists() else set()
    meta = candidate_df.set_index("record_id", drop=False)
    for idx, path in enumerate(html_files, start=1):
        record_id = path.stem.split("_")[0]
        if record_id in done_second:
            continue
        row = meta.loc[record_id] if record_id in meta.index else pd.Series({"record_id": record_id})
        html_text = path.read_text(encoding="utf-8", errors="ignore")
        links = extract_pdf_links(html_text, candidate_urls(row))
        status = "no_pdf_link_found"
        out_path = ""
        selected_url = ""
        for link in links[: args.max_attempts]:
            try:
                response = request_url(link, args.timeout)
                if classify_payload(response["payload"], response["content_type"]) == "pdf":
                    dst = pdf_dir / f"{path.stem}_secondary.pdf"
                    dst.write_bytes(response["payload"])
                    status = "pdf_downloaded"
                    out_path = str(dst)
                    selected_url = response["final_url"] or link
                    break
            except Exception:  # noqa: BLE001
                continue
            finally:
                time.sleep(0.1)
        second_rows.append(
            {
                "record_id": record_id,
                "source_html_path": str(path),
                "second_pass_status": status,
                "secondary_pdf_path": out_path,
                "selected_pdf_url": selected_url,
            }
        )
        if idx % 50 == 0:
            chunk = pd.DataFrame(second_rows)
            if second_pass_path.exists():
                out = pd.concat([pd.read_csv(second_pass_path), chunk], ignore_index=True)
            else:
                out = chunk
            out = out.drop_duplicates(subset=["record_id"], keep="last")
            out.to_csv(second_pass_path, index=False, encoding="utf-8-sig")
            second_rows = []
    if second_rows:
        if second_pass_path.exists():
            out = pd.concat([pd.read_csv(second_pass_path), pd.DataFrame(second_rows)], ignore_index=True)
        else:
            out = pd.DataFrame(second_rows)
        out = out.drop_duplicates(subset=["record_id"], keep="last")
        out.to_csv(second_pass_path, index=False, encoding="utf-8-sig")

    # Dedup
    file_rows: list[dict[str, Any]] = []
    meta = candidate_df.set_index("record_id", drop=False)
    for path in pdf_dir.iterdir():
        if not path.is_file():
            continue
        record_id = path.name.split("_")[0]
        row = meta.loc[record_id] if record_id in meta.index else pd.Series({})
        file_rows.append(
            {
                "record_id": record_id,
                "source_path": str(path),
                "filename": path.name,
                "extension": path.suffix.lower(),
                "sha256": sha256_file(path),
                "doi": normalize_doi(row.get("doi")),
                "title_normalized": normalize_title(row.get("title")),
            }
        )
    manifest = pd.DataFrame(file_rows)
    if not manifest.empty:
        keep_by_group: dict[str, str] = {}
        for _, row in manifest.iterrows():
            key = f"doi:{row['doi']}" if row["doi"] else (f"title:{row['title_normalized']}" if row["title_normalized"] else f"hash:{row['sha256']}")
            current = keep_by_group.get(key)
            if current is None:
                keep_by_group[key] = row["source_path"]
            else:
                current_path = Path(current)
                new_path = Path(row["source_path"])
                current_rank = (0 if current_path.suffix.lower() == ".pdf" else 1, -current_path.stat().st_size)
                new_rank = (0 if new_path.suffix.lower() == ".pdf" else 1, -new_path.stat().st_size)
                if new_rank < current_rank:
                    keep_by_group[key] = row["source_path"]
            manifest.loc[manifest.index == row.name, "dedup_group_key"] = key
        manifest["dedup_decision"] = manifest["source_path"].map(lambda p: "keep" if p in set(keep_by_group.values()) else "duplicate")
        for _, row in manifest.loc[manifest["dedup_decision"].eq("keep")].iterrows():
            src = Path(row["source_path"])
            dst = dedup_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
    manifest.to_csv(manifest_path, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
