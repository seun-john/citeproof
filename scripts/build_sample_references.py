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

    pandas, seaborn, skimage = by_key["pandas"], by_key["seaborn"], by_key["skimage"]
    text = "References\n"
    text += (
        f"McKinney, W. ({pandas['year']}). Data structures for statistical computing in Python. "
        f"{pandas['journal']}, 56\u201361. https://doi.org/{pandas['doi']}\n"
    )
    text += (
        "Harris, C. R., Millman, K. J., van der Walt, S. J., Gommers, R., \u2026 & Oliphant, T. E. "
        f"(2020). {by_key['numpy']['title']}. Nature, 585(7825), 357\u2013362.\n"
    )
    text += (
        f"Waskom, Michael L. \u201c{seaborn['title'].capitalize()}.\u201d {seaborn['journal']}, "
        "vol. 6, no. 60, 2021, p. 3021.\n"
    )
    text += (
        "Pedregosa F, Varoquaux G, Gramfort A, Michel V. Scikit-learn: machine learning in "
        "Python. J Mach Learn Res. 2011;12:2825-30.\n"
    )
    text += (
        "Wilkinson, M. D., Dumontier, M., Aalbersberg, I. J., et al. (2016). The FAIR Guiding "
        "Principles for scientific data management and stewardship. Scientific Data, 3, 160018. "
        "https://doi.org/10.1038/sdata.2016.18\n"
    )
    text += "my notes: still need to find the source for the 2019 survey figure\n"
    text += (
        "Van der Walt, S., Sch\u00f6nberger, J. L., Nunez-Iglesias, J., Boulogne, F., "
        "Warner, J. D., Yager, N., \u2026 & Yu, T. "
        f"({skimage['year']}). {skimage['title']}. {skimage['journal']}, "
        f"2, e453. https://doi.org/{skimage['doi']}\n"
    )
    (DATA / "sample-references-text.txt").write_text(text, encoding="utf-8")

    mixed = [
        "McKinney, Wes. 2010. \u201cData Structures for Statistical Computing in Python.\u201d "
        "Proceedings of the 9th Python in Science Conference, 56\u201361. "
        "https://doi.org/10.25080/Majora-92bf1922-00a",
        "Waskom, M.L. (2021) \u2018seaborn: statistical data visualization\u2019, Journal of Open "
        "Source Software, 6(60), p. 3021. https://doi.org/10.21105/joss.03021",
        "J. P. A. Ioannidis, \u201cWhy most published research findings are false,\u201d PLoS "
        "Medicine, vol. 2, no. 8, p. e124, Aug. 2005, doi: 10.1371/journal.pmed.0020124.",
        "Hunter, J. D. \u201cMatplotlib: A 2D Graphics Environment.\u201d Computing in Science & "
        "Engineering, vol. 9, no. 3, 2007, pp. 90\u201395. https://doi.org/10.1109/MCSE.2007.55",
        "Harris CR, Millman KJ, van der Walt SJ, et al. Array programming with NumPy. Nature. "
        "2020;585(7825):357-362. doi:10.1038/s41586-020-2649-2",
        "Pedregosa, F., Varoquaux, G., Gramfort, A., & Michel, V. (2011). Scikit-learn: Machine "
        "learning in Python. Journal of Machine Learning Research, 12, 2825\u20132830.",
    ]
    (DATA / "sample-references-mixed.txt").write_text("\n".join(mixed) + "\n", encoding="utf-8")

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
    print("Wrote 5 example files to docs/data/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
