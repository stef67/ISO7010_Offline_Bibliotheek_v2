# SafetyForms SVG-downloader voor GitHub

Deze tool opent de dynamische pagina:

https://safetyforms.nl/Pictogrammen.php

met een echte Chromium-browser en verzamelt:

- SVG-links uit de DOM;
- SVG-netwerkresponses;
- lazy-loaded SVG's na volledig scrollen;
- verborgen `.svg`-paden uit HTML en JavaScript;
- inline SVG-elementen.

## Installatie

Kopieer naar je repository:

- `.github/workflows/download-safetyforms-svg.yml`
- `tools/download_safetyforms_svgs.py`

Commit en push naar `main`.

## Uitvoeren

1. Open **Actions**.
2. Kies **SafetyForms SVG-pictogrammen downloaden**.
3. Klik **Run workflow**.
4. Na afloop staan de bestanden onder:

```text
ISO7010/
├── afbeeldingen/
├── index.html
├── manifest.csv
├── manifest.json
├── download_log.txt
├── bronpagina.html
└── bronpagina.png
```

De workflow commit de resultaten automatisch. Daarnaast wordt een tijdelijk
workflow-artifact aangemaakt.

## Licentie

De bronpagina vermeldt dat alle pictogrammen onder de Creative Commons
CC0 1.0 Universal Public Domain Dedication beschikbaar zijn. Bewaar de bron-URL
en controleer de bronpagina opnieuw wanneer de inhoud of licentievermelding wijzigt.
