"""Data handling for the CiteProof browser demo.

This file is the demo's only logic. It runs in the browser (Pyodide) and under pytest, and it
uses nothing outside the standard library and CiteProof itself.

What it does:
  * reads what the student pastes (BibTeX or CiteProof JSON) and the catalogue file (JSON or CSV);
  * calls CiteProof's own `citeproof()` and `parse_bibtex()` unchanged;
  * turns CiteProof's findings into one row per reference plus a summary, without changing a
    verdict or a message (the demo's own explanations are stored in separate fields);
  * builds the CSV export, and maps an optional Crossref response to a catalogue record.

It never opens a file or a network connection.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import sys
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote, urlencode

from text_references import parse_text_references

from citeproof import __version__ as CITEPROOF_VERSION
from citeproof.bibtex import parse_bibtex
from citeproof.core import InputError, norm
from citeproof.references import TITLE_NEAR, citeproof, normalise_doi

MAX_INPUT_CHARS = 300_000
MAX_CATALOGUE_CHARS = 8_000_000
MAX_REFERENCES = 500
MAX_CATALOGUE_RECORDS = 50_000
MAX_LOOKUPS = 25

CROSSREF_WORKS = "https://api.crossref.org/works/"
CROSSREF_SEARCH = "https://api.crossref.org/works?"
SEARCH_FIELDS = "DOI,title,author,issued,container-title"
MIN_SEARCH_TITLE = 12
DOI_SHAPE = re.compile(r"^10\.\d{4,9}/\S+$")

# CiteProof gives each reference exactly one of these as its comparison finding.
COMPARISON = ("VERIFIED", "METADATA_MISMATCH", "NEEDS_REVIEW")
BUCKET = {
    "VERIFIED": "verified",
    "METADATA_MISMATCH": "metadata_mismatch",
    "NEEDS_REVIEW": "no_verdict",
}

# The demo's own plain-language lines. They sit beside CiteProof's wording, never in place of it.
HEADLINES = {
    "VERIFIED": "Matches a record in this catalogue.",
    "METADATA_MISMATCH": "Found in this catalogue, but some details differ.",
    "METADATA_MISMATCH_INITIALS": "Found in this catalogue. Only the authors' given names differ.",
    "NEEDS_REVIEW_NOT_FOUND": "Not found in this catalogue.",
    "NEEDS_REVIEW_NO_DOI": "No DOI, so it could not be looked up in this catalogue.",
}
PERSON_NOTE = (
    "CiteProof does not decide whether this reference is acceptable. A person must decide."
)

CSV_COLUMNS = [
    "reference_id",
    "verdict",
    "other_flags",
    "citeproof_message",
    "plain_language_note",
    "doi_as_given",
    "title_as_given",
    "evidence",
    "catalogue_used",
    "citeproof_version",
    "person_decision",
]
CATALOGUE_FIELDS = ("doi", "title", "authors", "year", "journal", "retracted", "provenance")
NUMBERED_LIST = re.compile(r"^\[\s*\d{1,3}\s*\]")
TRUE_WORDS = {"true", "yes", "y", "1"}
FALSE_WORDS = {"false", "no", "n", "0"}


class DemoError(ValueError):
    """A problem with what the student supplied, worded for the student."""

    def __init__(self, title: str, message: str, hint: str = "", detail: str = "") -> None:
        super().__init__(f"{title}: {message}")
        self.title, self.message, self.hint, self.detail = title, message, hint, detail

    def as_dict(self) -> dict[str, str]:
        return {
            "title": self.title,
            "message": self.message,
            "hint": self.hint,
            "detail": self.detail,
        }


# --------------------------------------------------------------------------- errors


def explain_error(exc: BaseException) -> DemoError:
    """Rewrite an error from CiteProof or the parsers in plain words, keeping CiteProof's text."""
    if isinstance(exc, DemoError):
        return exc
    text = str(exc)
    detail = f"CiteProof said: {text}"
    if text == "Reference ids must be unique":
        return DemoError(
            "Two references share the same id",
            'CiteProof needs each reference to have its own id (the BibTeX key, or "id" in JSON).',
            "Rename one of the duplicates, then check again.",
            detail,
        )
    if text.startswith("Catalogue DOI appears twice"):
        return DemoError(
            "The catalogue lists the same DOI twice",
            f"{text.split(':', 1)[-1].strip()} appears more than once, and CiteProof will not "
            "guess "
            "which record to trust.",
            "Remove the repeated row from the catalogue file.",
            detail,
        )
    if text in ("'doi' must be str", "'id' must be str"):
        which = "a catalogue record" if "doi" in text else "a reference"
        field = "doi" if "doi" in text else "id"
        return DemoError(
            f'{which.capitalize()} has no "{field}" text',
            f'Every {which.split()[-1]} needs a "{field}" value.',
            "Add the missing value (CSV rows with a blank DOI are skipped, JSON records are not).",
            detail,
        )
    if text.endswith("must be list"):
        key = text.split("'")[1] if "'" in text else "a field"
        return DemoError(
            f'"{key}" must be a list', "CiteProof expects a list of items there.", "", detail
        )
    if text.startswith("Unbalanced braces"):
        return DemoError(
            "A BibTeX entry is not closed",
            "An opening { has no matching closing }.",
            "Check that every entry, and every {braced} field value, is closed.",
            detail,
        )
    if text.startswith("authors must be"):
        return DemoError(
            "Authors are in a form CiteProof cannot read",
            'Authors must be a list of names, or one text like "A. Author; B. Writer".',
            "",
            detail,
        )
    if text.startswith("Non-finite JSON number"):
        return DemoError(
            "The JSON contains NaN or Infinity",
            "JSON has no such numbers, and CiteProof refuses them.",
            "Replace them with real numbers or remove them.",
            detail,
        )
    if isinstance(exc, InputError):
        return DemoError("CiteProof could not use this input", text, "", detail)
    return DemoError(
        "CiteProof stopped on something it could not read",
        f"{type(exc).__name__}: {text}",
        "Check the input format, or load one of the samples to compare.",
        "",
    )


