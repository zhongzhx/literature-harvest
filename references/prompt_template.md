Use the bundled keyword-harvest skill pipeline to run a new keyword-driven research-article harvest.

Requirements:

1. Build a new run folder under `<OUTPUT_ROOT>/`.
2. Do not overwrite previous runs.
3. Search PubMed/PMC, Europe PMC, Crossref, and OpenAlex.
4. Start with a no-dedup candidate table.
5. Download all legally accessible PDFs/full texts you can reach in the current network environment.
6. Save HTML/XML when PDF is not directly accessible.
7. After the main download pass, run an HTML second-pass to chase PDF links.
8. After downloading, build a deduplicated file folder and manifest.
9. Keep all metadata and download failures logged.

Input topic keywords:

- `<KEYWORD OR QUERY 1>`
- `<KEYWORD OR QUERY 2>`
- `<KEYWORD OR QUERY 3>`

Priority guidance:

- Prefer original research articles unless told otherwise.
- Keep metadata even when download fails.
- Do not silently discard inaccessible papers.
- Do not claim HTML/XML is PDF.

Deliverables:

- candidate table
- high-priority and medium-priority tables
- download log
- summary markdown
- downloaded raw file folder
- deduplicated file folder
- dedup manifest
