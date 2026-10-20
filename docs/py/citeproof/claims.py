"""Attach source passages to claims and flag what a person must check.

Nothing here decides whether a source supports a claim. Similar wording or matching numbers
never prove support, so every claim that has usable evidence is routed to human review.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .core import InputError, finding, report, require

NUMBER = re.compile(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?\s?%?")


def normalise_number(raw: str) -> str:
    """12.50%, 12.5 % and 12.5% are the same number; so are 1,000 and 1000."""
    text = raw.replace(",", "").replace(" ", "")
    percent = text.endswith("%")
    try:
        value = float(text.rstrip("%"))
    except ValueError:
        return raw.strip()
    return f"{value:g}" + ("%" if percent else "")


def numbers(text: str) -> Counter[str]:
    return Counter(normalise_number(m.group()) for m in NUMBER.finditer(text))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def claimtrace(data: dict[str, Any]) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for claim in require(data, "claims", list):
        text = require(claim, "text", str)
        source = claim.get("source")
        if not source:
            out.append(finding("NO_CITATION", "No source was supplied for this claim.", claim=text))
            continue
        if not isinstance(source, dict):
            raise InputError("A claim's 'source' must be an object")
        passage = source.get("passage")
        if not passage:
            out.append(finding("SOURCE_UNAVAILABLE", "No source passage was supplied.", claim=text))
            continue
        if source.get("kind", "full_text") != "full_text":
            out.append(
                finding(
                    "HUMAN_REVIEW_REQUIRED",
                    "A title, abstract or snippet cannot establish support.",
                    claim=text,
                )
            )
            continue
        exact = _squash(text) in _squash(passage)
        missing = sorted((numbers(text) - numbers(passage)).elements())
        if exact:
            message = "The claim's exact wording is in the passage; check attribution and context."
        elif missing:
            message = (
                "Numbers in the claim do not appear in the passage; "
                "possible overstatement. Review required."
            )
        else:
            message = "A source passage is attached; whether it supports the claim needs a person."
        out.append(
            finding(
                "HUMAN_REVIEW_REQUIRED",
                message,
                claim=text,
                source=source.get("id"),
                page=source.get("page"),
                passage=passage,
                exact_text=exact,
                numbers_missing_from_passage=missing,
            )
        )
    return report("ClaimTrace", out, scope="evidence routing only; support is never decided")
