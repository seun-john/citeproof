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


PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "du", "la", "le", "bin", "ibn",
    "al", "el", "ten", "ter", "zu", "zur", "dos", "das",
}  # fmt: skip


def _natural_to_inverted(name: str) -> str:
    """'Stéfan van der Walt' -> 'van der Walt, Stéfan'."""
    tokens = name.split()
    if len(tokens) < 2:
        return name
    cut = len(tokens) - 1
    while cut > 1 and tokens[cut - 1].lower() in PARTICLES:
        cut -= 1
    return f"{' '.join(tokens[cut:])}, {' '.join(tokens[:cut])}"


def _first_inverted_authors(text: str) -> list[str] | None:
    """Chicago and MLA: 'Harris, Charles R., Jarrod Millman, and Stéfan van der Walt'.

    The first author is written 'Family, Given' and the rest 'Given Family'.
    """
    text = _squash(text).rstrip(".")
    if len(text) > 400:
        return None
    tokens = [t.strip() for t in re.split(r",\s*(?:and\s+|&\s+)?", text) if t.strip()]
    tokens = [t for t in tokens if not re.fullmatch(r"et al\.?", t)]
    if len(tokens) < 2:
        return None
    first = f"{tokens[0]}, {tokens[1]}"
    rest = [_natural_to_inverted(_trim_name(t)) for t in tokens[2:]]
    return [_trim_name(first), *rest]


def _vancouver_authors(text: str) -> list[str]:
    return [
        p.strip() for p in re.split(r",\s*", text.rstrip(".")) if p.strip() and "et al" not in p
    ]


PAGES = r"[A-Za-z]?\d+(?:\s*[–—\-]\s*[A-Za-z]?\d+)?"
CONFERENCE = re.compile(
    r"^(?:proceedings?|proc\.?|conference|symposium|workshop|annual (?:conference|meeting)|"
    r"international (?:conference|symposium|workshop))\b",
    re.I,
)


def _split_journal(rest: str, volume_follows_name: bool = False) -> tuple[str, str]:
    """The journal name at the start of what follows the title, and the text after it."""
    rest = rest.strip(" ,;:" + QUOTES)
    if re.match(r"in\b", rest, re.I):
        return "", ""
    stops = r",\s*(?=\d)|,\s*(?:vol|no|pp)\b|\.\s|\.$"
    if volume_follows_name:  # Chicago: 'Nature 585 (7825): 357-62'
        stops += r"|\s+\d+\s*(?:\(|:|,|$)"
    found = re.search(stops, rest)
    head, tail = (rest[: found.start()], rest[found.start() :]) if found else (rest, "")
    return _squash(head.strip(" .,;:" + QUOTES)), tail


def _expand_pages(pages: str) -> str:
    """'357-62' -> '357–362'. A range that was shortened in the text is written out in full."""
    match = re.match(r"^([A-Za-z]?)(\d+)\s*[–—\-]\s*([A-Za-z]?)(\d+)$", pages.strip())
    if not match:
        return _squash(pages)
    lead, start, lead2, end = match.groups()
    if len(end) < len(start):
        end = start[: len(start) - len(end)] + end
    return f"{lead}{start}–{lead2}{end}"


def _locators(tail: str) -> dict[str, str]:
    """Volume, issue and pages from the text after the journal name."""
    text = tail.strip(" .,;:")
    out: dict[str, str] = {}
    volume = re.search(r"\bvol(?:ume)?\.?\s*(\d+)", text, re.I)
    issue = re.search(r"\bno\.?\s*([\w-]+)", text, re.I)
    pages = re.search(rf"\bpp?\.?\s*({PAGES})", text, re.I)
    if volume or issue or pages:  # MLA and IEEE: 'vol. 6, no. 60, pp. 1-9'
        found = {"volume": volume, "issue": issue, "pages": pages}
        out = {k: m.group(1) for k, m in found.items() if m}
        # Harvard: '6(60), p. 3021' has a bare volume and issue before the page marker.
        lead = re.match(r"^(?P<v>\d+)\s*(?:\((?P<i>[^)]+)\))?\s*,", text)
        if lead and "volume" not in out:
            out["volume"] = lead.group("v")
            if lead.group("i") and "issue" not in out:
                out["issue"] = lead.group("i")
    else:
        for pattern in (
            rf"^(?P<v>\d+)\s*(?:\((?P<i>[^)]+)\))?\s*[,:]\s*(?P<p>{PAGES})\b",  # APA, Chicago
            rf";\s*(?P<v>\d+)\s*(?:\((?P<i>[^)]+)\))?\s*:\s*(?P<p>{PAGES})",  # Vancouver, AMA
            rf"^(?P<v>)(?P<i>)\s*,?\s*(?P<p>{PAGES})$",  # pages only (conference papers)
            r"^(?P<v>\d+)\s*(?:\((?P<i>[^)]+)\))?$",  # volume and issue, no pages
        ):
            match = re.search(pattern, text)
            if match:
                out = {
                    "volume": match.group("v") or "",
                    "issue": match.group("i") or "",
                    "pages": match.groupdict().get("p") or "",
                }
                break
    if "pages" in out:
        out["pages"] = _expand_pages(out["pages"])
    return {k: v for k, v in out.items() if v}


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
    if match:
        return _squash(match.group(1)).rstrip("."), match.group(2)
    return (_squash(text).rstrip("."), "") if text.strip(" .") else None  # a lone sentence


