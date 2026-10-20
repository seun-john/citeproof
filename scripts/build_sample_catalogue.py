"""Rebuild docs/data/sample-catalogue.json from the public sources it was made from.

Run it with network access:  python scripts/build_sample_catalogue.py

Every bibliographic field in the output is read from a file you can open yourself, and every
source file is pinned by SHA-256 so a change upstream stops the build instead of slipping in.

Ordinary records come from the citation files that open-source projects publish for their own
papers (NumPy, SciPy, pandas, seaborn, scikit-image). Retracted records come from the Retraction
Watch dataset that Crossref publishes on GitLab. A record is only marked `"retracted": false`
when its DOI is absent from that dataset, and the provenance string says exactly that.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path
from typing import Any

from citeproof.bibtex import parse_bibtex

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "sample-catalogue.json"
RETRIEVED = "2026-10-20"

RW_URL = "https://gitlab.com/crossref/retraction-watch-data/-/raw/main/retraction_watch.csv"
RW_COMMIT = "a503965fbfbc1175f810e505a3dbdc1c2561969c"
RW_DATE = "2026-10-19"

RAW = "https://raw.githubusercontent.com"
SOURCES = {
    "numpy": f"{RAW}/numpy/numpy/main/CITATION.bib",
    "scipy": f"{RAW}/scipy/scipy/main/CITATION.bib",
    "pandas": f"{RAW}/pandas-dev/pandas/main/CITATION.cff",
    "seaborn": f"{RAW}/mwaskom/seaborn/master/CITATION.cff",
    "skimage": f"{RAW}/scikit-image/scikit-image/main/CITATION.cff",
}
PINNED_SHA256 = {
    "numpy": "6b12115280759df0c423d639828d2b95bb3837373f65136fcc5086cc5560d528",
    "scipy": "00dae00c94b68345b59086ccff7183d7133f9b64e3045b0cced61daca7f67af4",
    "pandas": "a2e4df597d51899a88cbbc006776479704e0503040f46d77120ed010f6ccd603",
    "seaborn": "2db5e11d975aac2c608eededf7b98d012ce145378aa2aaf8665e36d84fc8cebc",
    "skimage": "2222251b11c833b797451ccdc678f93a2bb0fa2fdbb52565b07d202b7528062a",
}

# Fields for the .cff sources are written out here, and each value is checked to appear
# verbatim in the downloaded file before it is used.
CFF_RECORDS: dict[str, dict[str, Any]] = {
    "pandas": {
        "doi": "10.25080/Majora-92bf1922-00a",
        "title": "Data Structures for Statistical Computing in Python",
        "authors": ["McKinney, Wes"],
        "year": "2010",
        "journal": "Proceedings of the 9th Python in Science Conference",
        "checks": [
            "Data Structures for Statistical Computing in Python",
            "family-names: McKinney",
            "given-names: Wes",
            "year: 2010",
            "doi: 10.25080/Majora-92bf1922-00a",
            "collection-title: Proceedings of the 9th Python in Science Conference",
            "license: CC-BY-3.0",
        ],
    },
    "seaborn": {
        "doi": "10.21105/joss.03021",
        "title": "seaborn: statistical data visualization",
        "authors": ["Waskom, Michael Lawrence"],
        "year": "2021",
        "journal": "Journal of Open Source Software",
        "checks": [
            'title: "seaborn: statistical data visualization"',
            'family-names: "Waskom"',
            'given-names: "Michael Lawrence"',
            "year: 2021",
            'doi: "10.21105/joss.03021"',
            'journal: "Journal of Open Source Software"',
        ],
    },
    "skimage": {
        "doi": "10.7717/peerj.453",
        "title": "scikit-image: image processing in Python",
        "authors": [
            "van der Walt, Stéfan J.",
            "Schönberger, Johannes L.",
            "Nunez-Iglesias, Juan",
            "Boulogne, François",
            "Warner, Joshua D.",
            "Yager, Neil",
            "Gouillart, Emmanuelle",
            "Yu, Tony",
            "the scikit-image contributors",
        ],
        "year": "2014",
        "journal": "PeerJ",
        "checks": [
            'title: "scikit-image: image processing in Python"',
            "family-names: van der Walt",
            "given-names: Stéfan J.",
            "family-names: Schönberger",
            "given-names: Johannes L.",
            "family-names: Nunez-Iglesias",
            "given-names: Juan",
            "family-names: Boulogne",
            "given-names: François",
            "family-names: Warner",
            "given-names: Joshua D.",
            "family-names: Yager",
            "given-names: Neil",
            "family-names: Gouillart",
            "given-names: Emmanuelle",
            "family-names: Yu",
            "given-names: Tony",
            "family-names: the scikit-image contributors",
            "journal: PeerJ",
            "year: 2014",
            "doi: 10.7717/peerj.453",
        ],
    },
}

RETRACTED_DOIS = ["10.1126/science.1094515", "10.1126/science.1112286"]
ACCENTS = {"'": "\u0301", "`": "\u0300", "^": "\u0302", '"': "\u0308", "~": "\u0303", ".": "\u0307"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def unlatex(text: str) -> str:
    """Turn the few LaTeX accent macros these sources use into Unicode."""
    text = re.sub(r"\\([\'`^\".~])\s*([A-Za-z])", lambda m: m.group(2) + ACCENTS[m.group(1)], text)
    return unicodedata.normalize("NFC", text.replace("\\&", "&"))


def year_of(rw_date: str) -> str:
    match = re.search(r"\b(\d{4})\b", rw_date)
    if not match:
        raise SystemExit(f"No year in Retraction Watch date: {rw_date!r}")
    return match.group(1)


def provenance_source(name: str, url: str, digest: str) -> str:
    return f"bibliographic fields from {url} (sha256 {digest[:16]}, retrieved {RETRIEVED})"


def main() -> int:
    texts: dict[str, str] = {}
    digests: dict[str, str] = {}
    for name, url in SOURCES.items():
        data = fetch(url)
        digests[name] = hashlib.sha256(data).hexdigest()
        pinned = PINNED_SHA256.get(name)
        if pinned and pinned != digests[name]:
            raise SystemExit(f"{url} changed (sha256 {digests[name]}); review it, then re-pin.")
        texts[name] = data.decode("utf-8")

    print("Downloading the Retraction Watch dataset (about 65 MB)...", file=sys.stderr)
    rw_raw = fetch(RW_URL).decode("utf-8", errors="replace")
    csv.field_size_limit(sys.maxsize)
    rw_rows = list(csv.DictReader(rw_raw.splitlines(), skipinitialspace=False))
    listed: dict[str, list[dict[str, str]]] = {}
    for row in rw_rows:
        listed.setdefault(row["OriginalPaperDOI"].strip().lower(), []).append(row)

    no_rw = (
        f"not listed in the Retraction Watch dataset published by Crossref "
        f"({RW_URL.split('/-/')[0]}, commit {RW_COMMIT[:7]}, {RW_DATE})"
    )
    records: list[dict[str, Any]] = []

    # NumPy and SciPy: parsed with CiteProof's own BibTeX reader.
    for name in ("numpy", "scipy"):
        (entry,) = parse_bibtex(texts[name])
        records.append(
            {
                "doi": entry["doi"],
                "title": unlatex(entry["title"]),
                "authors": [unlatex(a) for a in entry["authors"]],
                "year": entry["year"],
                "journal": entry["journal"],
                "_source": name,
            }
        )

    for name, spec in CFF_RECORDS.items():
        for needle in spec["checks"]:
            if needle not in texts[name]:
                raise SystemExit(f"{name}: expected text not in source: {needle!r}")
        records.append({**{k: v for k, v in spec.items() if k != "checks"}, "_source": name})

    out: list[dict[str, Any]] = []
    for rec in records:
        name = rec.pop("_source")
        key = rec["doi"].strip().lower()
        if key in listed:
            raise SystemExit(f"{rec['doi']} is listed in Retraction Watch; review before use.")
        out.append(
            {
                **rec,
                "retracted": False,
                "provenance": (
                    f"{provenance_source(name, SOURCES[name], digests[name])}; "
                    f"retraction status: DOI {no_rw}"
                ),
            }
        )

    for doi in RETRACTED_DOIS:
        rows = [r for r in listed.get(doi.lower(), []) if r["RetractionNature"] == "Retraction"]
        if len(rows) != 1:
            raise SystemExit(f"Expected exactly one Retraction row for {doi}, got {len(rows)}")
        row = rows[0]
        out.append(
            {
                "doi": row["OriginalPaperDOI"].strip(),
                "title": row["Title"].strip(),
                "authors": [a.strip() for a in row["Author"].split(";") if a.strip()],
                "year": year_of(row["OriginalPaperDate"]),
                "journal": row["Journal"].strip(),
                "retracted": True,
                "provenance": (
                    f"Retraction Watch dataset published by Crossref "
                    f"({RW_URL.split('/-/')[0]}, commit {RW_COMMIT[:7]}, {RW_DATE}), "
                    f"record {row['Record ID']}: RetractionNature=Retraction, "
                    f"RetractionDate={row['RetractionDate'].split()[0]}"
                ),
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} records to {OUT.relative_to(ROOT)}", file=sys.stderr)
    for name, digest in digests.items():
        print(f'    "{name}": "{digest}",', file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
