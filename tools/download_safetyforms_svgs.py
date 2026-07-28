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
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Response

SVG_URL_RE = re.compile(
    r"""(?P<url>
        (?:https?:)?//[^\s"'<>]+?\.svg(?:\?[^\s"'<>]*)?
        |
        /[^\s"'<>]+?\.svg(?:\?[^\s"'<>]*)?
        |
        [A-Za-z0-9_./%+-]+\.svg(?:\?[^\s"'<>]*)?
    )""",
    re.IGNORECASE | re.VERBOSE,
)

SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(value: str, fallback: str = "pictogram") -> str:
    value = unquote(value).strip()
    value = Path(value.split("?", 1)[0]).name
    value = SAFE_RE.sub("_", value).strip("._")
    if not value:
        value = fallback
    if not value.lower().endswith(".svg"):
        value += ".svg"
    return value


def unique_path(folder: Path, filename: str, content: bytes) -> Path:
    target = folder / filename
    if not target.exists():
        return target
    if target.read_bytes() == content:
        return target
    stem = target.stem
    suffix = target.suffix
    digest = hashlib.sha256(content).hexdigest()[:10]
    return folder / f"{stem}_{digest}{suffix}"


def looks_like_svg(content: bytes, content_type: str = "") -> bool:
    head = content[:4096].lstrip().lower()
    return (
        b"<svg" in head
        or "image/svg+xml" in content_type.lower()
        or head.startswith(b"<?xml") and b"<svg" in head
    )


def title_from_svg(content: bytes, fallback: str) -> str:
    try:
        soup = BeautifulSoup(content, "xml")
        title = soup.find("title")
        if title and title.get_text(strip=True):
            return title.get_text(" ", strip=True)
    except Exception:
        pass
    return fallback


