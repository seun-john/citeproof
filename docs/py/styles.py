"""Reformat references into a chosen citation style.

The formatting itself is done by a standard citation-style engine (citeproc-py) running the
official Citation Style Language style files, not by rules written for this project. This module
only prepares the data and tidies the output:

  * build_item() turns what was read from a reference (and, when its DOI matches, the catalogue
    record) into the engine's input, and says plainly what was missing or filled in;
  * render() runs the engine and returns the formatted references as text and as plain
    italic/bold segments, so the page never has to insert HTML.

It reads and writes nothing outside the style files in docs/csl/.
"""

from __future__ import annotations

import re
import warnings
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# id -> (label shown to the person, file, locale).
STYLES = {
    "apa": ("APA 7th edition", "apa.csl", "en-US"),
    "mla": ("MLA 9th edition", "modern-language-association.csl", "en-US"),
    "chicago-author-date": (
        "Chicago 18th edition (author-date)",
        "chicago-author-date.csl",
        "en-US",
    ),
    "harvard": ("Harvard (Cite Them Right 12th edition)", "harvard-cite-them-right.csl", "en-GB"),
    "ieee": ("IEEE", "ieee.csl", "en-US"),
    "ama": ("AMA 11th edition", "american-medical-association.csl", "en-US"),
}

PARTICLES = {
    "van", "von", "der", "den", "de", "del", "della", "di", "da", "du", "la", "le", "bin", "ibn",
    "al", "el", "ten", "ter", "zu", "zur", "dos", "das",
}  # fmt: skip
TRUNCATION = re.compile(r"\bet al\b|…|\.\.\.", re.I)
FILL_LABELS = {
    "title": "title",
    "journal": "journal or conference name",
    "year": "year",
    "volume": "volume",
    "issue": "issue",
    "pages": "page numbers",
}


def csl_dir() -> Path:
    here = Path(__file__).resolve().parent
    for candidate in (here / "csl", here.parent / "csl"):
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("The citation style files (docs/csl) were not found.")


# --------------------------------------------------------------------------- names


def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"\s*(?:;|\band\b|&)\s*", value)
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def _surname(name: str) -> str:
    text = name.strip()
    if "," in text:
        return text.split(",", 1)[0].strip().casefold()
    tokens = text.split()
    if len(tokens) >= 2 and re.fullmatch(r"[A-Z]{1,3}", tokens[-1]):  # 'Harris CR'
        return " ".join(tokens[:-1]).casefold()
    return tokens[-1].casefold() if tokens else ""


def _initials_only(name: str) -> bool:
    given = name.split(",", 1)[1].strip() if "," in name else ""
    return bool(given) and all(
        re.fullmatch(r"[^\W\d_]\.?", t) for t in re.split(r"[\s.-]+", given) if t
    )


def csl_name(name: str) -> dict[str, str]:
    """'McKinney, W.', 'Harris CR' and 'Stéfan van der Walt' as CSL names."""
    text = name.strip()
    if "," in text:
        family, given = (part.strip() for part in text.split(",", 1))
        return {"family": family, "given": given}
    tokens = text.split()
    if len(tokens) == 1:
        return {"literal": text}
    if len(tokens) >= 2 and re.fullmatch(r"[A-Z]{1,3}", tokens[-1]):  # Vancouver: 'Harris CR'
        return {"family": " ".join(tokens[:-1]), "given": " ".join(f"{c}." for c in tokens[-1])}
    cut = len(tokens) - 1
    while cut > 1 and tokens[cut - 1].lower() in PARTICLES:
        cut -= 1
    return {"family": " ".join(tokens[cut:]), "given": " ".join(tokens[:cut])}


# --------------------------------------------------------------------------- input to the engine


