"""Compare a reference list with a catalogue of known records.

The catalogue is data you supply (for example an export from Crossref, a library manager
or a database you trust). CiteProof never looks anything up online, so a reference that is
missing from the catalogue is "needs review", not "fabricated".
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from .core import InputError, finding, norm, report, require

DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/|^doi:\s*", re.I)
TITLE_NEAR = 0.9


def normalise_doi(value: Any) -> str:
    """Lowercase DOI without URL or 'doi:' prefix and without trailing punctuation."""
    text = DOI_PREFIX.sub("", str(value or "").strip())
    return text.rstrip(".,;)").lower()


def _given_family(name: str) -> str:
    """'Lovelace, Ada' and 'Ada Lovelace' are the same person."""
    family, comma, given = name.partition(",")
    if comma and "," not in given:
        return f"{given.strip()} {family.strip()}"
    return name


def _authors(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"\s*(?:;|\band\b|&)\s*", value)
    if not isinstance(value, list):
        raise InputError("authors must be a list or a string")
    return [norm(_given_family(str(a))) for a in value if str(a).strip()]


def _year(value: Any) -> str:
    match = re.search(r"\d{4}", str(value))
    return match.group() if match else norm(value)


NOTICE_PREFIX = re.compile(r"^\s*(?:retracted|retraction|withdrawn)\s*[:\-–—]\s*", re.I)
JOURNAL_FILLER = frozenset(
    {"of", "the", "and", "for", "in", "on", "de", "la", "le", "du", "des", "und", "der", "di", "et"}
)


# Standard abbreviations that drop letters from the middle of the word, so are not prefixes.
# Kept short on purpose: matching on letter subsequences alone would accept 'Nat Med' for
# 'Nature Methods'.
NON_PREFIX_ABBREVIATIONS = {
    "natl": "national",
    "intl": "international",
    "mgmt": "management",
    "govt": "government",
    "engrg": "engineering",
}


def _strip_notice(title: Any) -> str:
    """Publishers prefix a retracted paper's title with 'RETRACTED:'; the citation does not."""
    return NOTICE_PREFIX.sub("", str(title))


def _journal_tokens(name: Any) -> list[str]:
    return [t for t in norm(name).split() if t not in JOURNAL_FILLER]


def journal_abbreviates(short: Any, full: Any) -> bool:
    """True when `short` reads as a standard abbreviation of `full`.

    'Nat Prod Rep' abbreviates 'Natural Product Reports'; 'J Am Chem Soc' abbreviates 'Journal
    of the American Chemical Society'. Every word must be the same word, a prefix of it, or one
    of a few standard abbreviations such as 'Natl', and the word count must match once filler
    words (of, the, and) are dropped, so 'Nature' does not match 'Nature Medicine'. A one-letter
    word counts as 'J' for Journal, anywhere before the end, or inside a closing run of at least
    two letters ('U S A'). A single closing letter must match exactly, so 'Phys Rev A' does not
    match 'Physical Review Applied'. A subtitle after a colon in `full` ('Proceedings of the Royal
    Society B: Biological Sciences') may be left out.
    """
    a = _journal_tokens(short)
    candidates = [full, str(full).split(":", 1)[0]]
    return any(_tokens_abbreviate(list(a), _journal_tokens(c)) for c in candidates)


def _tokens_abbreviate(a: list[str], b: list[str]) -> bool:
    if not a or not b:
        return False
    while len(a) > len(b) and len(a[-1]) == 1:
        a.pop()
    if len(a) != len(b):
        return False
    run_start = len(a)  # start of the closing run of one-letter words
    while run_start > 0 and len(a[run_start - 1]) == 1:
        run_start -= 1
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        if x == y:
            continue
        if not y.startswith(x) and NON_PREFIX_ABBREVIATIONS.get(x) != y:
            return False
        if len(x) == 1:
            in_closing_run = i >= run_start and len(a) - run_start >= 2
            if not (in_closing_run or i < len(a) - 1 or (x == "j" and y == "journal")):
                return False
    return True


