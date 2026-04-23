# Keyword Research Harvest

A portable local literature-harvesting skill for **any keyword set**.

This package bundles:

- scholarly API search scripts
- candidate table generation
- legal PDF / HTML / XML download logic
- HTML-to-PDF second-pass chasing
- downloaded-file deduplication
- AI-facing and human-facing documentation

It is designed so another user can download this repository and run it directly without needing a pre-existing `literature_harvest/` project.

## Included documentation

- English user guide: [README_EN.md](./README_EN.md)
- Chinese user guide: [README_CN.md](./README_CN.md)
- AI/agent skill instructions: [SKILL.md](./SKILL.md)

Text-only versions:

- [README_EN.txt](./README_EN.txt)
- [README_CN.txt](./README_CN.txt)

## Main scripts

- [scripts/run_keyword_harvest_no_dedup.py](./scripts/run_keyword_harvest_no_dedup.py)
- [scripts/continue_download_and_dedup.py](./scripts/continue_download_and_dedup.py)

Bundled dependency stack:

- [literature_harvest/scripts/](./literature_harvest/scripts/)

## Quick start

1. Copy and edit [references/config_template.json](./references/config_template.json).
2. Run:

```powershell
py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "<output folder>" --config "<config path>" --run-name "<run folder name>"
```

3. Resume downloads, run HTML second-pass, and deduplicate:

```powershell
py -3.13 .\scripts\continue_download_and_dedup.py --run-root "<run folder>" --retry-failed
```

## License

This repository is released under the [MIT License](./LICENSE).
