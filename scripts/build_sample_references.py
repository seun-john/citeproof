"""Write the demo's example reference lists from docs/data/sample-catalogue.json.

    python scripts/build_sample_references.py

Needs no network. The "good" list copies catalogue records with no mistakes. The "messy" list
copies some records and then adds one deliberate, labelled defect to each, plus references that
are not in the catalogue at all. tests/test_demo_logic.py pins the verdict each entry should get.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"


def bibtex(key: str, fields: dict[str, str], style: str = "braces") -> str:
    """One BibTeX entry. `style` varies delimiters so the list looks like real exports."""
    lines = []
    for name, value in fields.items():
        if style == "quotes" and name != "year":
            lines.append(f'  {name} = "{value}",')
        elif name == "year" and style == "quotes":
            lines.append(f"  {name} = {value},")
        else:
            lines.append(f"  {name} = {{{value}}},")
    return f"@article{{{key},\n" + "\n".join(lines) + "\n}\n"


def authors(record: dict, order: list[int] | None = None) -> str:
    names = record["authors"]
    if order is not None:
        names = [names[i] for i in order]
    return " and ".join(names)


def fields(record: dict, **changes: str | None) -> dict[str, str]:
    base = {
        "author": authors(record),
        "title": record["title"],
        "journal": record["journal"],
        "year": record["year"],
        "doi": record["doi"],
    }
    base.update({k: v for k, v in changes.items() if v is not None})
    return {k: v for k, v in base.items() if k not in changes or changes[k] is not None}


def main() -> int:
    catalogue = json.loads((DATA / "sample-catalogue.json").read_text(encoding="utf-8"))
    by_key = {
        "numpy": catalogue[0],
        "scipy": catalogue[1],
        "pandas": catalogue[2],
        "seaborn": catalogue[3],
        "skimage": catalogue[4],
        "hwang2004": catalogue[5],
        "hwang2005": catalogue[6],
    }

    good = "% A reference list where every entry matches a record in the sample catalogue.\n\n"
    good += bibtex("harris2020", fields(by_key["numpy"]))
    good += bibtex(
        "virtanen2020",
        fields(by_key["scipy"], doi="https://doi.org/" + by_key["scipy"]["doi"]),
        "quotes",
    )
    good += bibtex("mckinney2010", fields(by_key["pandas"], doi=by_key["pandas"]["doi"].upper()))
    good += bibtex(
        "waskom2021", fields(by_key["seaborn"], doi="doi:" + by_key["seaborn"]["doi"]), "quotes"
    )
    good += bibtex("vanderwalt2014", fields(by_key["skimage"]))
    (DATA / "sample-references-good.bib").write_text(good, encoding="utf-8")

    seaborn_title = by_key["seaborn"]["title"].replace("visualization", "visualisation")
    skimage_order = [1, 0, *range(2, len(by_key["skimage"]["authors"]))]
    messy = (
        "% A deliberately messy list. Each entry is labelled with what is wrong with it.\n"
        "% Entries marked 'real but absent' are real papers this small catalogue does not hold.\n"
        "% The entry marked 'invented' does not exist; it was written for this demo.\n\n"
    )
    messy += "% matches the catalogue, odd formatting\n"
    messy += bibtex(
        "mckinney2010",
        fields(by_key["pandas"], doi="https://doi.org/" + by_key["pandas"]["doi"].upper()),
        "quotes",
    )
    messy += "% matches the catalogue, doi: prefix\n"
    messy += bibtex("harris2020", fields(by_key["numpy"], doi="doi:" + by_key["numpy"]["doi"]))
    messy += "% title spelled differently (visualisation)\n"
    messy += bibtex("waskom2021", fields(by_key["seaborn"], title=seaborn_title))
    messy += "% first two authors swapped\n"
    messy += bibtex(
        "vanderwalt2014",
        {**fields(by_key["skimage"]), "author": authors(by_key["skimage"], skimage_order)},
    )
    messy += "% wrong year\n"
    messy += bibtex("virtanen2020", fields(by_key["scipy"], year="2019"))
    messy += "% matches the catalogue, which flags this work as retracted\n"
    messy += bibtex("hwang2005", fields(by_key["hwang2005"]))
    messy += "% real but absent: a genuine paper that this small catalogue does not hold\n"
    messy += bibtex(
        "wilkinson2016",
        {
            "author": "Wilkinson, Mark D. and others",
            "title": "The FAIR Guiding Principles for scientific data management and stewardship",
            "journal": "Scientific Data",
            "year": "2016",
            "doi": "10.1038/sdata.2016.18",
        },
    )
    messy += "% real but no DOI given\n"
    messy += bibtex(
        "pedregosa2011",
        {
            "author": "Pedregosa, Fabian and others",
            "title": "Scikit-learn: Machine Learning in Python",
            "journal": "Journal of Machine Learning Research",
            "year": "2011",
        },
    )
    messy += "% invented for this demo: this DOI and paper do not exist\n"
    messy += bibtex(
        "invented2026",
        {
            "author": "Example, Alex",
            "title": "An Invented Reference Written For The CiteProof Demo",
            "journal": "Journal of Examples",
            "year": "2026",
            "doi": "10.9999/demo.invented-001",
        },
    )
    messy += "% same paper as the first entry, listed again\n"
    messy += bibtex("mckinney2010b", fields(by_key["pandas"]))
    (DATA / "sample-references-messy.bib").write_text(messy, encoding="utf-8")

    example_json = {
        "references": [
            {
                "id": "r1",
                "doi": by_key["numpy"]["doi"],
                "title": by_key["numpy"]["title"],
                "authors": by_key["numpy"]["authors"],
                "year": by_key["numpy"]["year"],
                "journal": by_key["numpy"]["journal"],
            },
            {
                "id": "r2",
                "doi": by_key["seaborn"]["doi"],
                "title": by_key["seaborn"]["title"],
                "authors": by_key["seaborn"]["authors"],
                "year": by_key["seaborn"]["year"],
                "journal": by_key["seaborn"]["journal"],
            },
            {
                "id": "r3",
                "doi": "10.9999/demo.invented-002",
                "title": "Another Invented Reference Written For The CiteProof Demo",
                "authors": ["Example, Alex"],
                "year": 2026,
                "journal": "Journal of Examples",
            },
        ],
        "citations": ["r1", "r3", "r9"],
    }
    text = json.dumps(example_json, indent=2, ensure_ascii=False) + "\n"
    (DATA / "sample-references.json").write_text(text, encoding="utf-8")
    print("Wrote 3 example files to docs/data/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
