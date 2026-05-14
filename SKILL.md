---
name: literature-harvest
description: Search scholarly databases for papers, download full texts using OA links or institutional access, deduplicate, and produce structured status reports for Agent consumption.
---

# literature-harvest — Scholarly Literature Harvesting Skill

Use this skill when the user wants to collect research papers on a topic,
download accessible full texts, and produce structured output for downstream
KB/RAG ingestion.

## Compliance Principles

1. **Only legitimate access.** This tool uses only the user's locally available,
   legally authorised access rights (campus IP, VPN, institutional proxy,
   browser login session).
2. **No paywall bypass.** No captcha bypass, account restriction bypass, or
   publisher access control evasion.
3. **No pirate sources.** No Sci-Hub, pirate PDF sources, or unauthorised mirrors.
4. **No credential theft.** No account credentials, passwords, cookies, or tokens
   are written to logs or output files.
5. **Rate limiting.** Batch downloads use low concurrency and low frequency to
   respect publisher access rules.
6. **Manual fallback.** Papers that cannot be auto-downloaded are clearly marked
   as `manual_download_required` and listed in a queue file.

## What this skill does

- Searches PubMed/PMC, Europe PMC, Crossref, and OpenAlex for a keyword set.
- Builds a deduplicated candidate table.
- Downloads PDF/HTML/XML full texts via OA URLs.
- **Optionally** falls back to an institutional resolver (requests.Session) that
  follows DOI → publisher redirects and extracts PDF links from landing pages
  using your local network entitlements.
- **Optionally** falls back to a Playwright browser session that opens the
  publisher page with your existing login cookies.
- Produces structured output files: `harvest_candidates.jsonl`,
  `download_status.jsonl`, `download_summary.json`, `manual_download_queue.csv`.
- Verifies downloaded PDFs, computes SHA-256, deduplicates, and marks papers
  for KB ingestion.

## Download statuses

| Status | Meaning |
|---|---|
| `oa_pdf_downloaded` | PDF obtained via open-access URL |
| `institution_pdf_downloaded` | PDF obtained via institutional resolver |
| `browser_pdf_downloaded` | PDF obtained via Playwright browser session |
| `html_saved` | HTML full-text page saved |
| `xml_saved` | XML full-text saved |
| `metadata_only` | No full text obtained |
| `institution_login_required` | Publisher shows login screen |
| `paywall_detected_no_entitlement` | Paywall without entitlement |
| `captcha_or_bot_check` | Captcha or bot check triggered |
| `manual_download_required` | Could not auto-download |
| `rate_limited` | Publisher rate-limited the request |
| `broken_link` | URL returned 404/410 |
| `duplicate_skipped` | Already present in local collection |
| `ingest_pending` | Downloaded, awaiting KB ingestion |
| `ingested_to_kb` | Ingested into knowledge base |
| `ingest_failed` | KB ingestion failed |

## Agent workflow (recommended)

The Agent (Claude) drives the workflow in two passes:

### Pass 1: Search + score

```bash
# 1. Search all sources, output candidates CSV (no download)
#    Use --limit to control how many papers to fetch per source (default 5000).
python -m literature_harvest harvest "your search query" --score-only

# 2. Agent reads harvest_candidates.csv and scores each paper's relevance
#    to the user's topic (0-100) based on title + abstract.
#    Then writes scoring_table.csv with columns:
#    relevance_score, title, authors, journal, doi, abstract_summary
```

### Pass 2: Download in score order

```bash
# 3. Download papers from highest score to lowest
python -m literature_harvest harvest "your search query" \
    --papers-file ./scoring_table.csv \
    --download --institutional

# Agent reads download_status.jsonl and tells the user:
# - Which OA papers were downloaded successfully (✅)
# - Which non-OA papers could not be auto-downloaded (❌)
# - Which papers need manual download (see manual_download_queue.csv)
```

### Other commands

```bash
# Basic harvest (search + download OA, no scoring)
python -m literature_harvest harvest "your search query" --download

# With institutional resolver
python -m literature_harvest harvest "your search query" --download --institutional

# With browser-assisted download
python -m literature_harvest harvest "your search query" --download --institutional --browser-assisted --browser-profile-dir ./browser_profile --show-browser

# Resume a previous run
python -m literature_harvest resume --run-root ./harvest_output/run_12345

# Deduplicate downloaded files
python -m literature_harvest dedup --run-root ./harvest_output/run_12345
```

## Legacy CLI (unchanged)

```bash
python scripts/run_keyword_harvest_no_dedup.py --output-root <folder> --config <config> --run-name <run>
python scripts/continue_download_and_dedup.py --run-root <folder>
```

The legacy scripts accept the same new `--institutional` / `--browser-assisted` flags.

## Output files

| File | Format | Contents |
|---|---|---|
| `harvest_candidates.jsonl` | JSONL | All candidate papers with metadata |
| `download_status.jsonl` | JSONL | Per-paper download result with DownloadStatus |
| `download_summary.json` | JSON | Aggregate statistics for Agent consumption |
| `manual_download_queue.csv` | CSV | Papers needing manual download |
| `failed_downloads.csv` | CSV | Failed downloads with reasons |
| `ingest_status.csv` | CSV | Per-paper ingest lifecycle status |

## Important notes for the Agent

- **Scoring is YOUR job.** After ``--score-only``, read ``harvest_candidates.csv``
  from the output directory, score each paper's relevance to the user's topic
  (0-100) using your own judgment, then write ``scoring_table.csv`` with columns:
  ``relevance_score, title, authors, journal, doi, abstract_summary``.
  Re-run with ``--papers-file scoring_table.csv --download``.
- **Download in score order.** ``--papers-file`` makes the CLI download from
  highest score first.
- **Report clearly.** After download, tell the user the exact count of:
  - ✅ OA PDF downloaded successfully
  - ✅ Non-OA PDF downloaded via institutional/browser access
  - ❌ Non-OA papers that could not be auto-downloaded
- **Do not claim a paper was "ingested"** unless `ingested_to_kb` is confirmed.
- **Do not claim a paper was "downloaded"** unless the status is one of
  `oa_pdf_downloaded`, `institution_pdf_downloaded`, or `browser_pdf_downloaded`.
- **Read `download_summary.json`** for a quick overview of the harvest run.
- **Read `manual_download_queue.csv`** for papers the user needs to get manually.
- **Do not retry `manual_download_required` papers** with the same method —
  they need a different access route.
- **Never log browser profile paths, cookies, or authentication tokens.**

## Dependencies

- Core: `requests`, `pandas`, `beautifulsoup4`, `lxml`
- Optional (browser mode): `playwright`

```bash
pip install literature-harvest[browser]
playwright install chromium
```

## Files in this skill

- `literature_harvest/` — Python package with all core modules
- `scripts/run_keyword_harvest_no_dedup.py` — Legacy CLI entry point
- `scripts/continue_download_and_dedup.py` — Resume/retry/dedup script
- `references/config_template.json` — Config template
- `references/prompt_template.md` — Reusable prompt for AI agents
