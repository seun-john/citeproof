"""Load the demo in headless Chromium: a good list, a messy list, an empty input, and the rest.

Run: PYODIDE_DIST=/path/to/pyodide pytest tests/browser -q   (see docs/README.md)
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import expect

DATA = Path(__file__).resolve().parent.parent.parent / "docs" / "data"
MARKER = "ZZ-PRIVATE-MARKER-7431"
ALLOWED_HOSTS = {"127.0.0.1", "cdn.jsdelivr.net"}


def sideways_overflow(page: Any) -> int:
    return page.evaluate(
        "document.documentElement.scrollWidth - document.documentElement.clientWidth"
    )


def results_text(session: Any) -> str:
    """All text in the results, including what sits inside collapsed "Details" sections."""
    return session.page.text_content("#results-body")


def tick(session: Any, box: str) -> None:
    """Open "Optional: look things up online" like a person would, then tick a box."""
    online = session.page.locator("#online")
    if online.get_attribute("open") is None:
        online.locator("summary").first.click()
    session.page.check(box)


def load_sample(session: Any, name: str) -> None:
    session.page.click(f"[data-sample='data/{name}']")
    expect(session.page.locator("#refs")).not_to_have_value("")


# ----------------------------------------------------------------------- the three cases


def test_good_list(open_page: Any, shot: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-good.bib")
    s.check()
    expect(s.page.locator(".tile.verified .big")).to_have_text("5 of 5")
    expect(s.page.locator(".tile.verified .pct")).to_have_text("100%")
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("0 of 5")
    expect(s.page.locator(".tile.metadata_mismatch .big")).to_have_text("0 of 5")
    assert s.page.locator(".ref .badge.verified").count() == 5
    assert "Also flagged" not in results_text(s)
    for stray in ("null", "undefined", "[object"):
        assert stray not in results_text(s), stray
    assert "A person must decide" in results_text(s)
    assert s.errors == []
    shot(s.page, "good-list-desktop-light")
    shot(s.page, "good-list-desktop-light-fullpage", True)


def test_messy_list(open_page: Any, shot: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    page = s.page
    expect(page.locator(".tile.verified .big")).to_have_text("4 of 10")
    expect(page.locator(".tile.metadata_mismatch .big")).to_have_text("3 of 10")
    expect(page.locator(".tile.no_verdict .big")).to_have_text("3 of 10")
    # The no-verdict rate is as prominent as the pass rate.
    size = "el => getComputedStyle(el).fontSize"
    assert page.locator(".tile.verified .big").evaluate(size) == page.locator(
        ".tile.no_verdict .big"
    ).evaluate(size)
    assert page.locator(".tile.verified .pct").evaluate(size) == page.locator(
        ".tile.no_verdict .pct"
    ).evaluate(size)
    text = results_text(s)
    assert text.count("Not found in this catalogue.") == 2
    assert "No DOI, so it could not be looked up in this catalogue." in text
    assert "this does not show it is fabricated" in text  # CiteProof's own wording, verbatim
    assert "near match, probably a typo" in text
    assert "same authors in a different order" in text
    assert "RETRACTED" in text and "DUPLICATE" in text
    assert "Also flagged: 1 duplicate" in text
    assert "null" not in text and "undefined" not in text
    assert text.count("A person must decide.") >= 10
    assert not re.search(r"\b(fake|bogus|forged)\b", text, re.I)
    assert not re.search(
        r"\bfabricated\b", text.replace("does not show it is fabricated", ""), re.I
    )
    assert "What this does not check" in page.inner_text("#not-checked h2")
    assert s.errors == []
    shot(page, "messy-list-desktop-light")
    shot(page, "messy-list-desktop-light-fullpage", True)


def test_empty_input(open_page: Any, shot: Any) -> None:
    s = open_page()
    s.check("")
    alert = s.page.locator("#results-body [role=alert]")
    expect(alert).to_contain_text("Nothing to check yet")
    expect(alert).to_contain_text("Paste your reference list")
    assert s.page.locator(".tile").count() == 0  # no 0% / NaN summary for nothing
    s.check("   \n  ")
    expect(alert).to_contain_text("Nothing to check yet")
    assert s.errors == []
    shot(s.page, "empty-input-desktop-light")


def test_pasted_text_example(open_page: Any, shot: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-text.txt")
    s.check()
    page = s.page
    expect(page.locator(".tile.verified .big")).to_have_text("0 of 7")
    expect(page.locator(".tile.metadata_mismatch .big")).to_have_text("2 of 7")
    expect(page.locator(".tile.no_verdict .big")).to_have_text("5 of 7")
    text = results_text(s)
    assert "pasted text" in text and "not part of CiteProof" in text
    assert text.count("Possible match by title (advisory)") == 2
    assert "did not change the verdict" in text
    assert "initials" in text and "shortened list" in text
    reads = page.locator("details.more")
    assert reads.count() == 7
    reads.first.locator("summary").click()
    expect(reads.first).to_contain_text("How this was read")
    expect(reads.first).to_contain_text("McKinney, W. (2010)")
    expect(reads.first).to_contain_text("Layout: APA or Harvard")
    expect(reads.first).to_contain_text("10.25080/Majora-92bf1922-00a")
    assert s.errors == []
    shot(page, "pasted-text-desktop-light")


def test_text_that_is_not_references_is_explained(open_page: Any) -> None:
    s = open_page()
    s.check("hello, this is not a reference list at all")
    alert = s.page.locator("#results-body [role=alert]")
    expect(alert).to_contain_text("No references found in that text")
    expect(alert).to_contain_text("one reference per line")


# ----------------------------------------------------------------------- privacy


def test_nothing_pasted_leaves_the_device(open_page: Any) -> None:
    s = open_page()
    bib = (DATA / "sample-references-good.bib").read_text(encoding="utf-8")
    s.check(bib.replace("harris2020", MARKER))
    expect(s.page.locator(".tile")).to_have_count(3)
    assert s.hosts() <= ALLOWED_HOSTS, s.hosts()
    assert s.hooks["blocked"] == []
    assert {r.method for r in s.requests} == {"GET"}
    for r in s.requests:
        assert MARKER not in r.url and not r.post_data
        assert MARKER not in json.dumps(r.headers)
    assert not any("crossref" in r.url for r in s.requests)
    assert s.page.context.cookies() == []
    storage = s.page.evaluate("[localStorage.length, sessionStorage.length]")
    assert storage == [0, 0]
    csp = s.page.locator("meta[http-equiv='Content-Security-Policy']").get_attribute("content")
    assert "default-src 'none'" in csp and "frame-src" not in csp


# ----------------------------------------------------------------------- engine failure


def test_cdn_failure_shows_a_readable_fallback(open_page: Any) -> None:
    s = open_page(cdn="fail", wait=False)
    expect(s.page.locator("#engine-failed")).to_be_visible(timeout=30_000)
    text = s.page.inner_text("#engine-failed")
    assert "could not be loaded" in text and "Nothing you pasted has been sent anywhere" in text
    assert "pip install" in text
    expect(s.page.locator("#check-btn")).to_be_disabled()
    assert s.page.locator("#retry-engine").is_visible()


def test_tampered_pyodide_is_refused(open_page: Any, pyodide_dist: Any) -> None:
    if pyodide_dist is None:
        return  # needs the local copy to alter
    s = open_page(cdn="tamper", wait=False)
    expect(s.page.locator("#engine-failed")).to_be_visible(timeout=30_000)
    expect(s.page.locator("#check-btn")).to_be_disabled()


# ----------------------------------------------------------------------- catalogue files


def upload(session: Any, name: str, body: str) -> None:
    session.page.set_input_files(
        "#cat-input",
        files=[{"name": name, "mimeType": "text/plain", "buffer": body.encode("utf-8")}],
    )


def test_own_csv_catalogue(open_page: Any) -> None:
    s = open_page()
    bib = (
        "@article{k, author={Smith, Jane and Doe, Alex}, title={A study of things}, "
        "journal={Journal of Things}, year={2020}, doi={10.1234/example}}"
    )
    upload(
        s,
        "mine.csv",
        "doi,title,authors,year,journal,retracted,provenance\n"
        '10.1234/example,A study of things,"Smith, Jane; Doe, Alex",2020,Journal of Things,'
        "false,my library\n"
        ",row without doi,,,,,\n",
    )
    expect(s.page.locator("#cat-status")).to_contain_text("Loaded 1 records from mine.csv")
    expect(s.page.locator("#cat-status")).to_contain_text("1 row(s) with no DOI were skipped")
    s.check(bib)
    expect(s.page.locator(".tile.verified .big")).to_have_text("1 of 1")
    assert "your file mine.csv" in results_text(s)
    assert "my library" in results_text(s)


def test_own_json_catalogue_and_unreadable_file(open_page: Any) -> None:
    s = open_page()
    upload(s, "bad.json", '[{"doi": ')
    expect(s.page.locator("#cat-status")).to_contain_text("Could not read bad.json as JSON")
    assert s.page.locator("#cat-sample").is_checked()
    upload(s, "nodoi.csv", "title,year\nT,2020\n")
    expect(s.page.locator("#cat-status")).to_contain_text('needs a "doi" column')
    upload(s, "ok.json", json.dumps([{"doi": "10.1234/example", "title": "T"}]))
    expect(s.page.locator("#cat-status")).to_contain_text("Loaded 1 records")


def test_file_option_without_a_file_is_a_readable_error(open_page: Any) -> None:
    s = open_page()
    s.page.check("#cat-file")
    s.check("@misc{a, title={T}, doi={10.1/x}}")
    expect(s.page.locator("#results-body [role=alert]")).to_contain_text("No catalogue file chosen")


# ----------------------------------------------------------------------- exports


def test_csv_and_json_downloads(open_page: Any, tmp_path: Path) -> None:
    s = open_page()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    with s.page.expect_download() as info:
        s.page.click("#dl-csv")
    path = tmp_path / info.value.suggested_filename
    info.value.save_as(path)
    assert path.name == "citeproof-results.csv"
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
    assert len(rows) == 10
    by_id = {r["reference_id"]: r for r in rows}
    assert by_id["invented2026"]["verdict"] == "NEEDS_REVIEW"
    assert by_id["hwang2005"]["other_flags"].startswith("RETRACTED")
    assert by_id["mckinney2010b"]["other_flags"].startswith("DUPLICATE")
    with s.page.expect_download() as info2:
        s.page.click("#dl-json")
    report = json.loads(Path(info2.value.path()).read_text(encoding="utf-8"))
    assert report["tool"] == "CiteProof" and len(report["findings"]) >= 10


# ----------------------------------------------------------------------- optional Crossref lookup


def crossref_ok(route: Any) -> None:
    url = route.request.url
    headers = {"access-control-allow-origin": "*", "content-type": "application/json"}
    if url.endswith("10.1038/sdata.2016.18"):
        body = {
            "status": "ok",
            "message": {
                "DOI": "10.1038/sdata.2016.18",
                "title": [
                    "The FAIR Guiding Principles for scientific data management and stewardship"
                ],
                "author": [{"family": "Wilkinson", "given": "Mark D."}],
                "issued": {"date-parts": [[2016, 3, 15]]},
                "container-title": ["Scientific Data"],
            },
        }
        route.fulfill(status=200, headers=headers, body=json.dumps(body))
    else:
        route.fulfill(status=404, headers=headers, body="Resource not found.")


def test_crossref_is_off_by_default_and_sends_nothing(open_page: Any) -> None:
    s = open_page(crossref=crossref_ok)
    assert not s.page.locator("#crossref-on").is_checked()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    expect(s.page.locator(".tile")).to_have_count(3)
    assert s.page.locator("#lookup-panel").count() == 0
    assert not any("crossref" in r.url for r in s.requests)


def test_crossref_needs_a_second_explicit_step_and_shows_what_is_sent(
    open_page: Any, shot: Any
) -> None:
    s = open_page(crossref=crossref_ok)
    load_sample(s, "sample-references-messy.bib")
    tick(s, "#crossref-on")
    s.check()
    panel = s.page.locator("#lookup-panel")
    expect(panel).to_contain_text("Nothing has been sent")
    expect(panel).to_contain_text("https://api.crossref.org/works/10.1038/sdata.2016.18")
    expect(panel).to_contain_text("https://api.crossref.org/works/10.9999/demo.invented-001")
    assert not any("crossref" in r.url for r in s.requests)  # ticking and checking sent nothing
    assert "@" not in panel.inner_text()  # no email address anywhere in what is sent
    s.page.click("#lookup-go")
    expect(s.page.locator("#results-h")).to_have_text(
        "Results (with Crossref lookup)", timeout=30_000
    )
    sent = [r for r in s.requests if "crossref" in r.url]
    assert sorted(r.url for r in sent) == [
        "https://api.crossref.org/works/10.1038/sdata.2016.18",
        "https://api.crossref.org/works/10.9999/demo.invented-001",
    ]
    assert all(r.method == "GET" and not r.post_data for r in sent)
    assert all("mailto" not in r.url and "cookie" not in r.headers for r in sent)
    text = results_text(s)
    assert "Crossref returned a record" in text
    assert "Crossref has no record for this DOI" in text and "not proof it does not exist" in text
    # The FAIR paper moves from "no verdict" to a comparison. CiteProof then flags its authors
    # ("Wilkinson ... and others" is not the full list), so the result is a mismatch, not a pass.
    expect(s.page.locator(".tile.verified .big")).to_have_text("4 of 10")
    expect(s.page.locator(".tile.metadata_mismatch .big")).to_have_text("4 of 10")
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("2 of 10")
    assert "Crossref record" in text and "Crossref REST API" in text
    shot(s.page, "crossref-after-lookup-desktop-light")


def test_crossref_rate_limit_stops_politely(open_page: Any) -> None:
    def limited(route: Any) -> None:
        route.fulfill(
            status=429,
            headers={"access-control-allow-origin": "*", "retry-after": "0"},
            body="slow down",
        )

    s = open_page(crossref=limited)
    load_sample(s, "sample-references-messy.bib")
    tick(s, "#crossref-on")
    s.check()
    s.page.click("#lookup-go")
    expect(s.page.locator("#lookup-panel")).to_contain_text(
        "asked this page to slow down", timeout=60_000
    )
    text = s.page.inner_text("#lookup-panel")
    assert "Not looked up. Nothing was sent for this DOI." in text
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("3 of 10")  # nothing changed
    assert s.errors == []


def test_crossref_unreachable_is_a_readable_message(open_page: Any) -> None:
    def down(route: Any) -> None:
        route.abort()

    s = open_page(crossref=down)
    load_sample(s, "sample-references-messy.bib")
    tick(s, "#crossref-on")
    s.check()
    s.page.click("#lookup-go")
    expect(s.page.locator("#lookup-panel")).to_contain_text(
        "Could not reach Crossref", timeout=30_000
    )
    expect(s.page.locator(".tile")).to_have_count(3)


# ----------------------------------------------------------------------- accessibility and layout


def test_keyboard_only(open_page: Any) -> None:
    s = open_page()
    page = s.page
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip"
    page.keyboard.press("Enter")
    page.focus("#refs")
    page.keyboard.type("@misc{k, title={Keyboard}, doi={10.1/none}}")
    for _ in range(40):
        page.keyboard.press("Tab")
        if page.evaluate("document.activeElement.id") == "check-btn":
            break
    assert page.evaluate("document.activeElement.id") == "check-btn"
    page.keyboard.press("Enter")
    expect(page.locator(".tile")).to_have_count(3)
    assert page.evaluate("document.activeElement.id") == "results-h"
    page.focus("#dl-csv")
    with page.expect_download():
        page.keyboard.press("Enter")


def test_every_control_has_an_accessible_name(open_page: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    names = s.page.evaluate(
        """() => [...document.querySelectorAll('button, input, textarea, summary, a[href]')]
            .map(e => {
              const label = e.labels && e.labels[0] ? e.labels[0].textContent : '';
              const name = e.getAttribute('aria-label') || label || e.textContent || '';
              return [e.tagName, e.id, name.trim()];
            })"""
    )
    assert names and all(name for _, _, name in names), [n for n in names if not n[2]]
    assert s.page.evaluate("document.documentElement.lang") == "en"
    assert s.page.evaluate("document.querySelectorAll('h1').length") == 1


def test_phone_width_has_no_horizontal_scroll(open_page: Any, shot: Any) -> None:
    s = open_page(width=360, height=740)
    load_sample(s, "sample-references-messy.bib")
    s.check()
    expect(s.page.locator(".tile")).to_have_count(3)
    assert sideways_overflow(s.page) <= 0
    button = s.page.locator("#check-btn").bounding_box()
    assert button["height"] >= 44
    shot(s.page, "messy-list-phone-light")
    shot(s.page, "messy-list-phone-light-fullpage", True)


def test_dark_mode_changes_the_palette(open_page: Any, shot: Any) -> None:
    light = open_page(scheme="light").page
    dark_session = open_page(scheme="dark", width=390, height=800)
    dark = dark_session.page
    get = "getComputedStyle(document.body).backgroundColor"
    assert light.evaluate(get) != dark.evaluate(get)
    load_sample(dark_session, "sample-references-messy.bib")
    dark_session.check()
    expect(dark.locator(".tile")).to_have_count(3)
    assert sideways_overflow(dark) <= 0
    shot(dark, "messy-list-phone-dark")
    shot(dark, "messy-list-phone-dark-fullpage", True)


def test_json_example_shows_uncited_and_missing(open_page: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references.json")
    s.check()
    text = results_text(s)
    assert "UNCITED_REFERENCE" in text and "MISSING_REFERENCE" in text
    assert "Cited in the text but not in the bibliography." in text


# ----------------------------------------------------------------------- optional title search


CATALOGUE = json.loads((DATA / "sample-catalogue.json").read_text(encoding="utf-8"))
NUMPY = CATALOGUE[0]
NO_DOI_BIB = (
    "@article{harris2020,\n"
    "  author = {" + " and ".join(NUMPY["authors"]) + "},\n"
    "  title = {Array programming with NumPy},\n"
    "  journal = {Nature},\n"
    "  year = {2020}\n}\n"
)
SEARCH_ORIGIN = "https://api.crossref.org/works?query.bibliographic="


def crossref_item(record: dict[str, Any], **changes: Any) -> dict[str, Any]:
    authors = []
    for name in record["authors"]:
        family, _, given = name.partition(",")
        authors.append({"family": family.strip(), "given": given.strip()})
    item = {
        "DOI": record["doi"],
        "title": [record["title"]],
        "author": authors,
        "issued": {"date-parts": [[int(record["year"])]]},
        "container-title": [record["journal"]],
    }
    return {**item, **changes}


def search_reply(items: list[dict[str, Any]]) -> Any:
    def reply(route: Any) -> None:
        body = {"status": "ok", "message": {"items": items}}
        route.fulfill(
            status=200,
            headers={"access-control-allow-origin": "*", "content-type": "application/json"},
            body=json.dumps(body),
        )

    return reply


def searches(session: Any) -> list[Any]:
    return [r for r in session.requests if r.url.startswith(SEARCH_ORIGIN)]


def test_title_search_is_off_by_default(open_page: Any) -> None:
    s = open_page(crossref=search_reply([crossref_item(NUMPY)]))
    assert not s.page.locator("#search-on").is_checked()
    s.check(NO_DOI_BIB)
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("1 of 1")
    assert s.page.locator("#search-panel").count() == 0
    assert not any("crossref" in r.url for r in s.requests)


def test_title_search_shows_what_is_sent_and_sends_nothing_until_clicked(
    open_page: Any, shot: Any
) -> None:
    decoy = {
        **NUMPY,
        "doi": "10.5555/decoy",
        "title": "Array programming in Python",
        "year": "2019",
    }
    s = open_page(crossref=search_reply([crossref_item(decoy), crossref_item(NUMPY)]))
    tick(s, "#search-on")
    s.check(NO_DOI_BIB)
    panel = s.page.locator("#search-panel")
    expect(panel).to_contain_text("Nothing has been sent")
    expect(panel).to_contain_text("“Array programming with NumPy Harris 2020”")
    expect(panel).to_contain_text(
        SEARCH_ORIGIN + "Array%20programming%20with%20NumPy%20Harris%202020"
    )
    assert searches(s) == []  # ticking the box and checking sent nothing
    s.page.click("#search-go")
    expect(s.page.locator(".candidates")).to_be_visible(timeout=30_000)
    sent = searches(s)
    assert len(sent) == 1 and sent[0].method == "GET" and not sent[0].post_data
    # Only the title, the first author's family name and the year were sent.
    query = sent[0].url.split("query.bibliographic=")[1].split("&")[0]
    assert query == "Array%20programming%20with%20NumPy%20Harris%202020"
    for leaked in ("Nature", "Millman", "Charles", NUMPY["doi"]):
        assert leaked not in sent[0].url
    assert "mailto" not in sent[0].url and "cookie" not in sent[0].headers
    text = s.page.inner_text("#results-body")
    assert "Possible DOIs from Crossref" in text
    assert "Nothing is chosen for you" in text
    assert "year matches" in text and "year differs" in text
    # Suggestions alone change nothing: the verdict is still "no verdict".
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("1 of 1")
    expect(s.page.locator(".tile.verified .big")).to_have_text("0 of 1")
    shot(s.page, "title-search-candidates-desktop-light")


def test_picking_a_doi_reruns_citeproof_and_is_labelled(open_page: Any) -> None:
    s = open_page(crossref=search_reply([crossref_item(NUMPY)]))
    tick(s, "#search-on")
    s.check(NO_DOI_BIB)
    s.page.click("#search-go")
    expect(s.page.locator(".candidates")).to_be_visible(timeout=30_000)
    s.page.click(f"[data-use-doi='{NUMPY['doi']}']")
    expect(s.page.locator(".tile.verified .big")).to_have_text("1 of 1")
    text = results_text(s)
    assert "DOI added by you" in text and "was chosen by you from a Crossref title search" in text
    assert "It was not in your pasted reference" in text
    assert s.page.locator(".candidates").count() == 0
    assert s.errors == []


def test_title_search_rate_limit_stops_and_changes_nothing(open_page: Any) -> None:
    def limited(route: Any) -> None:
        route.fulfill(
            status=429, headers={"access-control-allow-origin": "*", "retry-after": "0"}, body=""
        )

    s = open_page(crossref=limited)
    tick(s, "#search-on")
    s.check(NO_DOI_BIB)
    s.page.click("#search-go")
    expect(s.page.locator("#search-panel")).to_contain_text("slow down", timeout=60_000)
    assert s.page.locator(".candidates").count() == 0
    expect(s.page.locator(".tile.no_verdict .big")).to_have_text("1 of 1")


def test_title_search_skips_references_with_a_doi_or_no_title(open_page: Any) -> None:
    s = open_page(crossref=search_reply([]))
    tick(s, "#search-on")
    load_sample(s, "sample-references-good.bib")
    s.check()
    expect(s.page.locator("#search-panel")).to_contain_text("Nothing to search for")
    assert searches(s) == []


# ----------------------------------------------------------------------- what is visible by default


def test_the_essentials_are_visible_without_opening_anything(open_page: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    page = s.page
    assert page.locator(".banner").is_visible()
    expect(page.locator(".banner")).to_contain_text("A person must decide")
    for kind in ("verified", "metadata_mismatch", "no_verdict"):
        assert page.locator(f".tile.{kind} .big").is_visible()
        assert page.locator(f".tile.{kind} .pct").is_visible()
    card = page.locator("article", has=page.locator(".ref-id", has_text="invented2026"))
    expect(card.locator(".badge")).to_have_text("NEEDS_REVIEW")  # CiteProof's own status
    expect(card.locator(".headline")).to_have_text("Not found in this catalogue.")
    # The evidence used is shown, not hidden.
    expect(card.locator(".evidence").first).to_contain_text("10.9999/demo.invented-001")
    expect(card.locator(".person")).to_contain_text("A person must decide")
    mismatch = page.locator("article", has=page.locator(".ref-id", has_text="waskom2021"))
    visible_evidence = mismatch.locator(".evidence").first
    expect(visible_evidence).to_contain_text("near match, probably a typo")
    # The long parts are folded away until asked for.
    assert not card.locator("details.more .says").first.is_visible()
    card.locator("details.more summary").click()
    expect(card.locator(".says").first).to_contain_text("does not show it is fabricated")
    # The not-checked panel is on the page, not hidden.
    assert page.locator("#not-checked").is_visible()
    expect(page.locator("#not-checked")).to_contain_text("Whether a reference is real")


def test_the_start_screen_is_short(open_page: Any) -> None:
    s = open_page()
    page = s.page
    assert page.locator("#refs").is_visible() and page.locator("#check-btn").is_visible()
    # Explanations are folded away until asked for.
    for hidden in ("#privacy ul", "#online .hint", "#sample-list"):
        assert not page.locator(hidden).first.is_visible(), hidden
    words = len(page.inner_text("main").split())
    assert words < 400, f"start screen has {words} words in <main>"


def test_filters_show_only_what_was_asked_for(open_page: Any) -> None:
    s = open_page()
    load_sample(s, "sample-references-messy.bib")
    s.check()
    page = s.page
    items = page.locator(".refs > li")
    assert items.filter(visible=True).count() == 10
    page.click("[data-filter='NEEDS_REVIEW']")
    assert items.filter(visible=True).count() == 3
    expect(page.locator("[data-filter='NEEDS_REVIEW']")).to_have_attribute("aria-pressed", "true")
    page.click("[data-filter='flagged']")
    assert items.filter(visible=True).count() == 2
    page.click("[data-filter='all']")
    assert items.filter(visible=True).count() == 10