def build_item(
    ref: dict[str, Any], record: dict[str, Any] | None = None, raw: str = ""
) -> tuple[dict[str, Any] | None, list[str], str]:
    """Return (CSL item or None, notes for the person, reason it was skipped).

    `ref` is what was read from the person's own reference. `record` is the catalogue record with
    the same DOI, if any: it only fills gaps and completes author names, and every such use is
    listed in the notes.
    """
    notes: list[str] = []
    data = {k: ref.get(k) for k in ("title", "year", "journal", "volume", "issue", "pages", "type")}
    authors = [a for a in _as_list(ref.get("authors")) if a.casefold() not in {"others", "et al."}]
    truncated = bool(TRUNCATION.search(raw)) or len(authors) != len(_as_list(ref.get("authors")))
    if record:
        filled = []
        for key in ("title", "journal", "year", "volume", "issue", "pages", "type"):
            if not data.get(key) and record.get(key):
                data[key] = record[key]
                if key in FILL_LABELS:
                    filled.append(FILL_LABELS[key])
        if filled:
            notes.append(
                f"Filled from the catalogue record with the same DOI: {', '.join(filled)}."
            )
        theirs = _as_list(record.get("authors"))
        mine_surnames, their_surnames = (
            [_surname(a) for a in authors],
            [_surname(a) for a in theirs],
        )
        abbreviated = (
            len(authors) == len(theirs)
            and mine_surnames == their_surnames
            and any(_initials_only(a) or re.fullmatch(r".+\s[A-Z]{1,3}", a) for a in authors)
        )
        if theirs and (not authors or truncated or abbreviated):
            authors = theirs
            truncated = False
            notes.append("Author names taken in full from the catalogue record with the same DOI.")
    kind = str(data.get("type") or "article-journal")
    if kind.startswith("other:"):
        return (
            None,
            notes,
            f"this looks like a {kind[6:].replace('-', ' ')}, which is not formatted yet",
        )
    missing = [
        label
        for label, value in (
            ("title", data["title"]),
            ("authors", authors),
            ("year", data["year"]),
            ("journal or conference name", data["journal"]),
        )
        if not value
    ]
    if missing:
        return None, notes, f"missing {', '.join(missing)}, so it cannot be formatted reliably"
    if kind == "article-journal" and not (
        data.get("volume") or data.get("issue") or data.get("pages")
    ):
        return (
            None,
            notes,
            "no volume, issue or page numbers were found, so it may be a book, report or web "
            "page, which this tool does not format",
        )
    if truncated:
        notes.append(
            "Your text shortened the author list (“et al.” or …), so only the "
            "authors you listed are formatted. Add the full list."
        )
    if kind == "article-journal" and not data.get("volume"):
        notes.append("No volume was found.")
    if not data.get("pages"):
        notes.append("No page numbers were found.")
    if not ref.get("doi") and not (record and record.get("doi")):
        notes.append("No DOI was found.")
    year = re.search(r"\d{4}", str(data["year"]))
    item: dict[str, Any] = {
        "type": kind if kind in {"article-journal", "paper-conference"} else "article-journal",
        "title": str(data["title"]),
        "author": [csl_name(a) for a in authors],
        "issued": {"date-parts": [[int(year.group())]]} if year else {},
        "container-title": str(data["journal"]),
    }
    for csl_key, key in (("volume", "volume"), ("issue", "issue"), ("page", "pages")):
        if data.get(key):
            item[csl_key] = str(data[key])
    doi = ref.get("doi") or (record or {}).get("doi")
    if doi:
        item["DOI"] = str(doi)
    return item, notes, ""


# --------------------------------------------------------------------------- output


class _Segments(HTMLParser):
    """Turn the engine's small HTML (<i>, <b>) into [{text, italic, bold}] segments."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.segments: list[dict[str, Any]] = []
        self._italic = self._bold = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        self._italic += tag in {"i", "em"}
        self._bold += tag in {"b", "strong"}

    def handle_endtag(self, tag: str) -> None:
        self._italic -= tag in {"i", "em"} and self._italic > 0
        self._bold -= tag in {"b", "strong"} and self._bold > 0

    def handle_data(self, data: str) -> None:
        italic, bold = self._italic > 0, self._bold > 0
        if (
            self.segments
            and self.segments[-1]["italic"] == italic
            and self.segments[-1]["bold"] == bold
        ):
            self.segments[-1]["text"] += data
        else:
            self.segments.append({"text": data, "italic": italic, "bold": bold})


def _tidy(html_text: str, locale: str) -> str:
    text = re.sub(r"^(\[\d+\]|\d+\.)(?=\S)", r"\1 ", html_text.strip())  # '[1]W.' -> '[1] W.'
    if locale == "en-US":  # US style puts commas and full stops inside closing quotes
        text = re.sub(r"”([,.])", r"\1”", text)
    return text


_ENGINE_PATCHED = False


def _honour_initialize_false() -> None:
    """Apply the CSL rule `initialize="false"`, which the engine ignores.

    The MLA style asks for given names to stay in full. Per the CSL specification, with
    initialize="false" only given names that are already initials receive the initialize-with
    mark. This wraps the engine's method at run time; the vendored files are not edited.
    """
    global _ENGINE_PATCHED
    if _ENGINE_PATCHED:
        return
    from citeproc import model

    original = model.Name.initialize

    def initialize(self: Any, given: str, mark: str, context: Any) -> str:
        if self.get("initialize") == "false":
            tokens = [t for t in re.split(r"[\s.-]+", given) if t]
            if not all(len(t) == 1 and t.isupper() for t in tokens):
                return given
        return original(self, given, mark, context)

    model.Name.initialize = initialize
    _ENGINE_PATCHED = True


def render(items: list[dict[str, Any]], style_id: str) -> list[dict[str, Any]]:
    """Format CSL items (each with a unique "id"). Returns entries in the style's own order."""
    from citeproc import Citation, CitationItem, CitationStylesBibliography, CitationStylesStyle
    from citeproc.formatter import html
    from citeproc.source.json import CiteProcJSON

    _label, filename, locale = STYLES[style_id]
    _honour_initialize_false()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        style = CitationStylesStyle(str(csl_dir() / filename), locale=locale, validate=False)
        bibliography = CitationStylesBibliography(style, CiteProcJSON(items), html)
        for item in items:
            bibliography.register(Citation([CitationItem(item["id"])]))
        bibliography.sort()
        entries = [str(entry) for entry in bibliography.bibliography()]
        keys = list(bibliography.keys)
    out = []
    for key, entry in zip(keys, entries, strict=True):
        parser = _Segments()
        parser.feed(_tidy(entry, locale))
        parser.close()
        segments = [s for s in parser.segments if s["text"]]
        out.append({"id": key, "segments": segments, "text": "".join(s["text"] for s in segments)})
    return out
