# CiteProof in your browser

A static demo of [CiteProof](../README.md). A student pastes a reference list, and the page shows which references match a catalogue of known records. CiteProof's own Python code runs inside the browser tab using [Pyodide](https://pyodide.org). There is no server.

Nothing here is a verdict on a reference. Every result says what CiteProof compared, shows the evidence, and says that **a person must decide**.

## Privacy note

- **What you paste stays in your browser tab.** The reference list, any catalogue file you load and the results are handled by JavaScript and Python running on your device. They are not uploaded, logged or stored, apart from the Crossref lookups described below. The page uses no cookies, no `localStorage`, no analytics and no third-party scripts besides Pyodide. Closing the tab discards everything; the *Clear* button empties the box sooner.
- **What the page downloads when it opens:** its own files from wherever it is hosted (GitHub Pages, if you publish it there), and Pyodide from `cdn.jsdelivr.net`, pinned to version 0.29.5 and checked with a Subresource Integrity hash. Those requests carry no part of your list. As with any website, the host and the CDN can see ordinary connection data such as your IP address and which files you asked for. This project does not control that data.
- **Two Crossref lookups are on by default and can be switched off.** Both have a visible tick-box just above the *Check references* button. When ticked, pressing *Check* runs them automatically, one request at a time, and the results list every address that was sent. Untick both and nothing leaves your device.
  - *DOI lookup:* for references whose DOI is not in the catalogue, `https://api.crossref.org/works/<DOI>`. Only DOIs are sent.
  - *Title search for references with no DOI:* `https://api.crossref.org/works?query.bibliographic=<words>&rows=3&select=...`, where the words are that reference's **title, its first author's family name and its year**. That is more revealing than a DOI because it is the reference's own wording, which is why it is a separate choice. The rest of the list, the other authors and the journal are not sent.
  - In both cases Crossref can also see your IP address and the usual request headers. No email address, API key or cookie is used.
- **A Content-Security-Policy** in the page limits it to its own files, `cdn.jsdelivr.net` and `api.crossref.org`. A static policy cannot switch the Crossref allowance on and off, so it is always listed; the code only contacts Crossref while one of the two tick-boxes is on. An automated test records every request the page makes during a check and fails if one goes anywhere else, if any request carries a body, or if any text you pasted appears in a request.
- **Downloads** (CSV, JSON) are built in your browser and saved by it. Reports can contain your references; read them before sharing.

## What it checks, and what it does not

It runs CiteProof's `check` command, unchanged: each reference is looked up **by DOI** in the catalogue and compared on title, authors, year and journal. The verdict names and messages are CiteProof's own (`VERIFIED`, `METADATA_MISMATCH`, `NEEDS_REVIEW`, `DUPLICATE`, `RETRACTED`, `UNCITED_REFERENCE`, `MISSING_REFERENCE`); the page adds plain-language lines beside them, clearly separate.

The summary counts each reference once, by its comparison result: **Verified**, **Metadata mismatch**, or **No verdict** (`NEEDS_REVIEW`: no DOI, or a DOI that is not in the catalogue). The three counts always add up to the number of references, and none is shown more prominently than another. When the only difference is how the authors' given names are written (initials such as "McKinney, W." against "McKinney, Wes"), the card says so and the summary notes how many mismatches are like that. This is display only: CiteProof still reports `METADATA_MISMATCH`, and the reference is not counted as verified. `DUPLICATE`, `RETRACTED`, `UNCITED_REFERENCE`, `MISSING_REFERENCE` and "retraction status not supplied" are listed as additional flags and are not part of those three counts.

For a reference that gets no verdict, the page also checks whether the catalogue holds a record with the same **title**, and if so shows "Possible match by title (advisory)". This runs on your device, never changes the verdict, and exists because CiteProof matches by DOI only: it helps with citations that have no DOI or a wrong one. A person has to confirm it is the same work.