def _initials_first_authors(text: str) -> list[str] | None:
    """IEEE: 'W. McKinney, J. P. A. Ioannidis, and K. Smith' -> ['McKinney, W.', ...]."""
    names = []
    for part in re.split(r",\s*(?:and\s+)?|\s+and\s+", text.strip().rstrip(".")):
        part = part.strip()
        if not part or "et al" in part:
            continue
        match = re.match(rf"^({INITIALS})(.+)$", part)
        if not match:
            return None
        names.append(f"{_squash(match.group(2))}, {_squash(match.group(1))}")
    return names or None


def _set_container(fields: dict[str, Any], journal: str) -> None:
    if journal:
        fields["journal"] = journal
        if CONFERENCE.match(journal):
            fields["type"] = "paper-conference"


def read_entry(raw: str) -> dict[str, Any]:
    """Fields read from one reference (only those found).

    doi, authors, year, title, journal, and when present volume, issue, pages and type.
    """
    fields: dict[str, Any] = {}
    doi = _find_doi(raw)
    if doi:
        fields["doi"] = doi
    body = _strip_links(raw)
    style = "not recognised"

    apa = re.match(rf"^(?P<a>.+?)\s*\((?P<y>{YEAR})\)\s*[.,]?\s*(?P<rest>.+)$", body)
    ieee = re.match(r"^(?P<a>.+?),\s+(?P<rest>[\"“‘].+)$", body)
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
        found = _quoted_title(apa["rest"]) or _sentence_title(apa["rest"])
        if found:
            fields["title"], remainder = found
            journal, tail = _split_journal(remainder)
            _set_container(fields, journal)
            fields.update(_locators(tail))
        names = _apa_authors(authors) or _generic_authors(authors)
        if names:
            fields["authors"] = names
    elif ieee and _initials_first_authors(ieee["a"]) and _quoted_title(ieee["rest"]):
        style = "IEEE"
        fields["authors"] = _initials_first_authors(ieee["a"])
        title, remainder = _quoted_title(ieee["rest"]) or ("", "")
        fields["title"] = title
        years = YEAR_ANYWHERE.findall(remainder)
        if years:
            fields["year"] = years[-1]
        conference = re.match(rf"in\s+(?P<j>.+?),\s*(?:[A-Z][a-z]{{2,3}}\.?\s*)?{YEAR}", remainder)
        if conference:
            _set_container(fields, _squash(conference["j"]))
            fields["type"] = "paper-conference"
            fields.update(_locators(remainder[conference.end() :]))
        else:
            journal, tail = _split_journal(remainder)
            _set_container(fields, journal)
            fields.update(_locators(tail))
    elif chicago and _quoted_title(chicago["rest"]):
        style = "Chicago author-date"
        fields["year"] = chicago["y"]
        title, remainder = _quoted_title(chicago["rest"]) or ("", "")
        fields["title"] = title
        journal, tail = _split_journal(remainder, volume_follows_name=True)
        _set_container(fields, journal)
        fields.update(_locators(tail))
        names = _generic_authors(chicago["a"]) or _first_inverted_authors(chicago["a"])
        if names:
            fields["authors"] = names
    elif mla and _quoted_title(mla["rest"]):
        style = "MLA"
        title, remainder = _quoted_title(mla["rest"]) or ("", "")
        fields["title"] = title
        journal, tail = _split_journal(remainder)
        _set_container(fields, journal)
        fields.update(_locators(tail))
        years = YEAR_ANYWHERE.findall(remainder)
        if years:
            fields["year"] = years[0]
        names = _generic_authors(mla["a"]) or _first_inverted_authors(mla["a"])
        if names:
            fields["authors"] = names
    elif vancouver:
        style = "Vancouver or AMA"
        fields["authors"] = _vancouver_authors(vancouver["a"])
        fields["title"] = _squash(vancouver["t"]).rstrip(".")
        _set_container(fields, _squash(vancouver["j"]))
        fields["year"] = vancouver["y"]
        fields.update(_locators(body[vancouver.end("y") :]))
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
