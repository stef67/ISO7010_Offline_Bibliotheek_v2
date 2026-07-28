#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

SVG_PATH_RE = re.compile(r"(^|/)pictograms/[^?#]+\.svg(?:\?[^#]*)?$", re.IGNORECASE)
SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class Record:
    code: str
    naam: str
    categorie: str
    bestand: str
    bron_url: str
    sha256: str


def safe_filename(url: str) -> str:
    name = Path(unquote(urlparse(url).path)).name
    name = SAFE_RE.sub("_", name).strip("._")
    return name or "pictogram.svg"


def code_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    m = re.search(r"(ISO_7010_[A-Z]\d{3}|ADR_[A-Za-z0-9.]+|GHS\d{2}|[A-Z]\d{3})", stem, re.I)
    return m.group(1).upper() if m else stem.upper()


def looks_like_svg(content: bytes, content_type: str = "") -> bool:
    head = content[:4096].lstrip().lower()
    return b"<svg" in head or "image/svg+xml" in content_type.lower()


def extract_links(html_text: str, base_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    found: dict[str, dict[str, str]] = {}

    for details in soup.select("details.category-group"):
        summary = details.find("summary")
        category = summary.get_text(" ", strip=True) if summary else "Onbekend"

        for card in details.select(".pictogram-card"):
            name_node = card.select_one(".pictogram-name")
            label = name_node.get_text(" ", strip=True) if name_node else ""

            hrefs = []
            for a in card.select('a[href$=".svg"], a[href*=".svg?"]'):
                hrefs.append(a.get("href", ""))
            for img in card.select('img[src$=".svg"], img[src*=".svg?"]'):
                hrefs.append(img.get("src", ""))

            for href in hrefs:
                if not href:
                    continue
                absolute = urljoin(base_url, href)
                path = urlparse(absolute).path
                if "/pictograms/" not in path.lower():
                    continue
                if not path.lower().endswith(".svg"):
                    continue

                filename = safe_filename(absolute)
                code = code_from_filename(filename)
                found[absolute] = {
                    "url": absolute,
                    "filename": filename,
                    "code": code,
                    "naam": label or code,
                    "categorie": category,
                }

    # Algemene fallback: alle pictograms/*.svg-links uit de pagina.
    if not found:
        for tag in soup.select("[href], [src]"):
            raw = tag.get("href") or tag.get("src") or ""
            absolute = urljoin(base_url, raw)
            path = urlparse(absolute).path
            if "/pictograms/" in path.lower() and path.lower().endswith(".svg"):
                filename = safe_filename(absolute)
                code = code_from_filename(filename)
                found[absolute] = {
                    "url": absolute,
                    "filename": filename,
                    "code": code,
                    "naam": tag.get("alt") or code,
                    "categorie": "Onbekend",
                }

    return list(found.values())


async def fetch_rendered_html(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1600, "height": 1000},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
        )
        await page.goto(url, wait_until="networkidle", timeout=120_000)
        await page.wait_for_timeout(4000)

        previous = 0
        for _ in range(30):
            height = await page.evaluate("document.body.scrollHeight")
            if height == previous:
                break
            previous = height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(500)

        content = await page.content()
        await browser.close()
        return content


