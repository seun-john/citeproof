"""Tests for the browser demo's data handling (docs/py/demo_logic.py) and its shipped data."""

from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import demo_logic as demo
import pytest
import text_references

from citeproof.references import citeproof

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
CATALOGUE = json.loads((DATA / "sample-catalogue.json").read_text(encoding="utf-8"))
TEXT = (DATA / "sample-references-text.txt").read_text(encoding="utf-8")
GOOD = (DATA / "sample-references-good.bib").read_text(encoding="utf-8")
MESSY = (DATA / "sample-references-messy.bib").read_text(encoding="utf-8")
JSON_EXAMPLE = (DATA / "sample-references.json").read_text(encoding="utf-8")

BIB = """@article{a1,
  author = {Lovelace, Ada and Turing, Alan},
  title = {A Study of Things},
  journal = {J Things},
  year = {2020},
  doi = {10.1/x}
}
"""
REC = {
    "doi": "10.1/x",
    "title": "A Study of Things",
    "authors": ["Ada Lovelace", "Alan Turing"],
    "year": 2020,
    "journal": "J Things",
    "retracted": False,
    "provenance": "test",
}


def check(text: str, records: list[dict[str, Any]] | None = None, **kw: Any) -> dict[str, Any]:
    return demo.run_check(text, [REC] if records is None else records, "test catalogue", **kw)


def verdicts(result: dict[str, Any]) -> dict[str, str]:
    return {row["id"]: row["verdict"] for row in result["rows"]}


# ---------------------------------------------------------------- shipped files


def test_vendored_citeproof_is_an_exact_copy_of_src() -> None:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "sync_citeproof.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_sample_catalogue_records_are_complete_and_honest() -> None:
    dois = [r["doi"].lower() for r in CATALOGUE]
    assert len(dois) == len(set(dois)) == 7
    for record in CATALOGUE:
        assert {"doi", "title", "authors", "year", "journal", "provenance"} <= set(record)
        assert isinstance(record["retracted"], bool)
        assert "Retraction Watch" in record["provenance"]
    assert [r["retracted"] for r in CATALOGUE].count(True) == 2


def test_good_list_is_all_verified() -> None:
    result = check(GOOD, CATALOGUE)
    assert set(verdicts(result).values()) == {"VERIFIED"}
    assert result["summary"]["verified"] == {"count": 5, "percent": 100.0}
    assert result["summary"]["no_verdict"]["count"] == 0


def test_messy_list_gets_the_documented_verdicts() -> None:
    result = check(MESSY, CATALOGUE)
    assert verdicts(result) == {
        "mckinney2010": "VERIFIED",
        "harris2020": "VERIFIED",
        "waskom2021": "METADATA_MISMATCH",
        "vanderwalt2014": "METADATA_MISMATCH",
        "virtanen2020": "METADATA_MISMATCH",
        "hwang2005": "VERIFIED",
        "wilkinson2016": "NEEDS_REVIEW",
        "pedregosa2011": "NEEDS_REVIEW",
        "invented2026": "NEEDS_REVIEW",
        "mckinney2010b": "VERIFIED",
    }
    flags = {row["id"]: [f["status"] for f in row["flags"]] for row in result["rows"]}
    assert flags["hwang2005"] == ["RETRACTED"]
    assert flags["mckinney2010b"] == ["DUPLICATE"]
    notes = {row["id"]: row["evidence"] for row in result["rows"]}
    title_line = next(
        e["value"] for e in notes["waskom2021"] if e["label"] == "Difference in title"
    )
    assert "near match, probably a typo" in title_line
    author_line = next(
        e["value"] for e in notes["vanderwalt2014"] if e["label"] == "Difference in authors"
    )
    assert "same authors in a different order" in author_line


def test_json_example_shows_uncited_and_missing() -> None:
    result = check(JSON_EXAMPLE, CATALOGUE)
    assert result["summary"]["other_flags"]["UNCITED_REFERENCE"] == 1
    assert result["summary"]["other_flags"]["MISSING_REFERENCE"] == 1
    assert [m["id"] for m in result["missing_references"]] == ["r9"]


# ---------------------------------------------------------------- the summary is honest


def test_buckets_always_add_up_and_percentages_match() -> None:
    result = check(MESSY, CATALOGUE)
    s = result["summary"]
    assert (
        s["verified"]["count"] + s["metadata_mismatch"]["count"] + s["no_verdict"]["count"]
        == s["total"]
        == 10
    )
    assert (
        s["verified"]["percent"],
        s["metadata_mismatch"]["percent"],
        s["no_verdict"]["percent"],
    ) == (40.0, 30.0, 30.0)


def test_no_verdict_is_reported_beside_verified() -> None:
    result = check(BIB.replace("10.1/x", "10.9/unknown"))
    s = result["summary"]
    assert s["verified"]["count"] == 0
    assert s["no_verdict"] == {"count": 1, "percent": 100.0}