def build_index(records: list[dict[str, str]], output: Path, source_url: str) -> None:
    cards = []
    for item in sorted(records, key=lambda x: (x["naam"].lower(), x["bestand"].lower())):
        cards.append(
            f"""
<article class="card"
 data-search="{html.escape((item['naam'] + ' ' + item['bestand']).lower())}">
  <img src="afbeeldingen/{html.escape(item['bestand'])}" alt="{html.escape(item['naam'])}">
  <strong>{html.escape(item['naam'])}</strong>
  <small>{html.escape(item['bestand'])}</small>
  <a href="afbeeldingen/{html.escape(item['bestand'])}" download>SVG downloaden</a>
</article>"""
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
header{{background:#17365d;color:#fff;padding:24px;border-left:10px solid #c00000}}
main{{max-width:1400px;margin:auto;padding:20px}}
input{{width:100%;padding:12px;border:1px solid #aaa;border-radius:8px;font:inherit;margin:14px 0 20px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}}
.card{{background:#fff;border:1px solid #ccc;border-radius:9px;padding:13px;display:grid;gap:8px}}
.card img{{width:100%;height:140px;object-fit:contain;background:#fafafa}}
.card strong{{color:#17365d}}
.card small{{color:#666;overflow-wrap:anywhere}}
.card a{{color:#17365d;font-weight:700}}
.note{{font-size:13px;line-height:1.45;color:#444}}
</style>
</head>
<body>
<header>
<h1>SafetyForms SVG-pictogrammen</h1>
<p>{len(records)} lokaal opgeslagen SVG-bestanden.</p>
</header>
<main>
<p class="note">Bron: <a href="{html.escape(source_url)}">{html.escape(source_url)}</a>.
De bronpagina vermeldt dat de pictogrammen onder CC0 1.0 beschikbaar zijn.</p>
<input id="q" type="search" placeholder="Zoek op naam of bestandsnaam">
<section class="grid">
{''.join(cards)}
</section>
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


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    output = args.output.resolve()
    image_dir = output / "afbeeldingen"
    output.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)

    discovered_urls: set[str] = set()
    response_svgs: dict[str, bytes] = {}
    inline_svgs: list[tuple[str, bytes]] = []
    diagnostics: list[str] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            accept_downloads=True,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
            viewport={"width": 1600, "height": 1000},
        )
        page = await context.new_page()

        async def capture_response(response: Response) -> None:
            try:
                url = response.url
                content_type = (await response.header_value("content-type")) or ""
                if ".svg" in url.lower() or "image/svg+xml" in content_type.lower():
                    body = await response.body()
                    if looks_like_svg(body, content_type):
                        response_svgs[url] = body
                        discovered_urls.add(url)
            except Exception as exc:
                diagnostics.append(f"Response capture mislukt: {response.url}: {exc}")

        page.on("response", capture_response)

        print(f"Openen: {args.url}", flush=True)
        await page.goto(args.url, wait_until="networkidle", timeout=120_000)
        await page.wait_for_timeout(5_000)

        # Scroll volledig om lazy-loaded kaarten te activeren.
        previous_height = 0
        for _ in range(30):
            height = await page.evaluate("document.body.scrollHeight")
            if height == previous_height:
                break
            previous_height = height
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(700)
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1_000)

        # Alle DOM-attributen die een URL of bestandsnaam kunnen bevatten.
        dom_values = await page.eval_on_selector_all(
            "*",
            """els => els.flatMap(el => {
              const values = [];
              for (const a of el.attributes || []) {
                if (a.value) values.push(a.value);
              }
              return values;
            })""",
        )
        for value in dom_values:
            for match in SVG_URL_RE.finditer(value):
                discovered_urls.add(urljoin(page.url, match.group("url")))

        # Performance resources.
        resources = await page.evaluate(
            "performance.getEntriesByType('resource').map(x => x.name)"
        )
        for url in resources:
            if ".svg" in url.lower():
                discovered_urls.add(url)

        # Inline SVG's afzonderlijk opslaan.
        inline = await page.eval_on_selector_all(
            "svg",
            """svgs => svgs.map((svg, i) => ({
              markup: new XMLSerializer().serializeToString(svg),
              name: svg.getAttribute('id')
                 || svg.getAttribute('data-code')
                 || svg.getAttribute('aria-label')
                 || svg.closest('[data-code]')?.getAttribute('data-code')
                 || `inline_${i+1}`
            }))""",
        )
        for item in inline:
            content = item["markup"].encode("utf-8")
            if looks_like_svg(content):
                inline_svgs.append((safe_name(item["name"]), content))

        # HTML en geladen scripts doorzoeken op verborgen SVG-paden.
        html_content = await page.content()
        for match in SVG_URL_RE.finditer(html_content):
            discovered_urls.add(urljoin(page.url, match.group("url")))

        script_urls = await page.eval_on_selector_all(
            "script[src]", "els => els.map(x => x.src)"
        )
        session = requests.Session()
        session.headers.update({"User-Agent": await page.evaluate("navigator.userAgent")})
        for script_url in script_urls:
            try:
                resp = session.get(script_url, timeout=30)
                if resp.ok:
                    for match in SVG_URL_RE.finditer(resp.text):
                        discovered_urls.add(urljoin(script_url, match.group("url")))
            except Exception as exc:
                diagnostics.append(f"Script niet gelezen: {script_url}: {exc}")

        # Screenshot en HTML-dump voor diagnose als de bronstructuur wijzigt.
        await page.screenshot(path=str(output / "bronpagina.png"), full_page=True)
        (output / "bronpagina.html").write_text(html_content, encoding="utf-8")

        await browser.close()

    records: list[dict[str, str]] = []
    seen_hashes: set[str] = set()

    def save_svg(content: bytes, filename: str, source: str) -> None:
        digest = hashlib.sha256(content).hexdigest()
        if digest in seen_hashes:
            return
        seen_hashes.add(digest)

        target = unique_path(image_dir, safe_name(filename), content)
        target.write_bytes(content)
        fallback_name = target.stem.replace("_", " ")
        records.append(
            {
                "naam": title_from_svg(content, fallback_name),
                "bestand": target.name,
                "bron": source,
                "sha256": digest,
            }
        )
        print(f"Opgeslagen: {target.name}", flush=True)

    # Eerst SVG's die via browserresponses zijn onderschept.
    for url, content in response_svgs.items():
        save_svg(content, Path(urlparse(url).path).name or "pictogram.svg", url)

    # Daarna overige ontdekte URL's rechtstreeks downloaden.
    http = requests.Session()
    http.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124 Safari/537.36"
            ),
            "Referer": args.url,
        }
    )
    for url in sorted(discovered_urls):
        if url in response_svgs:
            continue
        try:
            response = http.get(url, timeout=45)
            response.raise_for_status()
            if looks_like_svg(response.content, response.headers.get("content-type", "")):
                save_svg(
                    response.content,
                    Path(urlparse(url).path).name or "pictogram.svg",
                    url,
                )
            else:
                diagnostics.append(f"Geen SVG-inhoud: {url}")
        except Exception as exc:
            diagnostics.append(f"Download mislukt: {url}: {exc}")

    # Ten slotte inline SVG's.
    for filename, content in inline_svgs:
        save_svg(content, filename, args.url + "#inline")

    # Manifesten.
    records.sort(key=lambda x: (x["naam"].lower(), x["bestand"].lower()))
    with (output / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)

    with (output / "manifest.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["naam", "bestand", "bron", "sha256"]
        )
        writer.writeheader()
        writer.writerows(records)

    build_index(records, output, args.url)

    (output / "download_log.txt").write_text(
        "\n".join(
            [
                f"Bron: {args.url}",
                f"Ontdekte SVG-URL's: {len(discovered_urls)}",
                f"Browserresponse-SVG's: {len(response_svgs)}",
                f"Inline SVG's: {len(inline_svgs)}",
                f"Unieke opgeslagen SVG's: {len(records)}",
                "",
                "Diagnostiek:",
                *diagnostics,
            ]
        ),
        encoding="utf-8",
    )

    if not records:
        print(
            "Geen SVG's gevonden. Controleer ISO7010/bronpagina.html, "
            "bronpagina.png en download_log.txt in het workflow-artifact.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    print(f"Klaar: {len(records)} unieke SVG's.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
