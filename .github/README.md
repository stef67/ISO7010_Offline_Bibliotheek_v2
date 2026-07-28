# Directe SafetyForms SVG-downloader

Deze versie leest uitsluitend de echte links uit de bronpagina, bijvoorbeeld:

```text
pictograms/ISO_7010_M001.svg
```

Daarmee wordt de correcte URL:

```text
https://safetyforms.nl/pictograms/ISO_7010_M001.svg
```

Er worden geen zelfverzonnen root-URL's meer geprobeerd.

## Installatie

Kopieer naar je repository:

- `.github/workflows/download-safetyforms-direct.yml`
- `tools/download_safetyforms_direct.py`

Commit en push naar `main`.

## Starten

1. Open **Actions**.
2. Kies **SafetyForms SVG-bibliotheek bijwerken**.
3. Klik **Run workflow**.

## Output

```text
ISO7010/
├── afbeeldingen/
├── index.html
├── manifest.csv
├── manifest.json
├── fouten.json
├── download_log.txt
└── bronpagina.html
```

De workflow commit de resultaten automatisch en maakt daarnaast een artifact.