def build_index(records: list[Record], output: Path, source_url: str) -> None:
    categories: dict[str, list[Record]] = {}
    for record in records:
        categories.setdefault(record.categorie, []).append(record)

    sections = []
    for category in sorted(categories):
        cards = []
        for item in sorted(categories[category], key=lambda x: (x.code, x.naam)):
            cards.append(f"""
<article class="card" data-search="{html.escape((item.code + ' ' + item.naam).lower())}">
  <img src="afbeeldingen/{html.escape(item.bestand)}" alt="{html.escape(item.naam)}">
  <strong>{html.escape(item.code)}</strong>
  <span>{html.escape(item.naam)}</span>
  <a href="afbeeldingen/{html.escape(item.bestand)}" download>SVG downloaden</a>
</article>""")
        sections.append(
            f"<section><h2>{html.escape(category)}</h2><div class='grid'>{''.join(cards)}</div></section>"
        )

    page = f"""<!doctype html>
<html lang="nl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SafetyForms SVG-pictogrammen</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font-family:Arial,Helvetica,sans-serif;background:#f3f4f6;color:#111}}
header{{background:#17365d;color:white;padding:24px;border-left:10px solid #c00000}}
main{{max-width:1400px;margin:auto;padding:20px}}
input{{width:100%;padding:12px;border:1px solid #aaa;border-radius:8px;font:inherit;margin:15px 0}}
h2{{color:#17365d;margin-top:30px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}
.card{{background:white;border:1px solid #ccc;border-radius:9px;padding:13px;display:grid;gap:8px}}
.card img{{width:100%;height:140px;object-fit:contain;background:#fafafa}}
.card strong{{color:#17365d}}
.card span{{font-size:13px}}
.card a{{color:#17365d;font-weight:700}}
.note{{font-size:13px;color:#444}}
</style>
</head>
<body>
<header>
<h1>SafetyForms SVG-pictogrammen</h1>
<p>{len(records)} unieke SVG-bestanden.</p>
</header>
<main>
<p class="note">Bron: <a href="{html.escape(source_url)}">{html.escape(source_url)}</a></p>
<input id="q" type="search" placeholder="Zoek op code of naam">
{''.join(sections)}
</main>
<script>
const q=document.getElementById('q');
q.addEventListener('input',()=>{{
 const s=q.value.toLowerCase().trim();
 document.querySelectorAll('.card').forEach(el=>{{
   el.style.display=(!s||el.dataset.search.includes(s))?'grid':'none';
 }});
}});
</script>
</body>
</html>"""
    (output / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    output = args.output.resolve()
    image_dir = output / "afbeeldingen"
    output.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            )
        }
    )

    print(f"Bronpagina ophalen: {args.url}", flush=True)
    response = session.get(args.url, timeout=60)
    response.raise_for_status()
    html_text = response.text
    links = extract_links(html_text, args.url)

    if not links:
        print("Geen SVG-links in gewone HTML; browser-rendering gebruiken.", flush=True)
        html_text = asyncio.run(fetch_rendered_html(args.url))
        links = extract_links(html_text, args.url)

    (output / "bronpagina.html").write_text(html_text, encoding="utf-8")

    if not links:
        print("Geen pictogramlinks gevonden.", file=sys.stderr)
        return 1

    print(f"{len(links)} unieke SVG-links gevonden.", flush=True)

    records: list[Record] = []
    failed: list[dict[str, str]] = []
    seen_hashes: set[str] = set()

    for index, item in enumerate(sorted(links, key=lambda x: x["filename"]), start=1):
        url = item["url"]
        try:
            r = session.get(url, headers={"Referer": args.url}, timeout=45)
            r.raise_for_status()
            if not looks_like_svg(r.content, r.headers.get("content-type", "")):
                raise RuntimeError("antwoord is geen SVG")

            digest = hashlib.sha256(r.content).hexdigest()
            if digest in seen_hashes:
                print(f"[{index}/{len(links)}] duplicaat overgeslagen: {item['filename']}", flush=True)
                continue
            seen_hashes.add(digest)

            target = image_dir / item["filename"]
            target.write_bytes(r.content)

            records.append(
                Record(
                    code=item["code"],
                    naam=item["naam"],
                    categorie=item["categorie"],
                    bestand=item["filename"],
                    bron_url=url,
                    sha256=digest,
                )
            )
            print(f"[{index}/{len(links)}] OK {item['filename']}", flush=True)

        except Exception as exc:
            failed.append({"url": url, "fout": str(exc)})
            print(f"[{index}/{len(links)}] FOUT {url}: {exc}", flush=True)

    records.sort(key=lambda x: (x.categorie, x.code, x.bestand))

    with (output / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump([asdict(r) for r in records], handle, ensure_ascii=False, indent=2)

    with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["code", "naam", "categorie", "bestand", "bron_url", "sha256"],
        )
        writer.writeheader()
        writer.writerows(asdict(r) for r in records)

    with (output / "fouten.json").open("w", encoding="utf-8") as handle:
        json.dump(failed, handle, ensure_ascii=False, indent=2)

    build_index(records, output, args.url)

    (output / "download_log.txt").write_text(
        "\n".join(
            [
                f"Bron: {args.url}",
                f"Unieke SVG-links: {len(links)}",
                f"Succesvol opgeslagen: {len(records)}",
                f"Mislukt: {len(failed)}",
            ]
        ),
        encoding="utf-8",
    )

    print(
        f"Klaar: {len(records)} opgeslagen, {len(failed)} mislukt.",
        flush=True,
    )
    return 0 if records else 1


if __name__ == "__main__":
    raise SystemExit(main())
