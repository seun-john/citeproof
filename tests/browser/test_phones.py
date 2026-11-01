"""The page on phones: emulated devices with touch, notches, landscape and large text.

Chromium emulates the screen, touch and user agent. It is not Safari or a real phone, so this
catches layout and touch-size problems but not engine-specific ones. docs/phone-test-checklist.md
covers what a person should still try on a real phone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import expect

DOCS = Path(__file__).resolve().parent.parent.parent / "docs"
DATA = DOCS / "data"

IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)


def phone(width: int, height: int, scale: float, ua: str) -> tuple[int, int, dict[str, Any]]:
    return (
        width,
        height,
        {
            "device_scale_factor": scale,
            "is_mobile": True,
            "has_touch": True,
            "user_agent": ua,
        },
    )


DEVICES = {
    "iphone-se": phone(375, 667, 2, IPHONE_UA),
    "iphone-14-pro": phone(393, 852, 3, IPHONE_UA),
    "pixel-7": phone(412, 915, 2.625, ANDROID_UA),
    "small-android": phone(320, 568, 2, ANDROID_UA),
    "galaxy-fold-cover": phone(280, 653, 3, ANDROID_UA),
    "iphone-landscape": phone(844, 390, 3, IPHONE_UA),
    "ipad-portrait": phone(768, 1024, 2, IPHONE_UA),
}

HERE = Path(__file__).resolve().parent
TAP_TARGETS = (HERE / "tap_targets.js").read_text(encoding="utf-8")


def overflow(page: Any) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def off_screen(page: Any, selector: str) -> list[str]:
    """Elements matching selector that stick out past the right edge of the screen."""
    return page.evaluate((HERE / "off_screen.js").read_text(encoding="utf-8"), selector)


@pytest.fixture(params=list(DEVICES))
def phone_session(request: Any, open_page: Any) -> Any:
    width, height, device = DEVICES[request.param]
    session = open_page(width=width, height=height, device=device)
    session.device_name = request.param
    return session


def test_start_screen_fits_and_is_touch_friendly(phone_session: Any) -> None:
    s = phone_session
    page = s.page
    assert overflow(page) <= 0, (s.device_name, off_screen(page, "body *"))
    assert page.evaluate("matchMedia('(pointer: coarse)').matches")
    size = page.locator("#refs").evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
    assert size >= 16, "iOS zooms into inputs smaller than 16px"
    for selector in ("#style-pick",):
        if page.locator(selector).count():
            assert (
                page.locator(selector).evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
                >= 16
            )
    assert page.locator("#check-btn").bounding_box()["height"] >= 44
    assert page.locator("h1").is_visible() and page.locator("#refs").is_visible()
    assert page.locator("#check-btn").bounding_box()["width"] <= page.viewport_size["width"]
    small = page.evaluate(TAP_TARGETS)
    assert small == [], (s.device_name, small)


def test_results_fit_and_everything_is_tappable(phone_session: Any) -> None:
    s = phone_session
    page = s.page
    page.tap("[data-sample='data/sample-references-messy.bib']")
    expect(page.locator("#refs")).not_to_have_value("")
    page.tap("#check-btn")
    expect(page.locator(".tile")).to_have_count(3)
    assert overflow(page) <= 0, (s.device_name, off_screen(page, "main *"))
    for tile in page.locator(".tile").all():
        box = tile.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= page.viewport_size["width"] + 0.5
    # All three rates are readable on one row, as the brief asks for no-verdict to be as visible
    # as verified.
    tops = {round(t.bounding_box()["y"]) for t in page.locator(".tile").all()}
    assert len(tops) == 1 or s.device_name == "galaxy-fold-cover", tops
    page.locator("details.more summary").first.tap()
    assert overflow(page) <= 0
    assert page.evaluate(TAP_TARGETS) == [], s.device_name


def test_long_unbroken_text_wraps_instead_of_pushing_the_page_sideways(phone_session: Any) -> None:
    s = phone_session
    long_doi = "10.1234/" + "a-very-long-doi-segment-" * 6
    long_title = "Supercalifragilisticexpialidocious" * 4
    s.page.fill(
        "#refs",
        f"Smith, J. ({2020}). {long_title}. Journal of Things, 4(2), 1-10. "
        f"https://doi.org/{long_doi}",
    )
    s.page.tap("#check-btn")
    expect(s.page.locator(".tile")).to_have_count(3)
    s.page.locator("details.more summary").first.tap()
    assert overflow(s.page) <= 0, (s.device_name, off_screen(s.page, "main *"))


def test_reformat_and_the_crossref_panels_fit(open_page: Any) -> None:
    def crossref(route: Any) -> None:
        route.fulfill(
            status=200,
            headers={"access-control-allow-origin": "*", "content-type": "application/json"},
            body=json.dumps({"message": {"items": []}}),
        )

    width, height, device = DEVICES["small-android"]
    s = open_page(width=width, height=height, device=device, online=True, crossref=crossref)
    s.page.tap("[data-sample='data/sample-references-mixed.txt']")
    s.page.tap("#check-btn")
    expect(s.page.locator(".tile")).to_have_count(3)
    s.page.locator("#reformat > summary").tap()
    s.page.tap("#reformat-go")
    expect(s.page.locator(".bib li").first).to_be_visible(timeout=120_000)
    assert overflow(s.page) <= 0, off_screen(s.page, "main *")
    assert s.page.evaluate(TAP_TARGETS) == []
    s.page.locator("#reformat details.how summary").first.tap()
    assert overflow(s.page) <= 0


def test_large_text_does_not_break_the_layout(open_page: Any) -> None:
    width, height, device = DEVICES["iphone-se"]
    s = open_page(width=width, height=height, device=device)
    s.page.evaluate("document.documentElement.style.fontSize = '32px'")  # twice the default
    s.page.tap("[data-sample='data/sample-references-messy.bib']")
    s.page.tap("#check-btn")
    expect(s.page.locator(".tile")).to_have_count(3)
    assert overflow(s.page) <= 0, off_screen(s.page, "main *")
    assert s.page.locator("#check-btn").is_visible()


def test_dark_mode_on_a_phone(open_page: Any) -> None:
    width, height, device = DEVICES["iphone-14-pro"]
    s = open_page(scheme="dark", width=width, height=height, device=device)
    s.page.tap("[data-sample='data/sample-references-text.txt']")
    s.page.tap("#check-btn")
    expect(s.page.locator(".tile")).to_have_count(3)
    assert overflow(s.page) <= 0
    background = s.page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert background != "rgb(243, 245, 249)"


# ----------------------------------------------------------------------- failures a phone can hit


def test_a_browser_without_webassembly_gets_a_readable_message(open_page: Any) -> None:
    width, height, device = DEVICES["iphone-se"]
    s = open_page(
        width=width,
        height=height,
        device=device,
        wait=False,
        init_script="Object.defineProperty(window, 'WebAssembly', {value: undefined});",
    )
    failed = s.page.locator("#engine-failed")
    expect(failed).to_be_visible()
    expect(s.page.locator("#engine-failed-text")).to_contain_text("cannot run WebAssembly")
    expect(s.page.locator("#check-btn")).to_be_disabled()
    assert overflow(s.page) <= 0


def test_running_out_of_memory_gets_specific_advice(open_page: Any) -> None:
    width, height, device = DEVICES["iphone-se"]
    # This is how a browser reports it cannot allocate the engine's memory.
    script = (
        "WebAssembly.Memory = function () { throw new RangeError("
        "'WebAssembly.Memory(): could not allocate memory'); };"
    )
    s = open_page(width=width, height=height, device=device, wait=False, init_script=script)
    expect(s.page.locator("#engine-failed")).to_be_visible(timeout=60_000)
    expect(s.page.locator("#engine-failed-text")).to_contain_text("ran out of memory")
    assert s.page.locator("#retry-engine").bounding_box()["height"] >= 44


def test_buttons_show_progress_before_slow_work(open_page: Any) -> None:
    width, height, device = DEVICES["iphone-se"]
    s = open_page(width=width, height=height, device=device)
    s.page.tap("[data-sample='data/sample-references-mixed.txt']")
    s.page.evaluate((HERE / "watch_button.js").read_text(encoding="utf-8"))
    s.page.tap("#check-btn")
    expect(s.page.locator(".tile")).to_have_count(3)
    assert "Checking…" in s.page.evaluate("window.__labels")
    expect(s.page.locator("#check-btn")).to_have_text("Check references")
    expect(s.page.locator("#check-btn")).to_be_enabled()


# ----------------------------------------------------------------------- install and metadata


def test_the_page_can_be_added_to_a_home_screen() -> None:
    html = (DOCS / "index.html").read_text(encoding="utf-8")
    assert "viewport-fit=cover" in html and "width=device-width" in html
    assert 'rel="manifest" href="manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert html.count('name="theme-color"') == 2  # light and dark
    assert "manifest-src 'self'" in html
    manifest = json.loads((DOCS / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["display"] == "standalone" and manifest["start_url"] == "./"
    sizes = {i["sizes"] for i in manifest["icons"]}
    assert {"192x192", "512x512"} <= sizes
    for icon in manifest["icons"]:
        assert (DOCS / icon["src"]).is_file(), icon["src"]
    assert (DOCS / "assets" / "icon-180.png").is_file()


def test_the_stylesheet_respects_notches_and_touch() -> None:
    css = (DOCS / "assets" / "app.css").read_text(encoding="utf-8")
    assert "env(safe-area-inset-left)" in css and "env(safe-area-inset-bottom)" in css
    assert "@media (pointer: coarse)" in css and "@media (hover: hover)" in css
    assert re.search(r"touch-action:\s*manipulation", css)