def test_verdict_names_and_messages_are_citeproofs_own() -> None:
    result = check(MESSY, CATALOGUE)
    cp = {
        f["evidence"].get("reference"): f
        for f in result["report"]["findings"]
        if f["status"] == "NEEDS_REVIEW"
    }
    row = next(r for r in result["rows"] if r["id"] == "wilkinson2016")
    assert row["verdict"] == "NEEDS_REVIEW"
    assert row["message"] == cp["wilkinson2016"]["message"]
    assert "this does not show it is fabricated" in row["message"]
    direct = citeproof(
        {
            "references": __import__("citeproof.bibtex", fromlist=["parse_bibtex"]).parse_bibtex(
                MESSY
            ),
            "catalogue": CATALOGUE,
            "citations": [r["id"] for r in result["rows"]],
        }
    )
    direct.pop("generated_at")
    reported = dict(result["report"])
    reported.pop("generated_at")
    assert reported == direct  # the demo adds nothing to CiteProof's own report


def test_not_found_wording_and_evidence_and_person_note() -> None:
    result = check(MESSY, CATALOGUE)
    row = next(r for r in result["rows"] if r["id"] == "invented2026")
    assert row["headline"] == "Not found in this catalogue."
    labels = {e["label"]: e["value"] for e in row["evidence"]}
    assert labels["DOI looked up"] == "10.9999/demo.invented-001"
    assert "7 records" in labels["Catalogue searched"]
    assert "A person must decide" in row["person_note"]


def test_demo_text_never_calls_a_reference_fake_or_fabricated() -> None:
    result = check(MESSY, CATALOGUE)
    for row in result["rows"]:
        demo_text = " ".join(
            [row["headline"], row["person_note"], *(e["value"] for e in row["evidence"])]
        )
        assert not re.search(r"\b(fake|fabricat|bogus|false)\w*", demo_text, re.I), demo_text
    assert not re.search(r"fake|fabricat", " ".join(demo.HEADLINES.values()), re.I)


def test_missing_metadata_names_which_side_lacks_it() -> None:
    no_journal = BIB.replace("  journal = {J Things},\n", "")
    row = check(no_journal)["rows"][0]
    assert row["verdict"] == "METADATA_MISMATCH"
    line = next(e["value"] for e in row["evidence"] if e["label"] == "Difference in journal")
    assert "missing from your reference" in line


def test_no_doi_reference() -> None:
    row = check(BIB.replace("  doi = {10.1/x}\n", "  year2 = {1}\n"))["rows"][0]
    assert row["verdict"] == "NEEDS_REVIEW"
    assert row["headline"] == demo.HEADLINES["NEEDS_REVIEW_NO_DOI"]


def test_unknown_retraction_status_is_flagged_and_counted() -> None:
    unknown = {k: v for k, v in REC.items() if k != "retracted"}
    result = check(BIB, [unknown])
    assert result["summary"]["other_flags"]["RETRACTION_STATUS_NOT_SUPPLIED"] == 1
    assert result["summary"]["verified"]["count"] == 1


# ---------------------------------------------------------------- reading references


def test_empty_and_whitespace_input_gives_a_readable_error() -> None:
    for text in ("", "   \n\t "):
        with pytest.raises(demo.DemoError) as caught:
            check(text)
        assert caught.value.title == "Nothing to check yet"


def test_bibtex_treats_every_entry_as_cited_and_says_so() -> None:
    parsed = demo.parse_references(BIB)
    assert parsed["citations"] == ["a1"]
    assert any("treated as cited" in n for n in parsed["notices"])


def test_bare_json_list_and_missing_citations_are_handled_with_a_notice() -> None:
    refs = json.dumps(
        [{"id": "r", "doi": "10.1/x", "title": "T", "authors": ["A B"], "year": 1, "journal": "J"}]
    )
    parsed = demo.parse_references(refs)
    assert parsed["citations"] == ["r"]
    assert any("citations" in n for n in parsed["notices"])


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ('{"references": [', "Could not read your reference list as JSON"),
        ('{"references": NaN}', "The JSON contains NaN or Infinity"),
        ("@article{a, title = {oops", "A BibTeX entry is not closed"),
        ('@article{a, title = "oops}', "A BibTeX field is not closed"),
    ],
)
def test_malformed_input_gives_specific_messages(text: str, title: str) -> None:
    with pytest.raises(demo.DemoError) as caught:
        demo.parse_references(text)
    assert caught.value.title == title


def test_duplicate_ids_and_catalogue_dois_are_explained_with_citeproofs_text() -> None:
    twice = BIB + BIB
    with pytest.raises(demo.DemoError) as caught:
        check(twice)
    assert caught.value.title == "Two references share the same id"
    assert caught.value.detail == "CiteProof said: Reference ids must be unique"
    with pytest.raises(demo.DemoError) as caught2:
        check(BIB, [REC, {**REC, "doi": "https://doi.org/10.1/X"}])
    assert caught2.value.title == "The catalogue lists the same DOI twice"


