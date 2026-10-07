from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from citeproof.bibtex import parse_bibtex
from citeproof.claims import claimtrace, normalise_number
from citeproof.cli import main
from citeproof.core import InputError
from citeproof.references import citeproof, normalise_doi


def statuses(result: dict[str, Any]) -> list[str]:
    return [f["status"] for f in result["findings"]]


def ref(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "a",
        "doi": "10.1/x",
        "title": "A Study of Things",
        "authors": ["Ada Lovelace", "Alan Turing"],
        "year": 2020,
        "journal": "J Things",
    }
    return {**base, **kw}


def rec(**kw: Any) -> dict[str, Any]:
    base = ref(retracted=False, provenance="test")
    base.pop("id")
    return {**base, **kw}


def run(
    refs: list[dict[str, Any]], records: list[dict[str, Any]], cites: list[str]
) -> dict[str, Any]:
    return citeproof({"references": refs, "catalogue": records, "citations": cites})


@pytest.mark.parametrize(
    "raw",
    [
        "10.1/X",
        "https://doi.org/10.1/x",
        "http://dx.doi.org/10.1/x",
        "doi:10.1/x",
        "DOI: 10.1/X.",
        " 10.1/x ",
    ],
)
def test_doi_forms_are_equivalent(raw: str) -> None:
    assert normalise_doi(raw) == "10.1/x"


def test_verified_reference() -> None:
    result = run([ref(doi="http://dx.doi.org/10.1/X")], [rec()], ["a"])
    assert statuses(result) == ["VERIFIED"]


def test_author_order_and_string_form() -> None:
    swapped = run([ref(authors=["Alan Turing", "Ada Lovelace"])], [rec()], ["a"])
    note = swapped["findings"][0]["evidence"]["differences"]["authors"]["note"]
    assert note == "same authors in a different order"
    as_text = run([ref(authors="Ada Lovelace; Alan Turing")], [rec()], ["a"])
    assert statuses(as_text) == ["VERIFIED"]


def test_surname_first_names_match() -> None:
    result = run([ref(authors=["Lovelace, Ada", "Turing, Alan"])], [rec()], ["a"])
    assert statuses(result) == ["VERIFIED"]


def test_title_typo_vs_different_title() -> None:
    near = run([ref(title="A Study of Thngs")], [rec()], ["a"])
    diff = near["findings"][0]["evidence"]["differences"]["title"]
    assert diff["note"] == "near match, probably a typo"
    far = run([ref(title="Completely unrelated")], [rec()], ["a"])
    assert far["findings"][0]["evidence"]["differences"]["title"]["note"] == "different title"


def test_year_in_different_formats() -> None:
    assert statuses(run([ref(year="2020a")], [rec()], ["a"])) == ["VERIFIED"]


def test_unknown_doi_is_not_called_fabricated() -> None:
    result = run([ref(doi="10.9/none")], [rec()], ["a"])
    finding = result["findings"][0]
    assert finding["status"] == "NEEDS_REVIEW"
    assert "not show it is fabricated" in finding["message"]


def test_reference_without_doi() -> None:
    result = run([ref(doi="")], [rec()], ["a"])
    assert "has no DOI" in result["findings"][0]["message"]


def test_duplicates_uncited_and_missing() -> None:
    refs = [ref(id="a"), ref(id="b", doi="https://doi.org/10.1/X")]
    result = run(refs, [rec()], ["a", "ghost"])
    got = statuses(result)
    assert "DUPLICATE" in got and "UNCITED_REFERENCE" in got and "MISSING_REFERENCE" in got
    dup = next(f for f in result["findings"] if f["status"] == "DUPLICATE")
    assert dup["evidence"]["duplicate_of"] == "a"


def test_retraction_and_unknown_retraction() -> None:
    assert "RETRACTED" in statuses(run([ref()], [rec(retracted=True)], ["a"]))
    unknown = rec()
    unknown.pop("retracted")
    assert "NEEDS_REVIEW" in statuses(run([ref()], [unknown], ["a"]))


def test_duplicate_catalogue_doi_is_rejected() -> None:
    with pytest.raises(InputError):
        run([ref()], [rec(), rec(doi="https://doi.org/10.1/X")], ["a"])


def test_duplicate_reference_ids_are_rejected() -> None:
    with pytest.raises(InputError):
        run([ref(), ref()], [rec()], ["a"])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("12.50%", "12.5%"), ("12.5 %", "12.5%"), ("1,000", "1000"), ("-3", "-3"), ("007", "7")],
)
def test_number_normalisation(raw: str, expected: str) -> None:
    assert normalise_number(raw) == expected


