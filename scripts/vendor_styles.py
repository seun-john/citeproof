"""Vendor the citation-style engine and the style files the "Reformat" feature uses.

    python scripts/vendor_styles.py          (needs network)

Writes docs/py/citeproc/ (the citeproc-py engine, BSD-2-Clause) and docs/csl/ (official Citation
Style Language files, CC BY-SA 3.0). Every download is checked against a pinned SHA-256, so a
change upstream stops the build instead of slipping in. The files are copied unmodified.

Note the spelling: `citeproc` is the third-party style engine; `citeproof` is this project.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = ROOT / "docs" / "py" / "citeproc"
CSL_DIR = ROOT / "docs" / "csl"
RETRIEVED = "2026-10-24"

ENGINE_VERSION = "0.11.1"
ENGINE_KEEP_LOCALES = {"locales-en-US.xml", "locales-en-GB.xml", "locales.json"}
ENGINE_SKIP = ("data/schema/", "data/styles/", "scripts/", "__pycache__/")

CSL_BASE = "https://raw.githubusercontent.com/citation-style-language/styles/master/"
# id -> (file, sha256 of the file as downloaded)
STYLES = {
    "apa": ("apa.csl", "3917def5fc951b104d64216c3373096042368b9704ba269ca83c14ebaba889fc"),
    "mla": (
        "modern-language-association.csl",
        "e1432698ef28938d044b06bd45ddcc57d6b974cec25f71007075646a11f99484",
    ),
    "chicago-author-date": (
        "chicago-author-date.csl",
        "002fade78d7e4fe9d42936a16b43a8066b097013f6255df40b1bfba6631eff9b",
    ),
    "harvard": (
        "harvard-cite-them-right.csl",
        "0ca3d2c7c881cd98cdd81098b5349f5921edf430498aa9a5a41918621cf7cc45",
    ),
    "ieee": ("ieee.csl", "b4c7619fc16c45a31e4cc3271eab94ffe83192d3b4c7fc729470a3b459448de3"),
    "ama": (
        "american-medical-association.csl",
        "d70f843d93c2b1e8c59c0e26e2396bea4ed99fb4a1aac69b6dddc249a10fadf7",
    ),
}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def vendor_engine() -> str:
    info = json.loads(fetch(f"https://pypi.org/pypi/citeproc-py/{ENGINE_VERSION}/json"))
    wheel = next(u for u in info["urls"] if u["filename"].endswith("py3-none-any.whl"))
    data = fetch(wheel["url"])
    if sha256(data) != wheel["digests"]["sha256"]:
        raise SystemExit("citeproc-py wheel does not match the hash PyPI published")
    if ENGINE_DIR.exists():
        shutil.rmtree(ENGINE_DIR)
    ENGINE_DIR.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as wheel_zip:
        for name in wheel_zip.namelist():
            if name.startswith("citeproc/") and not name.endswith("/"):
                relative = name[len("citeproc/") :]
                if any(relative.startswith(skip) or f"/{skip}" in relative for skip in ENGINE_SKIP):
                    continue
                if relative.startswith("data/locales/") and Path(relative).name not in (
                    ENGINE_KEEP_LOCALES
                ):
                    continue
                target = ENGINE_DIR / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(wheel_zip.read(name))
            elif name.endswith("licenses/LICENSE"):
                (ENGINE_DIR / "LICENSE").write_bytes(wheel_zip.read(name))
    return wheel["digests"]["sha256"]


def vendor_styles() -> list[tuple[str, str, str]]:
    CSL_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for style_id, (filename, pinned) in STYLES.items():
        data = fetch(CSL_BASE + filename)
        if sha256(data) != pinned:
            raise SystemExit(f"{filename} changed upstream (sha256 {sha256(data)}); review it.")
        (CSL_DIR / filename).write_bytes(data)
        title = re.search(rb"<title>([^<]*)</title>", data)
        rows.append((style_id, filename, title.group(1).decode() if title else filename))
    return rows


def write_notice(engine_sha: str, rows: list[tuple[str, str, str]]) -> None:
    lines = [
        "# Third-party files used by the Reformat feature",
        "",
        "These are copied unmodified. Nothing here is written by the CiteProof project.",
        "",
        f"## Citation Style Language styles (CC BY-SA 3.0), retrieved {RETRIEVED}",
        "",
        "Source: https://github.com/citation-style-language/styles (the official style "
        "repository). Licence: https://creativecommons.org/licenses/by-sa/3.0/ . Each file "
        "names its authors and contributors in its own header. They are unchanged here, so "
        "ShareAlike applies to these files only, not to the rest of this project.",
        "",
    ]
    for _style_id, filename, title in rows:
        lines.append(f"- `{filename}`: {title} (sha256 {STYLES[_style_id][1][:16]})")
    lines += [
        "",
        f"## citeproc-py {ENGINE_VERSION} (BSD 2-Clause), in `docs/py/citeproc/`",
        "",
        "Source: https://pypi.org/project/citeproc-py/ (wheel sha256 "
        f"{engine_sha[:16]}). Copyright 2011-2013 Brecht Machiels. The licence text is in "
        "`docs/py/citeproc/LICENSE`. Only the engine and its English locale files are included; "
        "its schema, bundled styles and scripts are left out. The English locale files come "
        "from the Citation Style Language locales project (CC BY-SA 3.0).",
        "",
        "Note the spelling: `citeproc` is this third-party engine; `citeproof` is this project.",
        "",
    ]
    (CSL_DIR / "NOTICE.md").write_text("\n".join(lines), encoding="utf-8")


def write_manifest() -> None:
    """The list of files the page fetches, once, the first time someone reformats."""
    engine = sorted(
        str(path.relative_to(ENGINE_DIR.parent))
        for path in ENGINE_DIR.rglob("*")
        if path.is_file() and path.suffix in {".py", ".xml", ".json"}
    )
    manifest = {"engine": engine, "csl": [filename for filename, _ in STYLES.values()]}
    (ENGINE_DIR.parent / "engine-files.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


def main() -> int:
    engine_sha = vendor_engine()
    rows = vendor_styles()
    write_notice(engine_sha, rows)
    write_manifest()
    print(f"Vendored citeproc-py {ENGINE_VERSION} and {len(rows)} styles.")
    for _style_id, filename, title in rows:
        print(f"  {filename}: {title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