def test_catalogue_record_without_doi_is_explained() -> None:
    with pytest.raises(demo.DemoError) as caught:
        check(BIB, [{"title": "x"}])
    assert "doi" in caught.value.title


def test_limits_are_enforced_with_readable_messages() -> None:
    with pytest.raises(demo.DemoError, match="too long"):
        demo.parse_references("@" + "x" * (demo.MAX_INPUT_CHARS + 1))
    many = "".join(f"@misc{{k{i}, title = {{T}}}}\n" for i in range(demo.MAX_REFERENCES + 1))
    with pytest.raises(demo.DemoError, match="Too many references"):
        demo.parse_references(many)


def test_pasted_text_is_never_interpreted_as_markup() -> None:
    nasty = BIB.replace("A Study of Things", "<img src=x onerror=alert(1)> & co")
    row = check(nasty)["rows"][0]
    assert row["title"] == "<img src=x onerror=alert(1)> & co"  # kept as plain text for textContent


def test_no_catalogue_is_an_error() -> None:
    with pytest.raises(demo.DemoError) as caught:
        demo.run_check(BIB, [], "none")
    assert caught.value.title == "No catalogue loaded"


def test_embedded_catalogue_in_pasted_json_is_used_and_announced() -> None:
    payload = {
        "references": [
            {"id": "a1", **{k: v for k, v in REC.items() if k not in ("retracted", "provenance")}}
        ],
        "catalogue": [REC],
        "citations": ["a1"],
    }
    result = demo.run_check(json.dumps(payload), CATALOGUE, "the sample")
    assert result["summary"]["verified"]["count"] == 1
    assert any('own "catalogue"' in n for n in result["notices"])


# ---------------------------------------------------------------- reading catalogues


CSV = (
    "﻿DOI,Title,Author,Year,Journal,Retracted,Provenance,Notes\r\n"
    '10.1/x,"A Study of Things","Ada Lovelace; Alan Turing",2020,J Things,false,"my, export",'
    "ignored\r\n"
    ",No doi here,A B,2000,J,,\r\n"
    "10.2/y,Second,B C,2001,J2,yes,\r\n"
    "\r\n"
    "10.3/z,Third,,2002,,,\r\n"
)


def test_csv_catalogue_converts_to_citeproof_records() -> None:
    parsed = demo.parse_catalogue(CSV, "c.csv")
    first, second, third = parsed["records"]
    assert first == {
        "doi": "10.1/x",
        "title": "A Study of Things",
        "authors": "Ada Lovelace; Alan Turing",
        "year": "2020",
        "journal": "J Things",
        "provenance": "my, export",
        "retracted": False,
    }
    assert second["retracted"] is True
    assert "retracted" not in third and "authors" not in third and "journal" not in third
    assert any("1 row(s) with no DOI were skipped (rows 3)" in n for n in parsed["notices"])
    assert any("Ignored columns: notes" in n for n in parsed["notices"])


def test_csv_blank_retracted_means_not_supplied_not_false() -> None:
    parsed = demo.parse_catalogue(
        "doi,title,authors,year,journal,retracted\n"
        "10.1/x,A Study of Things,Ada Lovelace; Alan Turing,2020,J Things,\n",
        "c.csv",
    )
    result = check(BIB, parsed["records"])
    assert result["summary"]["other_flags"]["RETRACTION_STATUS_NOT_SUPPLIED"] == 1


def test_csv_without_retracted_column_says_so() -> None:
    parsed = demo.parse_catalogue("doi,title\n10.1/x,T\n", "c.csv")
    assert any('no "retracted" column' in n for n in parsed["notices"])


def test_csv_semicolon_delimiter_is_detected() -> None:
    parsed = demo.parse_catalogue("doi;title;year\n10.1/x;T;2020\n", "c.csv")
    assert parsed["records"] == [{"doi": "10.1/x", "title": "T", "year": "2020"}]


@pytest.mark.parametrize(
    ("text", "title"),
    [
        ("title,year\nT,2020\n", 'The catalogue needs a "doi" column'),
        ("doi,retracted\n10.1/x,maybe\n", 'A "retracted" cell is not yes/no'),
        ("doi,title\n,no doi\n", "The catalogue has no usable records"),
        ("   \n", "The catalogue file is empty"),
        ("[1, 2]", "A catalogue record is not an object"),
        ('{"nope": 1}', "No catalogue found in that JSON"),
        ("[{", "Could not read c.json as JSON"),
    ],
)
def test_bad_catalogue_files_give_readable_errors(text: str, title: str) -> None:
    name = "c.json" if text.lstrip().startswith(("[", "{")) else "c.csv"
    with pytest.raises(demo.DemoError) as caught:
        demo.parse_catalogue(text, name)
    assert caught.value.title == title