def compare_metadata(
    ref: dict[str, Any], record: dict[str, Any], notes: list[str] | None = None
) -> dict[str, Any]:
    """Field-by-field differences between a reference and its catalogue record.

    Equivalences that were accepted rather than ignored (an abbreviated journal name, a
    'RETRACTED:' title prefix) are appended to `notes` so the caller can show them.
    """
    differences: dict[str, Any] = {}
    for field in ("title", "authors", "year", "journal"):
        if field not in ref or field not in record:
            differences[field] = {"reason": "missing metadata"}
            continue
        if field == "authors":
            mine, theirs = _authors(ref[field]), _authors(record[field])
            if mine == theirs:
                continue
            same_people = sorted(mine) == sorted(theirs)
            differences[field] = {
                "reference": ref[field],
                "catalogue": record[field],
                "note": "same authors in a different order" if same_people else "different authors",
            }
        elif field == "year":
            if _year(ref[field]) != _year(record[field]):
                differences[field] = {"reference": ref[field], "catalogue": record[field]}
        else:
            mine, theirs = ref[field], record[field]
            if norm(mine) == norm(theirs):
                continue
            if field == "title":
                mine, theirs = _strip_notice(mine), _strip_notice(theirs)
                if norm(mine) == norm(theirs):
                    if notes is not None:
                        notes.append("title: retraction or withdrawal prefix ignored")
                    continue
            if field == "journal" and (
                journal_abbreviates(ref[field], record[field])
                or journal_abbreviates(record[field], ref[field])
            ):
                if notes is not None:
                    notes.append("journal: abbreviation accepted")
                continue
            diff: dict[str, Any] = {"reference": ref[field], "catalogue": record[field]}
            if field == "title":
                ratio = SequenceMatcher(None, norm(mine), norm(theirs)).ratio()
                diff["similarity"] = round(ratio, 3)
                diff["note"] = (
                    "near match, probably a typo" if ratio >= TITLE_NEAR else "different title"
                )
            differences[field] = diff
    return differences


def citeproof(data: dict[str, Any]) -> dict[str, Any]:
    refs = require(data, "references", list)
    records = require(data, "catalogue", list)
    citations = require(data, "citations", list)
    ids = [require(r, "id", str) for r in refs]
    if len(set(ids)) != len(ids):
        raise InputError("Reference ids must be unique")
    catalogue: dict[str, dict[str, Any]] = {}
    for record in records:
        doi = normalise_doi(require(record, "doi", str))
        if doi in catalogue:
            raise InputError(f"Catalogue DOI appears twice: {doi}")
        catalogue[doi] = record

    out: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for ref in refs:
        doi = normalise_doi(ref.get("doi"))
        key = doi or norm(ref.get("title", ""))
        if key and key in seen:
            out.append(
                finding(
                    "DUPLICATE",
                    "Same DOI or normalised title as an earlier reference.",
                    reference=ref["id"],
                    duplicate_of=seen[key],
                )
            )
        elif key:
            seen[key] = ref["id"]
        record = catalogue.get(doi) if doi else None
        if record is None:
            reason = "has no DOI" if not doi else "is not in the supplied catalogue"
            out.append(
                finding(
                    "NEEDS_REVIEW",
                    f"Reference {reason}; this does not show it is fabricated.",
                    reference=ref["id"],
                )
            )
        else:
            notes: list[str] = []
            differences = compare_metadata(ref, record, notes)
            extra = {"accepted_equivalences": notes} if notes else {}
            out.append(
                finding(
                    "METADATA_MISMATCH" if differences else "VERIFIED",
                    "Compared with the supplied catalogue only.",
                    reference=ref["id"],
                    doi=doi,
                    differences=differences,
                    provenance=record.get("provenance", "unspecified"),
                    **extra,
                )
            )
            if record.get("retracted") is True:
                out.append(
                    finding(
                        "RETRACTED",
                        "The catalogue marks this work as retracted; check the flag's source.",
                        reference=ref["id"],
                    )
                )
            elif "retracted" not in record:
                out.append(
                    finding(
                        "NEEDS_REVIEW", "Retraction status was not supplied.", reference=ref["id"]
                    )
                )
        if ref["id"] not in citations:
            out.append(
                finding(
                    "UNCITED_REFERENCE",
                    "In the bibliography but not cited in the text.",
                    reference=ref["id"],
                )
            )
    for cite in sorted(set(citations) - set(ids)):
        out.append(
            finding(
                "MISSING_REFERENCE", "Cited in the text but not in the bibliography.", citation=cite
            )
        )
    return report(
        "CiteProof",
        out,
        scope="comparison with a catalogue you supply; no online lookup, no manuscript parsing",
    )
