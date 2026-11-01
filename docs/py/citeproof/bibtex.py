"""A small BibTeX reader that produces CiteProof reference records.

It handles the common case: `@article{key, field = {value}, field = "value", year = 2020}`.
It does not expand @string macros or cross-references, and it ignores @comment and @preamble.
"""

from __future__ import annotations

import re
from typing import Any

from .core import InputError

ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.S)
SKIP = {"comment", "preamble", "string"}


def _balanced(text: str, start: int) -> int:
    """Index just after the brace that closes the one opened at `start`."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise InputError("Unbalanced braces in BibTeX input")


def _fields(body: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pos = 0
    key = re.compile(r"\s*,?\s*([A-Za-z][\w-]*)\s*=\s*", re.S)
    while True:
        m = key.match(body, pos)
        if not m:
            break
        name, i = m.group(1).lower(), m.end()
        if i >= len(body):
            break
        if body[i] == "{":
            end = _balanced(body, i)
            value = body[i + 1 : end - 1]
        elif body[i] == '"':
            end = body.index('"', i + 1) + 1
            value = body[i + 1 : end - 1]
        else:
            m2 = re.compile(r"[^,}]+").match(body, i)
            if not m2:
                break
            end, value = m2.end(), m2.group().strip()
        fields[name] = re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()
        pos = end
    return fields


def parse_bibtex(text: str) -> list[dict[str, Any]]:
    """Return reference records: id, title, authors, year, journal, doi (when present)."""
    refs: list[dict[str, Any]] = []
    for m in ENTRY.finditer(text):
        if m.group(1).lower() in SKIP:
            continue
        open_at = text.index("{", m.start())
        end = _balanced(text, open_at)
        fields = _fields(text[m.end() : end - 1])
        ref: dict[str, Any] = {"id": m.group(2)}
        if "title" in fields:
            ref["title"] = fields["title"]
        if "author" in fields:
            ref["authors"] = [
                a.strip() for a in re.split(r"\s+and\s+", fields["author"]) if a.strip()
            ]
        if "year" in fields:
            ref["year"] = fields["year"]
        journal = fields.get("journal") or fields.get("booktitle")
        if journal:
            ref["journal"] = journal
        if "doi" in fields:
            ref["doi"] = fields["doi"]
        refs.append(ref)
    return refs
