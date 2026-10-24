"""Headless-Chromium fixtures for the browser demo.

Pyodide comes from one pinned CDN URL. With PYODIDE_DIST set to a folder holding that exact
release (pyodide.js, the wasm, python_stdlib.zip, pyodide-lock.json and the sqlite3 wheel), the
CDN URL is answered from disk, so the tests run offline against the same files the page loads in
production. Without it the tests use the real CDN and skip if it cannot be reached.

Every request the page makes is recorded so tests can prove where data does and does not go.
"""

from __future__ import annotations

import functools
import glob
import http.server
import os
import threading
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent.parent
DOCS = ROOT / "docs"
CDN = "https://cdn.jsdelivr.net/pyodide/v0.29.5/full/"
CROSSREF = "https://api.crossref.org/"
CTYPES = {
    ".js": "text/javascript",
    ".wasm": "application/wasm",
    ".json": "application/json",
    ".zip": "application/zip",
    ".whl": "application/zip",
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # keep test output clean
        pass


@pytest.fixture(scope="session")
def site() -> Iterator[str]:
    handler = functools.partial(Quiet, directory=str(DOCS))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.fixture(scope="session")
def pyodide_dist() -> Path | None:
    configured = os.environ.get("PYODIDE_DIST")
    if configured:
        path = Path(configured)
        if not (path / "pyodide.js").is_file():
            pytest.skip(f"PYODIDE_DIST={configured} has no pyodide.js")
        return path
    try:
        urllib.request.urlopen(CDN + "pyodide.js", timeout=10).close()
    except OSError:
        pytest.skip("Set PYODIDE_DIST, or run with access to cdn.jsdelivr.net")
    return None


@pytest.fixture(scope="session")
def browser() -> Iterator[Any]:
    with sync_api.sync_playwright() as p:
        candidates = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))
        explicit = os.environ.get("CHROMIUM_PATH") or (candidates[-1] if candidates else None)
        try:
            launched = p.chromium.launch(executable_path=explicit, args=["--no-sandbox"])
        except Exception as exc:  # no browser installed
            pytest.skip(f"Chromium is not available: {exc}")
        yield launched
        launched.close()


class Session:
    """One browser page plus a log of everything it requested."""

    def __init__(self, page: Any, requests: list[Any], hooks: dict[str, Any]) -> None:
        self.page, self.requests, self.hooks = page, requests, hooks
        self.errors: list[str] = []
        page.on("pageerror", lambda e: self.errors.append(str(e)))

    def hosts(self) -> set[str]:
        return {urlparse(r.url).hostname for r in self.requests}

    def wait_ready(self) -> None:
        self.page.locator("#engine.ready").wait_for(timeout=120_000)

    def check(self, text: str | None = None) -> None:
        if text is not None:
            self.page.fill("#refs", text)
        self.page.click("#check-btn")


@pytest.fixture
def open_page(
    browser: Any, site: str, pyodide_dist: Path | None
) -> Iterator[Callable[..., Session]]:
    contexts: list[Any] = []

    def make(
        scheme: str = "light",
        width: int = 1100,
        height: int = 900,
        cdn: str = "serve",
        crossref: Callable[[Any], None] | None = None,
        wait: bool = True,
        online: bool = False,
    ) -> Session:
        ctx = browser.new_context(
            viewport={"width": width, "height": height},
            color_scheme=scheme,
            accept_downloads=True,
        )
        contexts.append(ctx)
        page = ctx.new_page()
        requests: list[Any] = []
        hooks: dict[str, Any] = {"blocked": []}
        page.on("request", lambda r: requests.append(r))

        def handle(route: Any) -> None:
            url = route.request.url
            if url.startswith(site):
                route.continue_()
            elif url.startswith(CDN):
                if cdn == "fail":
                    route.abort()
                elif pyodide_dist is None:
                    route.continue_()
                else:
                    name = url[len(CDN) :].split("?")[0]
                    file = pyodide_dist / name
                    if not file.is_file():
                        route.fulfill(status=404, body="missing")
                        return
                    body = file.read_bytes()
                    if cdn == "tamper" and name == "pyodide.js":
                        body += b"\n// tampered\n"
                    route.fulfill(
                        status=200,
                        body=body,
                        headers={
                            "content-type": CTYPES.get(file.suffix, "application/octet-stream"),
                            "access-control-allow-origin": "*",
                        },
                    )
            elif url.startswith(CROSSREF) and crossref is not None:
                crossref(route)
            else:
                hooks["blocked"].append(url)
                route.abort()

        ctx.route("**/*", handle)
        page.goto(site)
        session = Session(page, requests, hooks)
        if wait:
            session.wait_ready()
            if not online:  # the page ships with the Crossref lookups on; most tests need them off
                page.uncheck("#crossref-on")
                page.uncheck("#search-on")
        return session

    yield make
    for ctx in contexts:
        ctx.close()


@pytest.fixture
def shot() -> Callable[[Any, str, bool], None]:
    """Save a screenshot when SCREENSHOT_DIR is set (the viewport, or the whole page)."""
    target = os.environ.get("SCREENSHOT_DIR")

    def take(page: Any, name: str, full: bool = False) -> None:
        if target:
            Path(target).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(Path(target) / f"{name}.png"), full_page=full)

    return take
