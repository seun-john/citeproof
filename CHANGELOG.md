# Changelog

## Unreleased

- Add a static browser demo in `docs/` that runs CiteProof's unchanged Python with Pyodide. No change to the CiteProof package.

## 0.1.0

First release.

- `citeproof check`: compare references with a catalogue you supply (DOI, title, authors, year, journal), find duplicates, uncited references, missing bibliography entries and supplied retraction flags.
- `citeproof claims`: attach source passages to claims and flag missing citations, unavailable passages, abstract-only evidence and number discrepancies.
- `citeproof from-bibtex`: turn a .bib file into check input.