def claim(text: str, **source: Any) -> dict[str, Any]:
    return {"claims": [{"text": text, "source": source}] if source else [{"text": text}]}


def test_claim_without_citation_or_passage() -> None:
    assert statuses(claimtrace(claim("X"))) == ["NO_CITATION"]
    assert statuses(claimtrace(claim("X", id="s"))) == ["SOURCE_UNAVAILABLE"]


def test_abstract_cannot_support() -> None:
    result = claimtrace(claim("X", passage="abstract", kind="abstract"))
    assert statuses(result) == ["HUMAN_REVIEW_REQUIRED"]
    assert "cannot establish support" in result["findings"][0]["message"]


def test_equivalent_numbers_are_not_flagged() -> None:
    result = claimtrace(claim("Rates fell by 12.5% in 1000 cases", passage="fell 12.50% of 1,000"))
    assert result["findings"][0]["evidence"]["numbers_missing_from_passage"] == []


def test_missing_number_is_flagged() -> None:
    result = claimtrace(claim("Rates fell by 15%", passage="Rates fell by 12%"))
    evidence = result["findings"][0]["evidence"]
    assert evidence["numbers_missing_from_passage"] == ["15%"]
    assert "overstatement" in result["findings"][0]["message"]


def test_exact_text_ignores_case_and_spacing() -> None:
    result = claimtrace(claim("rates   fell", passage="The Rates fell sharply."))
    assert result["findings"][0]["evidence"]["exact_text"] is True


BIB = """
@article{lovelace2020,
  title = {A {Study} of Things},
  author = {Lovelace, Ada and Turing, Alan},
  year = 2020,
  journal = "J Things",
  doi = {10.1/x},
}
@comment{ignore me}
@inproceedings{k2,
  title={Second},
  booktitle={Proc. X},
  year={2021}
}
"""


def test_bibtex_parser() -> None:
    refs = parse_bibtex(BIB)
    assert [r["id"] for r in refs] == ["lovelace2020", "k2"]
    first = refs[0]
    assert first["title"] == "A Study of Things"
    assert first["authors"] == ["Lovelace, Ada", "Turing, Alan"]
    assert first["year"] == "2020" and first["doi"] == "10.1/x" and first["journal"] == "J Things"
    assert refs[1]["journal"] == "Proc. X"


def test_bibtex_unbalanced_is_an_error() -> None:
    with pytest.raises(InputError):
        parse_bibtex("@article{a, title = {oops")


def test_cli_end_to_end(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    bib.write_text(BIB, encoding="utf-8")
    skeleton = tmp_path / "in.json"
    assert (
        main(
            ["from-bibtex", str(bib), "--input-out", str(skeleton), "-o", str(tmp_path / "c.json")]
        )
        == 0
    )
    data = json.loads(skeleton.read_text(encoding="utf-8"))
    data["catalogue"] = [rec(doi="10.1/x", title="A Study of Things", year="2020")]
    data["references"] = data["references"][:1]
    data["citations"] = ["lovelace2020"]
    skeleton.write_text(json.dumps(data), encoding="utf-8")
    report = tmp_path / "report.json"
    code = main(
        ["check", str(skeleton), "-o", str(report), "--html", str(tmp_path / "r.html"), "--strict"]
    )
    assert code == 0
    assert json.loads(report.read_text(encoding="utf-8"))["findings"][0]["status"] == "VERIFIED"
    assert "CiteProof" in (tmp_path / "r.html").read_text(encoding="utf-8")


def test_cli_strict_flags_problems(tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text(
        json.dumps({"references": [ref()], "catalogue": [], "citations": ["a"]}), encoding="utf-8"
    )
    assert main(["check", str(src), "--strict", "-o", str(tmp_path / "o.json")]) == 1
    assert main(["check", str(src), "-o", str(tmp_path / "o.json")]) == 0


def test_cli_rejects_output_over_input(tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text(json.dumps({"claims": []}), encoding="utf-8")
    assert main(["claims", str(src), "-o", str(src)]) == 2
    assert json.loads(src.read_text(encoding="utf-8")) == {"claims": []}


def test_cli_bad_json_exits_2(tmp_path: Path) -> None:
    src = tmp_path / "in.json"
    src.write_text('{"x": NaN}', encoding="utf-8")
    assert main(["claims", str(src)]) == 2
