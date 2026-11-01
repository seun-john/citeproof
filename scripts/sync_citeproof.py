"""Copy CiteProof's modules into docs/py/ so GitHub Pages can serve them to the browser.

The browser demo runs these exact files. They are copied byte for byte and never edited.

    python scripts/sync_citeproof.py          copy src/citeproof -> docs/py/citeproof
    python scripts/sync_citeproof.py --check  exit 1 if the copy differs from src/citeproof
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "citeproof"
DEST = ROOT / "docs" / "py" / "citeproof"

# The browser only needs the checking logic. The command-line plumbing (cli, runner, __main__)
# reads and writes files and is not used.
MODULES = ["__init__.py", "core.py", "references.py", "bibtex.py", "claims.py"]


def differences() -> list[str]:
    problems = []
    for name in MODULES:
        source, copy = SRC / name, DEST / name
        if not copy.is_file():
            problems.append(f"missing: {copy.relative_to(ROOT)}")
        elif source.read_bytes().replace(b"\r\n", b"\n") != copy.read_bytes().replace(
            b"\r\n", b"\n"
        ):
            problems.append(f"differs from src: {copy.relative_to(ROOT)}")
    extra = sorted(p.name for p in DEST.glob("*.py")) if DEST.is_dir() else []
    problems += [
        f"unexpected file: {DEST.relative_to(ROOT) / n}" for n in extra if n not in MODULES
    ]
    return problems


def main(argv: list[str]) -> int:
    if "--check" in argv:
        problems = differences()
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0
    DEST.mkdir(parents=True, exist_ok=True)
    for name in MODULES:
        shutil.copyfile(SRC / name, DEST / name)
    print(f"Copied {len(MODULES)} modules to {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