The page has a "What this does not check" panel. In short: it does not decide whether a reference exists in the real world, whether a source supports a claim, whether a source is good, who wrote a text, citation style, or anything an academic-integrity process would decide. A reference that is "not found in this catalogue" says nothing about whether it is real.

## Limits

- **Pasted text is read by the demo's own best-effort reader, not by CiteProof.** CiteProof reads only BibTeX or JSON. `docs/py/text_references.py` splits a pasted list into references (blank lines, numbering, hanging indents or one per line) and reads the DOI, authors, year, title and journal where it recognises APA, Harvard, Chicago author-date, MLA or Vancouver layout. It leaves out any field it cannot read rather than guessing, and every card has a "Details" section that shows how the text was read. Unusual layouts, corporate authors and chapters can be misread. Google Scholar's *Cite* box usually gives no DOI, and CiteProof can only look a reference up by DOI, so those references get no verdict.
- **Initials and shortened author lists count as differences.** CiteProof compares given names letter for letter, so APA's "McKinney, W." differs from a catalogue's "McKinney, Wes", and "et al." or "…" gives a shorter list. That is CiteProof's rule and the demo does not change it; the card notes when family names match.
- **Formats.** References: pasted text, BibTeX or CiteProof JSON. Catalogue: CiteProof's JSON, or CSV. **CSV is a convenience of this demo, not a CiteProof format**; it is converted to CiteProof's records by `docs/py/demo_logic.py` (a blank `retracted` cell becomes "not supplied", not "false"). Rows with no DOI are skipped and counted.
- **BibTeX has no citation list.** Every entry is treated as cited, as in `citeproof from-bibtex`, so `UNCITED_REFERENCE` and `MISSING_REFERENCE` can only appear with JSON that has a `"citations"` list.
- **Size.** Up to 300,000 characters of references (500 references), and a catalogue of up to 8 MB / 50,000 records. The work runs on the page's main thread, so very large inputs can make the tab unresponsive.
- **The sample catalogue is tiny** (7 records) so that most real references will get no verdict. It exists so the demo works out of the box.
- **Matching is by wording, not meaning**, as in CiteProof. A reference can match a real record and still be cited for the wrong reason.
- **First load** downloads about 12 MB (Pyodide) and needs a browser with WebAssembly. There is no offline mode.
- **Both Crossref features are tested automatically against mocked responses** (success, not found, rate-limited, unreachable, stopped). The maintainer has also run them once against the live Crossref and they returned records, "no record" for an invented DOI, and title-search suggestions. Titles from Crossref have markup tags removed and entities decoded before comparison. A DOI Crossref does not know may be registered with another agency, such as DataCite.
- **CiteProof's `claims` command is not part of this demo.**

## Finding a DOI when a reference has none

CiteProof looks references up by DOI, and citations copied from Google Scholar usually have none. For references that get no verdict the page offers two things, neither of which changes a verdict by itself:

1. **"Possible match by title (advisory)"**: if the catalogue holds a record with the same title. Local, nothing sent.
2. **Title search on Crossref (on by default, can be switched off):** up to three possible DOIs per reference, shown with their title, authors, year, journal and a title-similarity score. **Nothing is chosen automatically.** The reference stays at "no verdict" until the person presses *Use this DOI and check again* on a match they have read. CiteProof then compares the reference with that record as usual, and the card, the summary notice and the CSV all say the DOI was added by the person and was not in the pasted reference. A reference that already has a DOI is never changed.

Some works have no DOI at all (many books, reports, web pages and older papers). For those, "no verdict" is the correct result.

## Sample data

`docs/data/sample-catalogue.json` holds seven real records, each with its source in its `provenance` field. It contains bibliographic facts only (DOI, title, authors, year, journal), no abstracts or article text.

