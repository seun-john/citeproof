"""Best-effort reading of references pasted as plain text.

This is the demo's own code and is not part of CiteProof, which reads BibTeX or JSON and does
not parse formatted text. It splits a pasted list into references and pulls out the DOI, authors,
year, title and journal where the layout is recognised (APA, Harvard, Chicago author-date, MLA,
Vancouver). A field it cannot read confidently is left out, never guessed, and the page shows
the student exactly what was read from each reference so a person can check it.
"""

from __future__ import annotations

import re
from typing import Any

DOI_IN_TEXT = re.compile(r"10\.\d{4,9}/[^\s\"<>]+")
URL = re.compile(r"https?://\S+", re.I)
YEAR = r"(?:19|20)\d{2}[a-z]?"
YEAR_ANYWHERE = re.compile(rf"\b{YEAR}\b")
NUMBERING = re.compile(r"^\s*(?:\[\d{1,3}\]|\(\d{1,3}\)|\d{1,3}[.)])\s+")
HEADINGS = {"references", "reference list", "bibliography", "works cited", "sources", "citations"}
INITIALS = r"(?:[^\W\d_]\.\s*-?\s*)+"
QUOTES = "\"'‘’“”`"
OPEN_QUOTE = "\"'‘“`"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean(text: str) -> str:
    return _squash(NUMBERING.sub("", text, count=1).replace("*", ""))


_NAME = r"[^\W\d_][\w'\u2019\-]*"
STARTS = re.compile(
    rf"^(?:{_NAME}\.?\s+){{0,4}}{_NAME},\s*[A-Z\u00c0-\u00d6\u00d8-\u00de]"  # Waskom, Michael
    rf"|^{_NAME}\s+[A-Z]{{1,3}}\b[,.]"  # Pedregosa F,
)
PAREN_YEAR = re.compile(rf"\(\s*{YEAR}\s*\)")


def _starts_reference(line: str) -> bool:
    """Does this line look like the first line of a reference (authors first)?"""
    line = line.strip()
    return bool(STARTS.match(line) or (line[:1].isalpha() and PAREN_YEAR.search(line[:150])))


def _is_complete(entry: str) -> bool:
    """A reference normally ends with a full stop, a DOI or link, or a page number."""
    entry = entry.strip()
    return bool(
        entry.endswith(".")
        or DOI_IN_TEXT.search(entry)
        or URL.search(entry)
        or entry[-1:].isdigit()
    )


