"""Check that the published demo works, the way a visitor would use it.

    python scripts/live_check.py                       # the default GitHub Pages address
    python scripts/live_check.py https://example.org/citeproof/ --crossref

It needs Playwright and Chromium (pip install playwright; playwright install chromium).

What it checks, in order, stopping at the first group that fails:
  1. every file the page needs is served (page, script, styles, Python, data, style files, icons);
  2. the checksum pinned in assets/app.js still matches the Pyodide file the CDN serves;
  3. in a real browser the engine loads, the "messy" example gives 4 verified / 3 mismatch /
     3 no verdict, and reformatting into APA produces a list;
  4. with --crossref, a DOI lookup against the real Crossref returns a record.

Exit status 0 means everything passed, 1 means something did not, with the reason printed.
Set PYODIDE_DIST to a local copy of the pinned release to run without reaching the CDN.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_URL = "https://seun-john.github.io/citeproof/"
CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/"
CTYPES = {
    ".js": "text/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".zip": "application/zip",
    ".whl": "application/zip",
}
MESSY_EXPECTED = ("4 of 10", "3 of 10", "3 of 10")


def fetch(url: str) -> tuple[int, bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "citeproof-live-check"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), response.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, b"", ""


def check_files(base: str) -> list[str]:
    problems = []
    status, html, _ = fetch(base)
    if status != 200:
        return [f"{base} answered HTTP {status}"]
    text = html.decode("utf-8", "replace")
    if "Content-Security-Policy" not in text:
        problems.append("the page has no Content-Security-Policy")
    paths = ["assets/app.js", "assets/app.css", "manifest.webmanifest", "py/engine-files.json"]
    paths += [f"py/{name}" for name in ("demo_logic.py", "text_references.py", "styles.py")]
    paths += [f"py/citeproof/{n}" for n in ("__init__", "core", "references", "bibtex", "claims")]
    paths = [p if "." in Path(p).name else p + ".py" for p in paths]
    paths += [f"data/{n}" for n in ("sample-catalogue.json", "sample-references-mixed.txt")]
    paths += ["assets/icon-192.png", "assets/icon-180.png"]
    status, manifest, _ = fetch(base + "py/engine-files.json")
    if status == 200:
        info = json.loads(manifest)
        paths += [f"py/{f}" for f in info["engine"]] + [f"csl/{f}" for f in info["csl"]]
    for path in paths:
        code, body, _ctype = fetch(base + path)
        if code != 200 or not body:
            problems.append(f"{path}: HTTP {code}")
    return problems


def check_checksum(base: str) -> list[str]:
    _, js, _ = fetch(base + "assets/app.js")
    pinned = re.search(r'PYODIDE_SRI = "sha384-([^"]+)"', js.decode("utf-8", "replace"))
    if not pinned:
        return ["could not find the pinned checksum in assets/app.js"]
    dist = os.environ.get("PYODIDE_DIST")
    if dist:
        body = (Path(dist) / "pyodide.js").read_bytes()
    else:
        status, body, _ = fetch(CDN + "pyodide.js")
        if status != 200:
            return [f"the CDN answered HTTP {status} for pyodide.js"]
    actual = base64.b64encode(hashlib.sha384(body).digest()).decode()
    if actual != pinned.group(1):
        return [f"pyodide.js checksum is {actual}, but the page pins {pinned.group(1)}"]
    return []


IOANNIDIS = (
    "Ioannidis, J. P. A. (2005). Why most published research findings are false. "
    "PLoS Medicine, 2(8), e124. https://doi.org/10.1371/journal.pmed.0020124"
)


def _serve_from(dist: str):  # type: ignore[no-untyped-def]
    """Answer the CDN's address from a local copy of the pinned release."""

    def serve(route):  # type: ignore[no-untyped-def]
        file = Path(dist) / route.request.url[len(CDN) :].split("?")[0]
        if not file.is_file():
            route.fulfill(status=404, body="missing")
            return
        headers = {
            "content-type": CTYPES.get(file.suffix, "application/octet-stream"),
            "access-control-allow-origin": "*",
        }
        route.fulfill(status=200, body=file.read_bytes(), headers=headers)

    return serve


def check_in_browser(base: str, crossref: bool) -> list[str]:
    from playwright.sync_api import sync_playwright

    problems: list[str] = []
    errors: list[str] = []
    dist = os.environ.get("PYODIDE_DIST")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("CHROMIUM_PATH") or None, args=["--no-sandbox"]
        )
        phone = {"viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}
        context = browser.new_context(**phone)
        if dist:
            context.route(CDN + "**", _serve_from(dist))
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(base)
        try:
            page.locator("#engine.ready").wait_for(timeout=180_000)
        except Exception:
            failed = page.locator("#engine-failed")
            text = page.inner_text("#engine-failed" if failed.is_visible() else "#engine")
            browser.close()
            return [f"the Python engine did not become ready: {text.strip()[:300]}"]
        page.uncheck("#crossref-on")
        page.uncheck("#search-on")
        page.tap("[data-sample='data/sample-references-messy.bib']")
        page.tap("#check-btn")
        page.locator(".tile").first.wait_for(timeout=60_000)
        kinds = ("verified", "metadata_mismatch", "no_verdict")
        counts = tuple(page.locator(f".tile.{k} .big").inner_text() for k in kinds)
        if counts != MESSY_EXPECTED:
            problems.append(f"the messy example gave {counts}, expected {MESSY_EXPECTED}")
        page.tap("[data-sample='data/sample-references-mixed.txt']")
        page.tap("#check-btn")
        page.locator(".tile").first.wait_for(timeout=60_000)
        page.locator("#reformat > summary").tap()
        page.tap("#reformat-go")
        try:
            page.locator(".bib li").first.wait_for(timeout=180_000)
            if page.locator(".bib li").count() < 5:
                problems.append("reformatting produced fewer than 5 references")
        except Exception:
            problems.append("reformatting produced no list (the style engine did not load)")
        if crossref:
            page.check("#crossref-on")
            page.fill("#refs", IOANNIDIS)
            page.tap("#check-btn")
            try:
                found = page.locator("#online-panel").get_by_text("Crossref returned a record")
                found.wait_for(timeout=60_000)
            except Exception:
                problems.append("the live Crossref DOI lookup did not return a record")
        if errors:
            problems.append(f"page errors: {errors[:3]}")
        browser.close()
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--crossref", action="store_true", help="also try one real Crossref lookup")
    args = parser.parse_args()
    base = args.url if args.url.endswith("/") else args.url + "/"
    steps = (
        ("files", lambda: check_files(base)),
        ("checksum", lambda: check_checksum(base)),
        ("browser", lambda: check_in_browser(base, args.crossref)),
    )
    for name, step in steps:
        problems = step()
        print(f"{'FAIL' if problems else 'ok  '} {name}")
        for problem in problems:
            print(f"     - {problem}")
        if problems:
            return 1
    print(f"All checks passed for {base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