def test_json_catalogue_forms() -> None:
    assert demo.parse_catalogue(json.dumps([REC]), "c.json")["records"] == [REC]
    assert demo.parse_catalogue(json.dumps({"catalogue": [REC], "references": []}), "c.json")[
        "records"
    ] == [REC]


def test_catalogue_size_limit() -> None:
    with pytest.raises(demo.DemoError, match="too large"):
        demo.parse_catalogue("doi\n" + "x" * demo.MAX_CATALOGUE_CHARS, "big.csv")


# ---------------------------------------------------------------- CSV export


def read_csv(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_export_has_one_row_per_reference_plus_missing_citations() -> None:
    result = check(JSON_EXAMPLE, CATALOGUE)
    rows = read_csv(demo.results_to_csv(result))
    assert [r["reference_id"] for r in rows] == ["r1", "r2", "r3", "r9"]
    assert list(rows[0]) == demo.CSV_COLUMNS
    assert rows[0]["verdict"] == "VERIFIED"
    assert "UNCITED_REFERENCE" in rows[1]["other_flags"]
    assert rows[2]["verdict"] == "NEEDS_REVIEW"
    assert rows[3]["verdict"] == "MISSING_REFERENCE"
    assert all(r["person_decision"] == "" and r["citeproof_version"] for r in rows)


def test_csv_export_neutralises_spreadsheet_formulas() -> None:
    evil = BIB.replace("A Study of Things", '=HYPERLINK("http://x.example","go")').replace(
        "a1", "+cmd"
    )
    rows = read_csv(demo.results_to_csv(check(evil)))
    assert rows[0]["title_as_given"].startswith("'=")
    assert rows[0]["reference_id"].startswith("'+")


def test_csv_export_survives_commas_quotes_newlines_and_unicode() -> None:
    odd = BIB.replace("A Study of Things", 'Stéfan, "quoted"\n title')
    rows = read_csv(demo.results_to_csv(check(odd)))
    assert rows[0]["title_as_given"] == 'Stéfan, "quoted" title'


# ---------------------------------------------------------------- optional Crossref lookup


CROSSREF = {
    "status": "ok",
    "message": {
        "DOI": "10.9/new",
        "title": ["A <i>Fresh</i> Study &amp; More"],
        "author": [{"family": "Lovelace", "given": "Ada"}, {"name": "The Consortium"}],
        "issued": {"date-parts": [[2021, 5, 1]]},
        "container-title": ["J Things"],
    },
}


def test_crossref_url_only_for_real_looking_dois_and_is_encoded() -> None:
    assert demo.crossref_url("https://doi.org/10.1/x") is None  # too few digits in the prefix
    assert (
        demo.crossref_url("doi:10.1038/S41586-020-2649-2")
        == "https://api.crossref.org/works/10.1038/s41586-020-2649-2"
    )
    assert (
        demo.crossref_url("10.1016/s0140-6736(97)11096-0")
        == "https://api.crossref.org/works/10.1016/s0140-6736%2897%2911096-0"
    )
    for bad in ("", "not a doi", "10.1234/has space", "10.1234/"):
        assert demo.crossref_url(bad) is None


def test_lookup_candidates_list_only_dois_not_in_the_catalogue() -> None:
    result = check(MESSY, CATALOGUE)
    items = result["lookup"]["items"]
    assert [i["doi"] for i in items] == ["10.1038/sdata.2016.18", "10.9999/demo.invented-001"]
    assert all(i["url"].startswith("https://api.crossref.org/works/") for i in items)
    assert result["lookup"]["truncated"] == 0


def test_lookup_candidates_are_capped() -> None:
    many = "".join(
        f"@misc{{k{i}, title = {{T}}, doi = {{10.5555/n{i}}}}}\n"
        for i in range(demo.MAX_LOOKUPS + 5)
    )
    lookup = check(many)["lookup"]
    assert len(lookup["items"]) == demo.MAX_LOOKUPS and lookup["truncated"] == 5


def test_crossref_response_maps_to_a_labelled_catalogue_record() -> None:
    record = demo.crossref_to_record(CROSSREF, "2026-10-20")
    assert record["doi"] == "10.9/new"
    assert record["title"] == "A Fresh Study & More"
    assert record["authors"] == ["Lovelace, Ada", "The Consortium"]
    assert (record["year"], record["journal"]) == ("2021", "J Things")
    assert record["provenance"].startswith("Crossref REST API")
    assert "2026-10-20" in record["provenance"]
    assert "retracted" not in record  # never invented


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"message": []}, {"message": {"title": ["x"]}}, {"message": {"DOI": 5}}],
)
def test_unexpected_crossref_payloads_are_rejected_readably(payload: Any) -> None:
    with pytest.raises(demo.DemoError) as caught:
        demo.crossref_to_record(payload, "2026-10-20")
    assert caught.value.title == "Crossref sent something unexpected"