def split_entries(text: str) -> list[str]:
    """Cut a pasted list into one string per reference."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
    if len(blocks) > 1:
        return [_clean(b) for b in blocks]
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) <= 1:
        return [_clean(text)] if text else []
    numbered = sum(bool(NUMBERING.match(ln)) for ln in lines)
    if numbered >= max(2, len(lines) // 2):
        entries: list[str] = []
        for ln in lines:
            if NUMBERING.match(ln) or not entries:
                entries.append(ln)
            else:
                entries[-1] += " " + ln
        return [_clean(e) for e in entries]
    if not lines[0][:1].isspace() and any(ln[:1].isspace() for ln in lines[1:]):
        entries = []
        for ln in lines:
            if ln[:1].isspace() and entries:
                entries[-1] += " " + ln
            else:
                entries.append(ln)
        return [_clean(e) for e in entries]
    if sum(_starts_reference(ln) for ln in lines) >= 2:
        # One reference per line, unless a line clearly continues the one before it.
        entries = []
        for ln in lines:
            continues = entries and not _starts_reference(ln) and not _is_complete(entries[-1])
            if continues:
                entries[-1] += " " + ln
            else:
                entries.append(ln)
        return [_clean(e) for e in entries]
    return [_clean(text)]


def _find_doi(text: str) -> str:
    match = DOI_IN_TEXT.search(text)
    if not match:
        return ""
    doi = match.group().rstrip(".,;:'’”")
    while doi.endswith(")") and doi.count(")") > doi.count("("):
        doi = doi[:-1]
    return doi


def _strip_links(text: str) -> str:
    text = re.sub(r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?10\.\d{4,9}/\S+", " ", text, flags=re.I)
    text = URL.sub(" ", text)
    text = re.sub(
        r"\b(?:retrieved from|available at|accessed|doi|url)\s*:?\s*$", "", text, flags=re.I
    )
    return _squash(text).rstrip(" .,;")


def _apa_authors(text: str) -> list[str] | None:
    """'Smith, J., & Doe, A. B.' -> ['Smith, J.', 'Doe, A. B.'] (None if it does not fit)."""
    pairs = re.findall(rf"([^,;&]+?),\s*({INITIALS})", text)
    if not pairs:
        return None
    rest = re.sub(rf"([^,;&]+?),\s*({INITIALS})", "", text)
    rest = re.sub(r"\b(?:et al\.?|and)\b|[&,;.…\s-]", "", rest)
    if rest:
        return None
    names = [f"{_squash(s).lstrip('& ')}, {_squash(i)}" for s, i in pairs]
    return [re.sub(r"^(?:and|&)\s+", "", n).strip() for n in names]


def _trim_name(name: str) -> str:
    """Strip spaces, and a full stop unless it ends an initial ('Michael L.')."""
    name = name.strip()
    return name if re.search(r"(?:^|[\s.-])[^\W\d_]\.$", name) else name.rstrip(" .")


def _generic_authors(text: str) -> list[str] | None:
    """Authors written 'A B and C D', 'A B; C D' or a single name. Anything ambiguous: None."""
    text = _squash(text)
    if text.endswith(".") and not re.search(r"[^\W\d_]\.$", text):
        text = text.rstrip(".")
    if not text or len(text) > 400:
        return None
    if ";" in text:
        parts = re.split(r"\s*;\s*", text)
    elif "," in text:
        if text.count(",") == 1 and " and " not in text and "&" not in text:
            return [text]  # one inverted name: 'Smith, Jane'
        return None
    else:
        parts = re.split(r"\s+(?:and|&)\s+", text)
    names = [_trim_name(p) for p in parts if _trim_name(p) and "et al" not in p]
    return names or None


def _vancouver_authors(text: str) -> list[str]:
    return [
        p.strip() for p in re.split(r",\s*", text.rstrip(".")) if p.strip() and "et al" not in p
    ]


def _journal_after(rest: str, volume_follows_name: bool = False) -> str:
    """The journal name at the start of what follows the title."""
    rest = rest.strip(" .,;:" + QUOTES)
    if re.match(r"in\b", rest, re.I):
        return ""
    stops = r",\s*(?=\d)|,\s*(?:vol|no|pp)\b|\.\s|\.$"
    if volume_follows_name:  # Chicago: 'Nature 585 (7825): 357-62'
        stops += r"|\s+\d+\s*(?:\(|:|,|$)"
    head = re.split(stops, rest, maxsplit=1)[0]
    return _squash(head.strip(" .,;:" + QUOTES))


def _quoted_title(text: str) -> tuple[str, str] | None:
    """Title in quotes at the start of text: ('Title', remainder)."""
    if not text or text[0] not in OPEN_QUOTE:
        return None
    match = re.match(
        rf"[{re.escape(OPEN_QUOTE)}](.+?)[,.?!]?[{re.escape(QUOTES)}]\s*,?\s*(.*)$", text
    )
    return (_squash(match.group(1)).rstrip(".,"), match.group(2)) if match else None


def _sentence_title(text: str) -> tuple[str, str] | None:
    match = re.match(r"(.+?[.?!])\s+(.+)$", text)
    return (_squash(match.group(1)).rstrip("."), match.group(2)) if match else None


def read_entry(raw: str) -> dict[str, Any]:
    """Fields read from one reference: doi, authors, year, title, journal (only those found)."""
    fields: dict[str, Any] = {}
    doi = _find_doi(raw)
    if doi:
        fields["doi"] = doi
    body = _strip_links(raw)
    style = "not recognised"

    apa = re.match(rf"^(?P<a>.+?)\s*\((?P<y>{YEAR})\)\s*[.,]?\s*(?P<rest>.+)$", body)
    chicago = re.match(rf"^(?P<a>.+?)\.\s+(?P<y>{YEAR})\.\s+(?P<rest>.+)$", body)
    mla = re.match(r"^(?P<a>.+?)\.\s+(?P<rest>[\"“‘].+)$", body)
    vancouver = re.match(
        rf"^(?P<a>[^.]+?(?:\s+et al)?)\.\s+(?P<t>.+?[.?!])\s+(?P<j>[^.]+?)\.\s+(?P<y>{YEAR})\b",
        body,
    )

    if apa:
        style = "APA or Harvard"
        authors = apa["a"].strip(" ,")
        fields["year"] = apa["y"]
        rest = apa["rest"]
        found = _quoted_title(rest) or _sentence_title(rest)
        if found:
            fields["title"], remainder = found
            journal = _journal_after(remainder)
            if journal:
                fields["journal"] = journal
        names = _apa_authors(authors) or _generic_authors(authors)
        if names:
            fields["authors"] = names
    elif chicago and _quoted_title(chicago["rest"]):
        style = "Chicago author-date"
        fields["year"] = chicago["y"]
        title, remainder = _quoted_title(chicago["rest"]) or ("", "")
        fields["title"] = title
        journal = _journal_after(remainder, volume_follows_name=True)
        if journal:
            fields["journal"] = journal
        names = _generic_authors(chicago["a"])
        if names:
            fields["authors"] = names
    elif mla and _quoted_title(mla["rest"]):
        style = "MLA"
        title, remainder = _quoted_title(mla["rest"]) or ("", "")
        fields["title"] = title
        journal = _journal_after(remainder)
        if journal:
            fields["journal"] = journal
        years = YEAR_ANYWHERE.findall(remainder)
        if years:
            fields["year"] = years[0]
        names = _generic_authors(mla["a"])
        if names:
            fields["authors"] = names
    elif vancouver:
        style = "Vancouver"
        fields["authors"] = _vancouver_authors(vancouver["a"])
        fields["title"] = _squash(vancouver["t"]).rstrip(".")
        fields["journal"] = _squash(vancouver["j"])
        fields["year"] = vancouver["y"]
    fields = {k: v for k, v in fields.items() if v}
    return {"style": style, "fields": fields}


def parse_text_references(text: str) -> dict[str, Any]:
    """Split pasted text and read each reference. Entries with no DOI and no year are skipped."""
    references: list[dict[str, Any]] = []
    read: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for entry in split_entries(text):
        if len(entry) < 15 or entry.lower().strip(" .:") in HEADINGS:
            continue
        if not (DOI_IN_TEXT.search(entry) or YEAR_ANYWHERE.search(entry)):
            skipped.append(entry)
            continue
        info = read_entry(entry)
        ref_id = f"ref{len(references) + 1}"
        references.append({"id": ref_id, **info["fields"]})
        read[ref_id] = {"raw": entry, **info}
    return {"references": references, "read": read, "skipped": skipped}
