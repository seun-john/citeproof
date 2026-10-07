"""Command line for CiteProof."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .bibtex import parse_bibtex
from .claims import claimtrace
from .core import InputError, finding, report
from .references import citeproof
from .runner import Command, main_wrapper, run


def _check(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return citeproof(data)


def _claims(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    return claimtrace(data)


def _from_bibtex(args: argparse.Namespace, data: Any) -> dict[str, Any]:
    path = Path(args.bib)
    if not path.is_file():
        raise InputError(f"Not a file: {args.bib}")
    refs = parse_bibtex(path.read_text(encoding="utf-8"))
    target = Path(args.input_out)
    if target.resolve() == path.resolve():
        raise InputError("--input-out must not overwrite the .bib file")
    skeleton = {
        "references": refs,
        "catalogue": [],
        "citations": [r["id"] for r in refs],
    }
    target.write_text(json.dumps(skeleton, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report(
        "CiteProof",
        [
            finding(
                "CONVERTED",
                "References read from BibTeX. Fill in catalogue and citations, then run check.",
                references=len(refs),
                written=str(target),
            )
        ],
    )


COMMANDS = {
    "check": Command(_check, "Compare references with a catalogue", frozenset({"VERIFIED"})),
    "claims": Command(_claims, "Route claims and their source passages to human review"),
    "from-bibtex": Command(
        _from_bibtex,
        "Convert a .bib file into check input",
        frozenset({"CONVERTED"}),
        takes_input=False,
        options=[
            (("bib",), {"help": "BibTeX file"}),
            (("--input-out",), {"required": True, "help": "where to write the check input JSON"}),
        ],
        protect=("bib",),
    ),
}


def main(argv: list[str] | None = None) -> int:
    return run("citeproof", "Audit references and the claims they support.", COMMANDS, argv)


if __name__ == "__main__":
    main_wrapper(main)
