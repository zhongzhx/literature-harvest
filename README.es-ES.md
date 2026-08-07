

# Recopilación de Investigación de Palabras Clave

Una habilidad portátil y local para la recopilación de literatura dirigida a **cualquier conjunto de palabras clave**.

Este paquete incluye:

- scripts de búsqueda con la API `scholarly`
- generación de tablas de candidatos
- lógica de descarga de PDF / HTML / XML de fuentes legales
- seguimiento de segunda pasada de HTML a PDF
- deduplicación de archivos descargados
- documentación orientada a IA y a humanos

Está diseñado para que otro usuario pueda descargar este repositorio y ejecutarlo directamente sin necesidad de un proyecto `literature_harvest/` preexistente.

## Documentación incluida

- Guía de usuario en inglés: [README_EN.md](./README_EN.md)
- Guía de usuario en chino: [README_CN.md](./README_CN.md)
- Instrucciones de la habilidad para IA/agentes: [SKILL.md](./SKILL.md)

Versiones solo en texto:

- [README_EN.txt](./README_EN.txt)
- [README_CN.txt](./README_CN.txt)

## Scripts principales

- [scripts/run_keyword_harvest_no_dedup.py](./scripts/run_keyword_harvest_no_dedup.py)
- [scripts/continue_download_and_dedup.py](./scripts/continue_download_and_dedup.py)

Pila de dependencias incluidas:

- [literature_harvest/scripts/](./literature_harvest/scripts/)

## Inicio rápido

1. Copie y edite [references/config_template.json](./references/config_template.json).
2. Ejecute:

```powershell
py -3.13 .\scripts\run_keyword_harvest_no_dedup.py --output-root "<output folder>" --config "<config path>" --run-name "<run folder name>"
```

3. Reanude las descargas, ejecute la segunda pasada de HTML y deduplique:

```powershell
py -3.13 .\scripts\continue_download_and_dedup.py --run-root "<run folder>" --retry-failed
```

## Licencia

Este repositorio se publica bajo la [Licencia MIT](./LICENSE).