| Records | Source |
| --- | --- |
| NumPy, SciPy, pandas (McKinney 2010), seaborn, scikit-image | The citation files those projects publish for their own papers, pinned by SHA-256 in `scripts/build_sample_catalogue.py`. The five papers are published open access; the pandas source file states CC-BY-3.0, so check the publisher's page for the others. |
| Two retracted 2004/2005 *Science* papers | The [Retraction Watch dataset](https://gitlab.com/crossref/retraction-watch-data) that Crossref publishes (commit `a503965`, 2026-10-19). That repository has no licence file, and its terms could not be read when the demo was built, so check [Crossref's page on the data](https://www.crossref.org/documentation/retraction-watch/) before redistributing it. |

A record is marked `"retracted": false` only because its DOI is **not listed** in that dataset on that date. The provenance text says so.

`sample-references-text.txt`, `sample-references-good.bib`, `sample-references-messy.bib` and `sample-references.json` are generated from the catalogue by `scripts/build_sample_references.py`. Each defect in the messy list is labelled. One entry, `invented2026`, is invented for the demo.

## Run it locally

Browsers will not run this from a `file://` address. Serve the `docs` folder:

```bash
python -m http.server 8000 --directory docs
# then open http://localhost:8000
```

You need an internet connection the first time, because Pyodide loads from the CDN.

## Develop and test

```bash
pip install -e ".[dev]"
python scripts/sync_citeproof.py        # copy src/citeproof into docs/py/citeproof (never edit that copy)
ruff check . && ruff format --check . && pytest -q
```

`pytest` runs CiteProof's own tests plus `tests/test_demo_logic.py`, which covers the demo's data handling and proves `docs/py/citeproof` is byte-identical to `src/citeproof`. CI runs these.

The headless-browser tests (`tests/browser`) load the page in Chromium and cover a good list, a messy list, pasted text, an empty input, the title search, privacy (every request audited), a CDN failure, a tampered Pyodide file, catalogue upload, CSV export, the Crossref flows, keyboard-only use, a phone width and dark mode. They skip unless Playwright and Chromium are installed.

```bash
pip install playwright               # use an installed Chromium, or: playwright install chromium
pytest tests/browser -q              # uses the real CDN
# or, offline, from a local copy of the pinned release (pyodide.js, wasm, python_stdlib.zip,
# pyodide-lock.json and the sqlite3 wheel from pyodide-0.29.5.tar.bz2):
PYODIDE_DIST=/path/to/pyodide pytest tests/browser -q
SCREENSHOT_DIR=shots pytest tests/browser -q     # also writes screenshots
```

To rebuild the sample data: `python scripts/build_sample_catalogue.py` (needs network) then `python scripts/build_sample_references.py`.

### Check the CDN pin after publishing

The page loads `pyodide.js` with an integrity hash. To confirm the hash matches what the CDN serves:

```bash
curl -s https://cdn.jsdelivr.net/pyodide/v0.29.5/full/pyodide.js | openssl dgst -sha384 -binary | openssl base64 -A
# expected: VR47TfKeAmT7vMej7bwOVg0tHTQLLGMSIpsXtFMCZG5OpKZSIXoSLtGY//qHcxc6
```

If it differs, the browser refuses the script and the page shows its "could not be loaded" message.

## Changes to CiteProof

None. The Python in `src/citeproof` is unchanged. The only browser-specific step is loading Pyodide's `sqlite3` module before importing it, because CiteProof's `core.py` imports `sqlite3` for a helper this demo does not use.

## AI-use note

This demo was built with [Claude Code](https://claude.com/claude-code), Anthropic's AI coding assistant, working from a brief written by the maintainer. The assistant wrote the page, the demo's Python, the tests and this README, and assembled the sample data from the public sources above. It did not change CiteProof's own code.

Automated tests and a contrast and accessibility audit were run, but the demo has not been independently reviewed or validated, and nothing here claims users, adoption or impact.

**Maintainer review status: not yet recorded.** *(seun-john: replace this line with "Reviewed by seun-john on YYYY-MM-DD" once you have reviewed the code, the sample data and the wording.)*

## Licence

MIT, as for CiteProof. See [LICENSE](../LICENSE). Pyodide is MPL-2.0 and is loaded from its CDN, not copied here.
