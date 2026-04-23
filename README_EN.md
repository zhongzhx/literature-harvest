# Keyword Literature Harvest Skill - User Guide (English)

## 1. What this is

This is a reusable local literature-harvesting toolkit for **any keyword set**.

It is designed to:

- search research literature by keyword
- build candidate metadata tables
- download legally accessible PDFs or full texts
- run a second-pass PDF chase from saved HTML pages
- deduplicate downloaded files

This package is **not restricted to Aspergillus**.  
You can reuse it for other topics by editing the query configuration.

## 2. What is included

Main contents of this folder:

- `SKILL.md`
  AI/agent-facing skill instructions
- `scripts/run_keyword_harvest_no_dedup.py`
  Starts a new keyword-based harvest run
- `scripts/continue_download_and_dedup.py`
  Continues unfinished downloads, runs HTML-to-PDF second pass, and deduplicates files
- `references/config_template.json`
  Main configuration template for queries and filtering
- `references/prompt_template.md`
  Prompt template for another AI/agent
- `literature_harvest/scripts/`
  Bundled dependency scripts so the package is portable

## 3. Requirements

Recommended environment:

- Windows
- PowerShell
- Python 3.13 or similar
- network access to PubMed, Europe PMC, Crossref, and OpenAlex

You do **not** need to prepare these in advance:

- `literature_harvest/`
- `search_pubmed.py`
- `download_fulltexts.py`

They are already bundled inside this package.

## 4. Basic workflow

### Step 1: Copy and edit the config file

Open:

- `references/config_template.json`

Usually you will edit:

- `queries`
- `include_terms`
- `secondary_terms`
- `exclude_terms`

Meaning:

- `queries` = actual search strings sent to the APIs
- `include_terms` = core topic terms you want to keep
- `secondary_terms` = useful supporting topic terms
- `exclude_terms` = terms you want to deprioritize or exclude

It is a good idea to save your edited file as a new config, for example:

- `my_topic_config.json`

## 5. Start a new harvest run

Command format:

```powershell
py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "<output folder>" --config "<config path>" --run-name "<run folder name>"
```

Example:

```powershell
py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "D:\literature_runs" --config ".\references\my_topic_config.json" --run-name "marine_fungal_metabolites_20260423"
```

This creates a new run folder under:

- `<output folder>\<run folder name>`

and writes:

- candidate table
- high-priority table
- medium-priority table
- download log
- downloaded files

## 6. Resume after interruption

Large runs may take a long time.  
If the process stops, continue with:

```powershell
py -3.13 .\scripts\continue_download_and_dedup.py --run-root "<run folder>" --retry-failed
```

Example:

```powershell
py -3.13 .\scripts\continue_download_and_dedup.py --run-root "D:\literature_runs\marine_fungal_metabolites_20260423" --retry-failed
```

This continuation script will:

1. continue unfinished downloads
2. try a second-pass PDF chase from HTML pages
3. deduplicate the downloaded files

## 7. Main output files

In a typical run folder you will see:

- `keyword_research_candidate_table.csv`
  full candidate list
- `keyword_research_high_priority.csv`
  high-priority records
- `keyword_research_medium_priority.csv`
  medium-priority records
- `downloaded_pdfs/`
  raw downloaded files
- `downloaded_pdfs_deduplicated/`
  deduplicated kept files
- `download_logs/keyword_research_download_log.csv`
  main download log
- `download_logs/keyword_research_html_second_pass.csv`
  second-pass HTML-to-PDF log
- `keyword_research_dedup_manifest.csv`
  deduplication manifest
- `keyword_research_harvest_summary.md`
  summary report

## 8. PDF vs HTML vs XML

Important:

- `success` does **not** always mean a PDF was downloaded
- some publishers only expose an HTML or XML full-text page
- only files ending in `.pdf`, or log rows with `content_format = pdf`, are true PDFs

So successful downloads may still be:

- PDF
- HTML
- XML

## 9. Deduplication logic

Deduplication is performed mainly by:

1. DOI
2. normalized title
3. file hash

The script tries to keep:

- PDF over HTML/XML
- the more complete/larger file when needed

## 10. Recommended usage strategy

If your goal is **maximum coverage**:

- keep the first pass broad
- do not over-filter too early
- collect metadata and downloads first
- filter more strictly later

If your goal is **cleaner and lower-noise retrieval**:

- tighten `include_terms`
- tighten `exclude_terms`
- use more specific query combinations

## 11. Common questions

### Why are many files HTML instead of PDF?

Because some sources expose only a web full-text page and not a direct PDF file.  
This toolkit saves legally accessible full text first, then attempts a second-pass PDF chase.

### Why are there duplicate papers?

Because the initial harvest is intentionally **no-dedup first** to maximize coverage.  
Deduplication is handled later by the continuation script.

### Why do some downloads fail?

Common reasons:

- 403 / subscription barrier
- landing page accessible but file link blocked
- page visible but PDF not openly available
- request timeout or network issue

Failures are logged explicitly instead of being silently discarded.

## 12. How to share with another person

You can send the entire `keyword-research-harvest` folder to someone else.

They only need to:

1. install Python
2. edit the config file
3. run the two commands

and they can perform:

- literature search
- download
- HTML-to-PDF second pass
- deduplication