def test_looked_up_record_goes_through_citeproof_and_is_labelled() -> None:
    extra = demo.crossref_to_record(
        {
            "message": {
                "DOI": "10.1/x",
                "title": ["A Study of Things"],
                "author": [
                    {"family": "Lovelace", "given": "Ada"},
                    {"family": "Turing", "given": "Alan"},
                ],
                "issued": {"date-parts": [[2020]]},
                "container-title": ["J Things"],
            }
        },
        "2026-10-20",
    )
    result = check(BIB, CATALOGUE, extra_records=[extra])
    row = result["rows"][0]
    assert row["verdict"] == "VERIFIED" and row["from_crossref"] is True
    assert result["summary"]["other_flags"]["RETRACTION_STATUS_NOT_SUPPLIED"] == 1
    assert any("added from your Crossref lookup" in n for n in result["notices"])


def test_lookup_never_overrides_an_existing_catalogue_record() -> None:
    extra = {"doi": "10.1/x", "title": "Different", "provenance": "Crossref REST API"}
    result = check(BIB, [REC], extra_records=[extra])
    assert result["rows"][0]["from_crossref"] is False and result["catalogue_size"] == 1


# ---------------------------------------------------------------- bridge used by the page


def test_bridge_returns_json_and_never_raises() -> None:
    ok = json.loads(demo.api_check(BIB, json.dumps([REC]), "x", ""))
    assert ok["ok"] is True and ok["summary"]["total"] == 1
    bad = json.loads(demo.api_check("", json.dumps([REC]), "x", ""))
    assert bad["ok"] is False and bad["error"]["title"] == "Nothing to check yet"
    weird = json.loads(demo.api_check(BIB, "{not json", "x", ""))
    assert weird["ok"] is False and weird["error"]["title"]
    assert json.loads(demo.api_parse_catalogue("doi\n10.1/x\n", "c.csv"))["ok"] is True
    assert "csv" in json.loads(demo.api_csv(json.dumps(ok)))


# ---------------------------------------------------------------- pasted plain text


def read(raw: str) -> dict[str, Any]:
    return text_references.read_entry(raw)["fields"]


MCKINNEY_APA = (
    "McKinney, W. (2010). Data structures for statistical computing in Python. Proceedings of the "
    "9th Python in Science Conference, 56\u201361. https://doi.org/10.25080/Majora-92bf1922-00a"
)
WASKOM = {
    "apa": "Waskom, M. L. (2021). seaborn: statistical data visualization. Journal of Open Source "
    "Software, 6(60), 3021.",
    "harvard": "Waskom, M.L. (2021) 'seaborn: statistical data visualization', Journal of Open "
    "Source Software, 6(60), p. 3021.",
    "chicago": "Waskom, Michael L. 2021. \u201cSeaborn: Statistical Data Visualization.\u201d "
    "Journal of Open Source Software 6 (60): 3021.",
    "mla": "Waskom, Michael L. \u201cSeaborn: Statistical Data Visualization.\u201d Journal of "
    "Open Source Software, vol. 6, no. 60, 2021, p. 3021.",
}


@pytest.mark.parametrize("style", list(WASKOM))
def test_each_citation_style_gives_title_journal_and_year(style: str) -> None:
    fields = read(WASKOM[style])
    assert fields["title"].lower() == "seaborn: statistical data visualization"
    assert fields["journal"] == "Journal of Open Source Software"
    assert fields["year"] == "2021"
    assert fields["authors"][0].startswith("Waskom")


def test_vancouver_and_apa_multi_author_lists() -> None:
    van = read(
        "Pedregosa F, Varoquaux G, Gramfort A, Michel V. Scikit-learn: machine learning in "
        "Python. J Mach Learn Res. 2011;12:2825-30."
    )
    assert van["authors"] == ["Pedregosa F", "Varoquaux G", "Gramfort A", "Michel V"]
    assert (van["journal"], van["year"]) == ("J Mach Learn Res", "2011")
    apa = read(
        "Pedregosa, F., Varoquaux, G., Gramfort, A., & Michel, V. (2011). Scikit-learn: Machine "
        "learning in Python. Journal of Machine Learning Research, 12, 2825\u20132830."
    )
    assert apa["authors"] == ["Pedregosa, F.", "Varoquaux, G.", "Gramfort, A.", "Michel, V."]
    assert apa["journal"] == "Journal of Machine Learning Research"


def test_doi_is_found_in_every_common_form() -> None:
    base = "Smith, J. (2020). A study of things. Journal of Things, 4, 1-10."
    for tail in (
        "https://doi.org/10.1234/Abc.5.",
        "doi:10.1234/Abc.5",
        "DOI: 10.1234/Abc.5",
        "http://dx.doi.org/10.1234/Abc.5)",
    ):
        assert read(f"{base} {tail}")["doi"] == "10.1234/Abc.5"
    parens = read("Smith (1997). T. J. 1. 10.1016/S0140-6736(97)11096-0.")
    assert parens["doi"] == "10.1016/S0140-6736(97)11096-0"