def _load_json(text: str, what: str) -> Any:
    def reject(value: str) -> Any:
        raise InputError(f"Non-finite JSON number: {value}")

    try:
        return json.loads(text, parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise DemoError(
            f"Could not read {what} as JSON",
            f"{exc.msg} (line {exc.lineno}, column {exc.colno}).",
            "Look for a missing comma, quote or bracket near that position.",
        ) from exc
    except InputError as exc:
        raise explain_error(exc) from exc
    except RecursionError as exc:
        raise DemoError(f"Could not read {what} as JSON", "It is nested too deeply.") from exc


# --------------------------------------------------------------------------- input


def parse_references(text: str) -> dict[str, Any]:
    """Read pasted references: BibTeX, or CiteProof JSON (a full input, or a bare list)."""
    stripped = (text or "").lstrip("﻿").strip()
    if not stripped:
        raise DemoError(
            "Nothing to check yet",
            "The reference box is empty.",
            "Paste your reference list (copied from a document, Google Scholar or a reference "
            "manager), or press one of the sample buttons.",
        )
    if len(stripped) > MAX_INPUT_CHARS:
        raise DemoError(
            "That list is too long for this demo",
            f"The limit is {MAX_INPUT_CHARS:,} characters ({len(stripped):,} pasted).",
            "Check a smaller batch, or run CiteProof on your own computer.",
        )
    notices: list[str] = []
    if stripped[0] == "{" or (stripped[0] == "[" and not NUMBERED_LIST.match(stripped)):
        data = _load_json(stripped, "your reference list")
        if isinstance(data, list):
            data = {"references": data}
        if not isinstance(data, dict):
            raise DemoError("Unexpected JSON", "Expected an object or a list of references.")
        references = data.get("references")
        citations = data.get("citations")
        if citations is None and isinstance(references, list):
            ids = [r.get("id") for r in references if isinstance(r, dict)]
            citations = [i for i in ids if isinstance(i, str)]
            notices.append(
                'No "citations" list was supplied, so every reference is treated as cited '
                "(the same as CiteProof's from-bibtex)."
            )
        parsed = {"format": "json", "references": references, "citations": citations}
        parsed["catalogue"] = data.get("catalogue")
    else:
        try:
            entries = parse_bibtex(stripped)
        except InputError as exc:
            raise explain_error(exc) from exc
        except ValueError as exc:
            raise DemoError(
                "A BibTeX field is not closed",
                "A field value opens with a quote mark that never closes.",
                "Check the quote marks and braces in your entries.",
            ) from exc
        if entries:
            parsed = {
                "format": "bibtex",
                "references": entries,
                "citations": [r["id"] for r in entries],
                "catalogue": None,
            }
            notices.append(
                "BibTeX: every entry is treated as cited, as in CiteProof's from-bibtex, so the "
                "uncited and missing-reference checks cannot trigger. Use JSON with a "
                '"citations" list to use them.'
            )
        else:
            parsed = _read_plain_text(stripped, notices)
    if isinstance(parsed["references"], list) and len(parsed["references"]) > MAX_REFERENCES:
        raise DemoError(
            "Too many references for this demo",
            f"The limit is {MAX_REFERENCES} ({len(parsed['references'])} found).",
            "Check a smaller batch, or run CiteProof on your own computer.",
        )
    parsed["notices"] = notices
    return parsed


def _read_plain_text(text: str, notices: list[str]) -> dict[str, Any]:
    found = parse_text_references(text)
    if not found["references"]:
        raise DemoError(
            "No references found in that text",
            "No line looked like a reference: none had a DOI or a year.",
            "Paste one reference per line or paragraph (for example from your reference list "
            "or from Google Scholar's Cite box), or use BibTeX or CiteProof JSON.",
        )
    ids = [r["id"] for r in found["references"]]
    notices.append(
        f"Plain text: found {len(ids)} reference(s), read by this page's own reader (not part "
        'of CiteProof). Open "Details" on a card to see how it was read. Fields it cannot '
        "read are left out, not guessed. Every entry is treated as cited."
    )
    if found["skipped"]:
        shown = "; ".join(f"\u201c{t[:60]}\u201d" for t in found["skipped"][:3])
        notices.append(
            f"{len(found['skipped'])} line(s) were skipped because they have no DOI and no year, "
            f"so they do not look like references: {shown}"
        )
    return {
        "format": "text",
        "references": found["references"],
        "citations": ids,
        "catalogue": None,
        "read": found["read"],
    }


def _retracted_cell(value: str, row: int) -> bool | None:
    word = value.strip().lower()
    if not word:
        return None
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise DemoError(
        'A "retracted" cell is not yes/no',
        f"Row {row} has {value!r}.",
        "Use true/false (or yes/no), or leave it blank when the retraction status is not known.",
    )


def _catalogue_from_csv(text: str) -> dict[str, Any]:
    sample = text[:4096]
    first_line = sample.splitlines()[0] if sample.splitlines() else ""
    delimiter = max(",;\t", key=first_line.count) if any(c in first_line for c in ",;\t") else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise DemoError("The catalogue file is empty", "No header row was found.") from None
    names = [h.strip().lower().lstrip("﻿") for h in header]
    names = ["authors" if n == "author" else n for n in names]
    if "doi" not in names:
        raise DemoError(
            'The catalogue needs a "doi" column',
            f"The columns found were: {', '.join(h.strip() for h in header) or '(none)'}.",
            "Use a header row with doi, title, authors, year, journal, retracted, provenance.",
        )
    ignored = sorted({n for n in names if n and n not in CATALOGUE_FIELDS})
    records: list[dict[str, Any]] = []
    skipped: list[int] = []
    for number, cells in enumerate(reader, start=2):
        if not any(c.strip() for c in cells):
            continue
        row = {n: c.strip() for n, c in zip(names, cells, strict=False) if n in CATALOGUE_FIELDS}
        if not row.get("doi"):
            skipped.append(number)
            continue
        record: dict[str, Any] = {k: v for k, v in row.items() if v and k != "retracted"}
        flag = _retracted_cell(row.get("retracted", ""), number)
        if flag is not None:
            record["retracted"] = flag
        records.append(record)
        if len(records) > MAX_CATALOGUE_RECORDS:
            raise DemoError(
                "That catalogue is too large for this demo",
                f"The limit is {MAX_CATALOGUE_RECORDS:,} records.",
            )
    notices: list[str] = []
    if skipped:
        shown = ", ".join(str(n) for n in skipped[:5]) + (" and more" if len(skipped) > 5 else "")
        notices.append(
            f"{len(skipped)} row(s) with no DOI were skipped (rows {shown}); "
            "they cannot be matched."
        )
    if ignored:
        notices.append(f"Ignored columns: {', '.join(ignored)}.")
    if "retracted" not in names:
        notices.append(
            'There is no "retracted" column, so CiteProof will say the retraction status '
            "was not supplied for every match."
        )
    return {"format": "csv", "records": records, "notices": notices}


def parse_catalogue(text: str, filename: str = "") -> dict[str, Any]:
    """Read a catalogue file: JSON (a list, or an object with "catalogue") or CSV."""
    body = (text or "").lstrip("﻿")
    if not body.strip():
        raise DemoError("The catalogue file is empty", f"{filename or 'The file'} has no content.")
    if len(body) > MAX_CATALOGUE_CHARS:
        raise DemoError(
            "That catalogue file is too large for this demo",
            f"The limit is {MAX_CATALOGUE_CHARS // 1_000_000} MB of text.",
            "Use a smaller extract, or run CiteProof on your own computer.",
        )
    if body.lstrip()[0] in "{[":
        data = _load_json(body, filename or "the catalogue file")
        if isinstance(data, dict):
            data = data.get("catalogue")
        if not isinstance(data, list):
            raise DemoError(
                "No catalogue found in that JSON",
                'Expected a list of records, or an object with a "catalogue" list.',
            )
        for index, record in enumerate(data, start=1):
            if not isinstance(record, dict):
                raise DemoError(
                    "A catalogue record is not an object",
                    f'Item {index} should look like {{"doi": ...}}.',
                )
        result = {"format": "json", "records": data, "notices": []}
    else:
        result = _catalogue_from_csv(body)
    if not result["records"]:
        raise DemoError("The catalogue has no usable records", "Every row was empty or had no DOI.")
    if len(result["records"]) > MAX_CATALOGUE_RECORDS:
        raise DemoError(
            "That catalogue is too large for this demo",
            f"The limit is {MAX_CATALOGUE_RECORDS:,} records.",
        )
    return result


# --------------------------------------------------------------------------- results


def _percent(count: int, total: int) -> float | None:
    return round(100 * count / total, 1) if total else None


def _show(value: Any, limit: int = 4) -> str:
    if isinstance(value, list):
        names = [str(v) for v in value]
        extra = f" … (+{len(names) - limit} more)" if len(names) > limit else ""
        return "; ".join(names[:limit]) + extra
    return str(value)


def _clean_name(name: Any) -> str:
    return str(name).strip()


def _family_name(name: Any) -> str:
    """The family name as written: 'Harris' from 'Harris, Charles R.' or 'Charles Harris'."""
    text = _clean_name(name)
    if "," in text:
        return text.split(",", 1)[0].strip()
    return text.split()[-1] if text.split() else ""


def _surname(name: Any) -> str:
    return norm(_family_name(name))


def _author_hint(mine: Any, theirs: Any) -> str:
    """Why 'different authors' may only mean the names are written differently."""
    if not isinstance(mine, list) or not isinstance(theirs, list):
        return ""
    cut = any(re.search(r"et al|\u2026|\.\.\.", str(a)) for a in mine)
    if len(mine) != len(theirs):
        text = f"Your list has {len(mine)} author(s) and the catalogue has {len(theirs)}."
        if cut or len(mine) < len(theirs):
            text += (
                " CiteProof compares whole lists, so a shortened list (\u201cet al.\u201d, "
                "\u201c\u2026\u201d) counts as a difference."
            )
        return text
    if [_surname(a) for a in mine] == [_surname(a) for a in theirs]:
        return (
            "The family names match in the same order. CiteProof compares given names letter "
            "for letter, so initials (\u201cMcKinney, W.\u201d) differ from full names "
            "(\u201cMcKinney, Wes\u201d)."
        )
    return ""


def _only_given_names_differ(differences: dict[str, Any]) -> bool:
    """True when authors are the only difference and every family name matches in order.

    This is display only. CiteProof still reports METADATA_MISMATCH for it; the page just says
    that the difference is limited to how given names are written (initials or full names).
    """
    if set(differences) != {"authors"}:
        return False
    mine, theirs = differences["authors"].get("reference"), differences["authors"].get("catalogue")
    if not isinstance(mine, list) or not isinstance(theirs, list) or len(mine) != len(theirs):
        return False
    if any(re.search(r"et al|\u2026|\.\.\.", str(a)) for a in mine):
        return False
    return [_surname(a) for a in mine] == [_surname(a) for a in theirs]


def _difference_lines(
    differences: dict[str, Any],
    ref: dict[str, Any],
    record: dict[str, Any],
    from_text: bool = False,
) -> list[dict[str, str]]:
    lines = []
    for field, diff in differences.items():
        if diff.get("reason") == "missing metadata":
            gaps = []
            for side, source in (("your reference", ref), ("the catalogue record", record)):
                if field in source:
                    continue
                gaps.append("your pasted text" if from_text and side == "your reference" else side)
            where = " and ".join(gaps)
            tail = (
                "it could not be read from there, so it was not compared."
                if "your pasted text" in gaps
                else "so it could not be compared."
            )
            value = f"{field} is missing from {where}; {tail}"
        else:
            mine, theirs = _show(diff["reference"]), _show(diff["catalogue"])
            value = f"you wrote {mine!r}; the catalogue has {theirs!r}"
            if "similarity" in diff:
                value += f" (title similarity {diff['similarity']})"
            if "note" in diff:
                value += f" - CiteProof: {diff['note']}"
            if field == "authors" and diff.get("note") == "different authors":
                hint = _author_hint(diff["reference"], diff["catalogue"])
                if hint:
                    value += f". Note: {hint}"
        lines.append({"label": f"Difference in {field}", "value": value})
    return lines


def _title_hints(text: str, records: list[dict[str, Any]], contained: bool) -> list[dict[str, Any]]:
    """Catalogue records whose title is in `text`. Advisory only: CiteProof matches by DOI."""
    wanted, found = norm(text), []
    for record in records:
        title = norm(record.get("title", ""))
        if len(title) < 20 or not wanted:
            continue
        if contained:
            same = title in wanted
        else:
            same = SequenceMatcher(None, wanted, title).ratio() >= TITLE_NEAR
        if same:
            found.append(record)
    return found[:3]


def _read_view(info: dict[str, Any] | None, ref: dict[str, Any]) -> dict[str, Any] | None:
    """What the plain-text reader took from a pasted reference (None for BibTeX and JSON)."""
    if not info:
        return None
    labels = (
        ("doi", "DOI"),
        ("authors", "Authors"),
        ("year", "Year"),
        ("title", "Title"),
        ("journal", "Journal"),
    )
    fields = [
        {"label": label, "value": _show(ref[key], limit=6) if key in ref else "not read"}
        for key, label in labels
    ]
    return {"raw": info["raw"], "style": info["style"], "fields": fields}


def _flag_note(flag: dict[str, Any]) -> str:
    evidence = flag["evidence"]
    status = flag["status"]
    if status == "DUPLICATE":
        earlier = evidence.get("duplicate_of")
        return f"Same DOI or title as reference {earlier!r}, which appears earlier."
    if status == "RETRACTED":
        return (
            "The catalogue says this work was retracted. Read the retraction notice and "
            "check where the flag came from."
        )
    if status == "UNCITED_REFERENCE":
        return "The reference list has this entry but the citation list does not mention it."
    if flag["message"] == "Retraction status was not supplied.":
        return (
            "The catalogue record does not say whether the work was retracted, "
            "so that was not checked."
        )
    return ""


def build_result(
    parsed: dict[str, Any],
    report: dict[str, Any],
    records: list[dict[str, Any]],
    catalogue_label: str,
    notices: list[str],
) -> dict[str, Any]:
    by_doi = {normalise_doi(r["doi"]): r for r in records}
    findings = report["findings"]
    refs: list[dict[str, Any]] = parsed["references"]
    read_info: dict[str, Any] = parsed.get("read") or {}
    chosen: dict[str, str] = parsed.get("chosen") or {}
    rows: list[dict[str, Any]] = []
    initials_rows = 0
    counts = {"verified": 0, "metadata_mismatch": 0, "no_verdict": 0}
    flags_count = {
        "DUPLICATE": 0,
        "RETRACTED": 0,
        "RETRACTION_STATUS_NOT_SUPPLIED": 0,
        "UNCITED_REFERENCE": 0,
        "MISSING_REFERENCE": 0,
    }
    for ref in refs:
        mine = [f for f in findings if f["evidence"].get("reference") == ref["id"]]
        comparison = next((f for f in mine if f["status"] != "DUPLICATE"), None)
        if comparison is None or comparison["status"] not in COMPARISON:
            raise RuntimeError(f"CiteProof gave reference {ref['id']!r} no comparison finding")
        rest = [f for f in mine if f is not comparison]
        verdict = comparison["status"]
        counts[BUCKET[verdict]] += 1
        doi = normalise_doi(ref.get("doi"))
        record = by_doi.get(doi) if doi else None
        evidence: list[dict[str, str]] = []
        if ref["id"] in chosen:
            evidence.append(
                {
                    "label": "DOI added by you",
                    "value": (
                        f"{chosen[ref['id']]} was chosen by you from a Crossref title search. "
                        "It was not in your pasted reference."
                    ),
                }
            )
        if verdict == "VERIFIED":
            headline = HEADLINES["VERIFIED"]
            evidence.append({"label": "Matched by DOI", "value": doi})
            evidence.append(
                {"label": "Compared", "value": "title, authors, year and journal all match"}
            )
        elif verdict == "METADATA_MISMATCH":
            initials_only = _only_given_names_differ(comparison["evidence"]["differences"])
            initials_rows += initials_only
            headline = HEADLINES[
                "METADATA_MISMATCH_INITIALS" if initials_only else "METADATA_MISMATCH"
            ]
            evidence.append({"label": "Matched by DOI", "value": doi})
            evidence += _difference_lines(
                comparison["evidence"]["differences"], ref, record or {}, ref["id"] in read_info
            )
        elif doi:
            headline = HEADLINES["NEEDS_REVIEW_NOT_FOUND"]
            evidence.append({"label": "DOI looked up", "value": doi})
            evidence.append(
                {
                    "label": "Catalogue searched",
                    "value": f"{catalogue_label} ({len(records)} records)",
                }
            )
            evidence.append(
                {"label": "Result", "value": "No record with this DOI. That is all this shows."}
            )
        else:
            headline = HEADLINES["NEEDS_REVIEW_NO_DOI"]
            evidence.append({"label": "DOI in your reference", "value": "none given"})
            evidence.append(
                {
                    "label": "Catalogue searched",
                    "value": "not searched (CiteProof looks records up by DOI)",
                }
            )
        if verdict == "NEEDS_REVIEW":
            raw = read_info.get(ref["id"], {}).get("raw")
            text = raw if raw else str(ref.get("title", ""))
            other = (
                " Your reference gives a different DOI." if normalise_doi(ref.get("doi")) else ""
            )
            for hit in _title_hints(text, records, contained=bool(raw)):
                evidence.append(
                    {
                        "label": "Possible match by title (advisory)",
                        "value": (
                            f"The catalogue has \u201c{hit.get('title')}\u201d "
                            f"(DOI {hit.get('doi')}, {hit.get('year', 'no year')}) with this "
                            f"title.{other} CiteProof matches by DOI only, so this did not change "
                            "the verdict. A person should check."
                        ),
                    }
                )
        if record is not None:
            evidence.append(
                {
                    "label": "Catalogue provenance",
                    "value": str(record.get("provenance", "unspecified")),
                }
            )
        row_flags = []
        for flag in rest:
            if flag["status"] == "RETRACTED":
                flags_count["RETRACTED"] += 1
            elif flag["status"] == "DUPLICATE":
                flags_count["DUPLICATE"] += 1
            elif flag["status"] == "UNCITED_REFERENCE":
                flags_count["UNCITED_REFERENCE"] += 1
            elif flag["message"] == "Retraction status was not supplied.":
                flags_count["RETRACTION_STATUS_NOT_SUPPLIED"] += 1
            row_flags.append(
                {"status": flag["status"], "message": flag["message"], "note": _flag_note(flag)}
            )
        rows.append(
            {
                "id": ref["id"],
                "title": str(ref.get("title", "")),
                "doi_as_given": "" if ref["id"] in chosen else str(ref.get("doi", "") or ""),
                "doi_chosen": ref["id"] in chosen,
                "verdict": verdict,
                "message": comparison["message"],
                "headline": headline,
                "evidence": evidence,
                "flags": row_flags,
                "person_note": PERSON_NOTE,
                "read": _read_view(read_info.get(ref["id"]), ref),
                "from_crossref": bool(
                    record and str(record.get("provenance", "")).startswith("Crossref REST API")
                ),
            }
        )
    missing = []
    for finding in findings:
        if finding["status"] == "MISSING_REFERENCE":
            flags_count["MISSING_REFERENCE"] += 1
            missing.append(
                {
                    "id": finding["evidence"]["citation"],
                    "verdict": "MISSING_REFERENCE",
                    "message": finding["message"],
                    "person_note": PERSON_NOTE,
                }
            )
    total = len(refs)
    if sum(counts.values()) != total:
        raise RuntimeError("Summary counts do not add up to the number of references")
    summary = {"total": total}
    for key, count in counts.items():
        summary[key] = {"count": count, "percent": _percent(count, total)}
    summary["metadata_mismatch"]["only_given_names"] = initials_rows
    summary["other_flags"] = flags_count
    return {
        "ok": True,
        "citeproof_version": CITEPROOF_VERSION,
        "input_format": parsed["format"],
        "catalogue_label": catalogue_label,
        "catalogue_size": len(records),
        "summary": summary,
        "rows": rows,
        "missing_references": missing,
        "notices": notices,
        "lookup": lookup_candidates(rows),
        "search": search_plan(rows, refs),
        "report": report,
    }


def run_check(
    references_text: str,
    catalogue_records: list[dict[str, Any]] | None,
    catalogue_label: str,
    extra_records: list[dict[str, Any]] | None = None,
    doi_overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Check pasted references against a catalogue with CiteProof. Raises DemoError.

    `doi_overrides` maps a reference id to a DOI the person chose after a Crossref title search.
    It only applies to references that have no DOI of their own.
    """
    parsed = parse_references(references_text)
    notices = list(parsed.pop("notices"))
    if doi_overrides and isinstance(parsed["references"], list):
        chosen: dict[str, str] = {}
        references = []
        for ref in parsed["references"]:
            doi = doi_overrides.get(ref.get("id")) if isinstance(ref, dict) else None
            if doi and DOI_SHAPE.match(normalise_doi(doi)) and not normalise_doi(ref.get("doi")):
                ref = {**ref, "doi": doi}
                chosen[ref["id"]] = normalise_doi(doi)
            references.append(ref)
        parsed["references"], parsed["chosen"] = references, chosen
        if chosen:
            notices.append(
                f"{len(chosen)} DOI(s) were added by you from a Crossref title search; "
                "they were not in your pasted references."
            )
    embedded = parsed["catalogue"]
    if embedded is not None:
        records = embedded
        label = "the catalogue inside your pasted JSON"
        notices.append(
            'Your pasted JSON has its own "catalogue", which is used instead of the one selected.'
        )
    else:
        records = list(catalogue_records or [])
        label = catalogue_label
    if not isinstance(records, list):
        raise explain_error(InputError("'catalogue' must be list"))
    if not records:
        raise DemoError(
            "No catalogue loaded",
            "There is nothing to compare your references with.",
            "Use the sample catalogue or load your own file.",
        )
    added = 0
    if extra_records:
        have = {normalise_doi(r.get("doi")) for r in records if isinstance(r, dict)}
        for extra in extra_records:
            doi = normalise_doi(extra.get("doi"))
            if doi and doi not in have:
                records = [*records, extra]
                have.add(doi)
                added += 1
        if added:
            label = f"{label} + {added} from Crossref"
            notices.append(
                f"{added} record(s) were added from your Crossref lookup. Their provenance says so."
            )
    try:
        report = citeproof(
            {
                "references": parsed["references"],
                "catalogue": records,
                "citations": parsed["citations"],
            }
        )
    except (InputError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise explain_error(exc) from exc
    return build_result(parsed, report, records, label, notices)


# --------------------------------------------------------------------------- export


def _cell(value: Any) -> str:
    """Stop spreadsheet programs from running a cell as a formula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def results_to_csv(result: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    common = [result["catalogue_label"], result["citeproof_version"], ""]
    for row in result["rows"]:
        flags = "; ".join(f"{f['status']}: {f['message']}" for f in row["flags"])
        evidence = " | ".join(f"{e['label']}: {e['value']}" for e in row["evidence"])
        writer.writerow(
            [
                _cell(v)
                for v in (
                    row["id"],
                    row["verdict"],
                    flags,
                    row["message"],
                    row["headline"],
                    row["doi_as_given"],
                    row["title"],
                    evidence,
                    *common,
                )
            ]
        )
    for row in result["missing_references"]:
        writer.writerow(
            [
                _cell(v)
                for v in (row["id"], row["verdict"], "", row["message"], "", "", "", "", *common)
            ]
        )
    return out.getvalue()


# --------------------------------------------------------------------------- Crossref (optional)


def crossref_url(doi: str) -> str | None:
    """The one URL a lookup would fetch for this DOI, or None if it does not look like a DOI."""
    clean = normalise_doi(doi)
    return CROSSREF_WORKS + quote(clean, safe="/") if DOI_SHAPE.match(clean) else None


def lookup_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """DOIs a Crossref lookup could look up: references whose DOI is not in the catalogue."""
    seen: dict[str, str] = {}
    unusable: list[str] = []
    for row in rows:
        if row["verdict"] != "NEEDS_REVIEW" or not row["doi_as_given"].strip():
            continue
        doi = normalise_doi(row["doi_as_given"])
        url = crossref_url(doi)
        if url is None:
            unusable.append(row["doi_as_given"])
        elif doi not in seen:
            seen[doi] = url
    items = [{"doi": d, "url": u} for d, u in seen.items()]
    return {
        "items": items[:MAX_LOOKUPS],
        "truncated": max(0, len(items) - MAX_LOOKUPS),
        "unusable": unusable,
    }


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", str(value)))).strip()


def crossref_to_record(payload: Any, fetched_on: str, via: str = "DOI lookup") -> dict[str, Any]:
    """Map a Crossref /works/{doi} response to a catalogue record. Raises DemoError."""
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("DOI"), str):
        raise DemoError(
            "Crossref sent something unexpected", "The response had no work record with a DOI."
        )
    doi = message["DOI"]
    record: dict[str, Any] = {"doi": doi}
    titles = message.get("title")
    if isinstance(titles, list) and titles and _clean_text(titles[0]):
        record["title"] = _clean_text(titles[0])
    authors = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        family, given = author.get("family"), author.get("given")
        name = f"{family}, {given}" if family and given else family or given or author.get("name")
        if name:
            authors.append(_clean_text(name))
    if authors:
        record["authors"] = authors
    for key in ("issued", "published", "published-print", "published-online", "created"):
        try:
            year = message[key]["date-parts"][0][0]
        except (KeyError, IndexError, TypeError):
            continue
        if isinstance(year, int):
            record["year"] = str(year)
            break
    containers = message.get("container-title")
    if isinstance(containers, list) and containers and _clean_text(containers[0]):
        record["journal"] = _clean_text(containers[0])
    record["provenance"] = (
        f"Crossref REST API ({via}; api.crossref.org/works/{doi}), fetched live from your browser "
        f"on {fetched_on}; retraction status was not read from this response"
    )
    return record


def search_query(ref: dict[str, Any]) -> str | None:
    """The words a title search would send for one reference, or None if it has no usable title."""
    title = _clean_text(ref.get("title", ""))
    if len(title) < MIN_SEARCH_TITLE:
        return None
    authors = ref.get("authors")
    first = authors[0] if isinstance(authors, list) and authors else authors
    surname = _family_name(first) if isinstance(first, str) and first.strip() else ""
    year = re.search(r"\d{4}", str(ref.get("year", "")))
    return " ".join(part for part in (title, surname, year.group() if year else "") if part)


def crossref_search_url(query: str) -> str:
    """The one URL a title search fetches. Shown to the person before anything is sent."""
    params = {"query.bibliographic": query, "rows": 3, "select": SEARCH_FIELDS}
    return CROSSREF_SEARCH + urlencode(params, quote_via=quote)


def search_plan(rows: list[dict[str, Any]], refs: list[dict[str, Any]]) -> dict[str, Any]:
    """References with no DOI that a title search could try, and the ones it cannot."""
    by_id = {r["id"]: r for r in refs}
    items, unreadable = [], []
    for row in rows:
        if row["verdict"] != "NEEDS_REVIEW" or row["doi_as_given"].strip() or row["doi_chosen"]:
            continue
        query = search_query(by_id[row["id"]])
        if query is None:
            unreadable.append(row["id"])
        else:
            ref = by_id[row["id"]]
            items.append(
                {
                    "id": row["id"],
                    "title": _clean_text(ref.get("title", "")),
                    "year": _year_of(ref.get("year", "")),
                    "query": query,
                    "url": crossref_search_url(query),
                }
            )
    return {
        "items": items[:MAX_LOOKUPS],
        "truncated": max(0, len(items) - MAX_LOOKUPS),
        "unreadable": unreadable,
    }


def crossref_candidates(
    payload: Any, title: str, year: str, fetched_on: str
) -> list[dict[str, Any]]:
    """Possible DOIs from a Crossref search reply. Suggestions only: nothing is chosen here."""
    message = payload.get("message") if isinstance(payload, dict) else None
    items = message.get("items") if isinstance(message, dict) else None
    if not isinstance(items, list):
        raise DemoError(
            "Crossref sent something unexpected", "The search reply had no list of results."
        )
    found = []
    for item in items:
        try:
            record = crossref_to_record({"message": item}, fetched_on, via="title search")
        except DemoError:
            continue
        ratio = SequenceMatcher(None, norm(title), norm(record.get("title", ""))).ratio()
        found.append(
            {
                "doi": record["doi"],
                "title": record.get("title", "(no title)"),
                "authors": _show(record.get("authors", []), limit=4) or "(no authors listed)",
                "year": record.get("year", "year not given"),
                "journal": record.get("journal", "journal not given"),
                "title_similarity": round(ratio, 3),
                "year_matches": bool(year) and record.get("year") == _year_of(year),
                "record": record,
            }
        )
    return sorted(found, key=lambda c: c["title_similarity"], reverse=True)[:3]


def _year_of(value: Any) -> str:
    match = re.search(r"\d{4}", str(value))
    return match.group() if match else ""


# --------------------------------------------------------------------------- bridge for the page


def _wrap(call: Any) -> str:
    try:
        return json.dumps({"ok": True, **call()}, ensure_ascii=False, allow_nan=False)
    except DemoError as exc:
        return json.dumps({"ok": False, "error": exc.as_dict()}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": explain_error(exc).as_dict()}, ensure_ascii=False)


def api_info() -> str:
    return json.dumps({"citeproof_version": CITEPROOF_VERSION, "python": sys.version.split()[0]})


def api_parse_catalogue(text: str, filename: str) -> str:
    return _wrap(lambda: parse_catalogue(text, filename))


def api_check(
    references_text: str,
    catalogue_json: str,
    catalogue_label: str,
    extra_json: str,
    overrides_json: str = "",
) -> str:
    def call() -> dict[str, Any]:
        records = json.loads(catalogue_json) if catalogue_json else None
        extras = json.loads(extra_json) if extra_json else None
        overrides = json.loads(overrides_json) if overrides_json else None
        result = run_check(references_text, records, catalogue_label, extras, overrides)
        result.pop("ok")
        return result

    return _wrap(call)


def api_crossref_record(response_json: str, fetched_on: str) -> str:
    return _wrap(lambda: {"record": crossref_to_record(json.loads(response_json), fetched_on)})


def api_crossref_candidates(response_json: str, title: str, year: str, fetched_on: str) -> str:
    return _wrap(
        lambda: {
            "candidates": crossref_candidates(json.loads(response_json), title, year, fetched_on)
        }
    )


def api_csv(result_json: str) -> str:
    return _wrap(lambda: {"csv": results_to_csv(json.loads(result_json))})