def test_unrecognised_layouts_are_left_unread_not_guessed() -> None:
    fields = read("I think this was the one from last week maybe 2019 something")
    assert fields == {}


ONE = "One, A. (2020). A title here that is long. J, 1, 1-2."
TWO = "Two, B. (2021). Another title here. K, 2, 3-4."


@pytest.mark.parametrize(
    ("pasted", "count"),
    [
        (f"{ONE}\n\n{TWO}", 2),
        (f"[1] {ONE}\n[2] {TWO}", 2),
        (f"1. {ONE}\n2. {TWO}", 2),
        (f"{ONE.replace('J, 1,', 'J, 1,')}\n   more\n{TWO}", 2),
        (f"{ONE}\n{TWO}", 2),
        ("One, A. (2020). A title here that is\nlong and wraps. J, 1.", 1),
        (f"References\n{ONE}\n{TWO}\nnotes to self about the list", 2),
        ("One, A. (2020). A title here that is long. Journal of\nThings, 1, 1-2.\n" + TWO, 2),
    ],
)
def test_list_layouts_are_split_into_references(pasted: str, count: int) -> None:
    assert len(demo.parse_references(pasted)["references"]) == count


def test_numbered_list_starting_with_a_bracket_is_not_mistaken_for_json() -> None:
    parsed = demo.parse_references("[1] One, A. (2020). A title here that is long. J, 1, 1-2.")
    assert parsed["format"] == "text"


def test_text_without_any_reference_is_explained() -> None:
    with pytest.raises(demo.DemoError) as caught:
        check("just some words here that are not a reference at all")
    assert caught.value.title == "No references found in that text"
    assert "one reference per line" in caught.value.hint


def test_headings_and_non_references_are_skipped_and_reported() -> None:
    parsed = demo.parse_references(f"References\n{ONE}\n{TWO}\nmy notes to self about this")
    assert [r["id"] for r in parsed["references"]] == ["ref1", "ref2"]
    assert any("1 line(s) were skipped" in n for n in parsed["notices"])


def test_text_with_a_matching_doi_and_full_names_can_be_verified() -> None:
    chicago = (
        "McKinney, Wes. 2010. \u201cData Structures for Statistical Computing in Python.\u201d "
        "Proceedings of the 9th Python in Science Conference 445: 56\u201361. "
        "https://doi.org/10.25080/Majora-92bf1922-00a"
    )
    result = check(chicago, CATALOGUE)
    assert result["rows"][0]["verdict"] == "VERIFIED"
    assert result["input_format"] == "text"


def test_initials_are_a_citeproof_mismatch_and_the_card_says_why() -> None:
    row = check(MCKINNEY_APA, CATALOGUE)["rows"][0]
    assert row["verdict"] == "METADATA_MISMATCH"
    line = next(e["value"] for e in row["evidence"] if e["label"] == "Difference in authors")
    assert "CiteProof: different authors" in line
    assert "family names match" in line and "initials" in line


def test_shortened_author_lists_are_explained() -> None:
    row = check(TEXT, CATALOGUE)["rows"][-1]
    line = next(e["value"] for e in row["evidence"] if e["label"] == "Difference in authors")
    assert "shortened list" in line


def test_a_missing_field_from_text_says_it_was_not_read() -> None:
    record = {**REC, "doi": "10.1234/x"}
    row = check("Smith. (2020). x. https://doi.org/10.1234/x", [record])["rows"][0]
    lines = {e["label"]: e["value"] for e in row["evidence"]}
    assert "could not be read from there" in lines["Difference in journal"]
    assert "your pasted text" in lines["Difference in journal"]


def test_text_example_verdicts_and_how_it_was_read() -> None:
    result = check(TEXT, CATALOGUE)
    assert {r["id"]: r["verdict"] for r in result["rows"]} == {
        "ref1": "METADATA_MISMATCH",
        "ref2": "NEEDS_REVIEW",
        "ref3": "NEEDS_REVIEW",
        "ref4": "NEEDS_REVIEW",
        "ref5": "NEEDS_REVIEW",
        "ref6": "NEEDS_REVIEW",
        "ref7": "METADATA_MISMATCH",
    }
    assert result["summary"]["verified"]["count"] == 0
    assert all(r["read"] and r["read"]["raw"] for r in result["rows"])
    assert check(BIB, [REC])["rows"][0]["read"] is None  # BibTeX has no "how this was read"
    assert result["rows"][5]["read"]["style"] == "not recognised"


def test_title_hint_is_advisory_and_never_changes_the_verdict() -> None:
    rows = {r["id"]: r for r in check(TEXT, CATALOGUE)["rows"]}
    for ref_id, title in (("ref2", "Array programming with NumPy"), ("ref3", "seaborn")):
        hint = next(e for e in rows[ref_id]["evidence"] if "advisory" in e["label"])
        assert title in hint["value"] and "did not change the verdict" in hint["value"]
        assert rows[ref_id]["verdict"] == "NEEDS_REVIEW"
    assert not any("advisory" in e["label"] for e in rows["ref4"]["evidence"])
    assert not any("advisory" in e["label"] for e in rows["ref5"]["evidence"])


def test_title_hint_for_bibtex_with_a_wrong_doi_says_so() -> None:
    long_title = {**REC, "title": "A Study of Things That Matter Greatly"}
    wrong = BIB.replace("A Study of Things", long_title["title"]).replace("10.1/x", "10.9/other")
    row = check(wrong, [long_title])["rows"][0]
    hint = next(e for e in row["evidence"] if "advisory" in e["label"])
    assert "different DOI" in hint["value"]


def test_text_input_is_cited_note_and_never_says_verified_without_citeproof() -> None:
    result = check(TEXT, CATALOGUE)
    direct = citeproof(
        {
            "references": [{"id": r["id"], **(r["read"] and {})} for r in result["rows"]][:0],
            "catalogue": CATALOGUE,
            "citations": [],
        }
    )
    assert direct["findings"] == []  # sanity: building blocks are CiteProof's own
    assert any("Plain text" in n and "not part of CiteProof" in n for n in result["notices"])


# ---------------------------------------------------------------- finding DOIs by title (optional)

NUMPY = CATALOGUE[0]
NUMPY_NO_DOI = GOOD.split("@article")[1].replace(f"  doi = {{{NUMPY['doi']}}},\n", "")


def numpy_bib_without_doi() -> str:
    entry = "@article" + NUMPY_NO_DOI
    assert "doi" not in entry.lower()
    return entry


def crossref_item(record: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A Crossref work item for a catalogue record."""
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


def test_search_query_is_title_first_author_surname_and_year() -> None:
    ref = {
        "id": "a",
        "title": "Array programming with NumPy",
        "authors": ["Harris, Charles R."],
        "year": "2020",
    }
    assert demo.search_query(ref) == "Array programming with NumPy Harris 2020"
    assert (
        demo.search_query({"id": "a", "title": "Array programming with NumPy"})
        == "Array programming with NumPy"
    )
    assert demo.search_query({"id": "a", "title": "Short"}) is None
    assert demo.search_query({"id": "a"}) is None


def test_search_url_is_one_fixed_shape_with_everything_encoded() -> None:
    url = demo.crossref_search_url('A "quoted" title & more? #1')
    assert url.startswith("https://api.crossref.org/works?query.bibliographic=")
    assert "rows=3" in url and "select=DOI%2Ctitle%2Cauthor%2Cissued%2Ccontainer-title" in url
    assert " " not in url and '"' not in url and "#" not in url and "&more" not in url
    assert "mailto" not in url


def test_search_plan_lists_only_unresolved_references_without_a_doi() -> None:
    result = check(MESSY.replace("doi = {10.9999/demo.invented-001},", ""), CATALOGUE)
    plan = result["search"]
    assert [i["id"] for i in plan["items"]] == ["pedregosa2011", "invented2026"]
    assert plan["unreadable"] == []
    assert all(i["url"].startswith("https://api.crossref.org/works?") for i in plan["items"])
    # A reference whose DOI is merely absent from the catalogue is the DOI lookup's job, not search.
    assert "wilkinson2016" not in [i["id"] for i in plan["items"]]


def test_search_plan_reports_references_it_cannot_search() -> None:
    result = check(TEXT, CATALOGUE)
    plan = result["search"]
    assert "ref6" in plan["unreadable"]  # the unreadable notes line has no title
    assert "ref2" in [i["id"] for i in plan["items"]]


def test_candidates_are_ranked_never_chosen_and_keep_the_record() -> None:
    other = {
        **NUMPY,
        "doi": "10.5555/other",
        "title": "Array programming in Python",
        "year": "2019",
    }
    payload = {
        "message": {"items": [crossref_item(other), crossref_item(NUMPY), {"title": ["no doi"]}]}
    }
    found = demo.crossref_candidates(payload, NUMPY["title"], "2020", "2026-10-21")
    assert [c["doi"] for c in found] == [NUMPY["doi"], "10.5555/other"]
    assert found[0]["title_similarity"] == 1.0 and found[0]["year_matches"] is True
    assert found[1]["year_matches"] is False
    assert found[0]["record"]["provenance"].startswith("Crossref REST API (title search")
    assert "retracted" not in found[0]["record"]


def test_unexpected_search_replies_are_rejected_readably() -> None:
    for payload in (None, {}, {"message": {}}, {"message": {"items": "x"}}):
        with pytest.raises(demo.DemoError) as caught:
            demo.crossref_candidates(payload, "A long enough title", "2020", "2026-10-21")
        assert caught.value.title == "Crossref sent something unexpected"


def test_a_doi_the_person_chose_is_checked_by_citeproof_and_labelled() -> None:
    bib = numpy_bib_without_doi()
    before = check(bib, CATALOGUE)["rows"][0]
    assert before["verdict"] == "NEEDS_REVIEW" and before["doi_chosen"] is False
    chosen = demo.crossref_candidates(
        {"message": {"items": [crossref_item(NUMPY)]}}, NUMPY["title"], "2020", "2026-10-21"
    )[0]
    after = check(bib, CATALOGUE, doi_overrides={"harris2020": chosen["doi"]})
    row = after["rows"][0]
    assert row["verdict"] == "VERIFIED" and row["doi_chosen"] is True
    assert row["doi_as_given"] == ""  # the export never pretends the DOI was in the pasted text
    assert row["evidence"][0]["label"] == "DOI added by you"
    assert "Crossref title search" in row["evidence"][0]["value"]
    assert any("added by you" in n for n in after["notices"])
    assert after["search"]["items"] == []  # nothing left to search for


def test_a_chosen_doi_is_still_compared_and_can_still_mismatch() -> None:
    bib = numpy_bib_without_doi()
    wrong = {
        **NUMPY,
        "doi": "10.5555/other",
        "title": "Array programming in Python",
        "year": "2019",
    }
    row = check(
        bib,
        CATALOGUE,
        extra_records=[demo.crossref_to_record({"message": crossref_item(wrong)}, "2026-10-21")],
        doi_overrides={"harris2020": "10.5555/other"},
    )["rows"][0]
    assert row["verdict"] == "METADATA_MISMATCH"


def test_a_reference_keeps_its_own_doi_and_bad_overrides_are_ignored() -> None:
    with_doi = check(GOOD, CATALOGUE, doi_overrides={"harris2020": "10.5555/other"})
    assert set(verdicts(with_doi).values()) == {"VERIFIED"}
    assert not any(r["doi_chosen"] for r in with_doi["rows"])
    bib = numpy_bib_without_doi()
    for bad in ("not a doi", "10.1/x", "", "https://example.com/10.5555/x y"):
        assert (
            check(bib, CATALOGUE, doi_overrides={"harris2020": bad})["rows"][0]["doi_chosen"]
            is False
        )
    assert (
        check(bib, CATALOGUE, doi_overrides={"nobody": NUMPY["doi"]})["rows"][0]["doi_chosen"]
        is False
    )


def test_csv_export_marks_a_chosen_doi() -> None:
    result = check(numpy_bib_without_doi(), CATALOGUE, doi_overrides={"harris2020": NUMPY["doi"]})
    row = read_csv(demo.results_to_csv(result))[0]
    assert row["doi_as_given"] == "" and "DOI added by you" in row["evidence"]


# ----------------------------------------------------- mild mismatches, Crossref label


def test_initials_only_mismatch_is_labelled_but_the_verdict_is_citeproofs() -> None:
    result = check(MCKINNEY_APA, CATALOGUE)
    row = result["rows"][0]
    assert row["verdict"] == "METADATA_MISMATCH"  # unchanged
    assert row["headline"] == "Found in this catalogue. Only the authors' given names differ."
    assert result["summary"]["metadata_mismatch"] == {
        "count": 1,
        "percent": 100.0,
        "only_given_names": 1,
    }
    assert result["summary"]["verified"]["count"] == 0  # not promoted to verified


def test_other_mismatches_are_not_called_mild() -> None:
    result = check(MESSY, CATALOGUE)
    assert result["summary"]["metadata_mismatch"]["only_given_names"] == 0
    for row in result["rows"]:
        if row["verdict"] == "METADATA_MISMATCH":
            assert row["headline"] == demo.HEADLINES["METADATA_MISMATCH"]
    # A shortened author list ("et al.") is a real difference, not a matter of initials.
    short = check(TEXT, CATALOGUE)["rows"][-1]
    assert short["headline"] == demo.HEADLINES["METADATA_MISMATCH"]


def test_a_title_difference_alongside_initials_is_not_mild() -> None:
    other_title = MCKINNEY_APA.replace("Data structures for", "Some other thing about")
    row = check(other_title, CATALOGUE)["rows"][0]
    assert row["headline"] == demo.HEADLINES["METADATA_MISMATCH"]


def test_the_catalogue_label_says_how_many_records_came_from_crossref() -> None:
    extra = demo.crossref_to_record({"message": crossref_item(NUMPY)}, "2026-10-24")
    result = check(numpy_bib_without_doi() + "@misc{x, title={T}}", [REC], extra_records=[extra])
    assert result["catalogue_label"] == "test catalogue + 1 from Crossref"
    assert result["catalogue_size"] == 2
