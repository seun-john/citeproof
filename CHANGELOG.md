# Changelog

## Unreleased

- `check`: an abbreviated journal name (`Nat Prod Rep`) is accepted as the catalogue's full name (`Natural Product Reports`), and a `RETRACTED:` / `Retraction:` / `Withdrawn:` prefix on the catalogue title is ignored in the title comparison. Both are listed in `accepted_equivalences` on the finding. Different journals are still `METADATA_MISMATCH`.

## 0.1.0

First release.

- `citeproof check`: compare references with a catalogue you supply (DOI, title, authors, year, journal), find duplicates, uncited references, missing bibliography entries and supplied retraction flags.
- `citeproof claims`: attach source passages to claims and flag missing citations, unavailable passages, abstract-only evidence and number discrepancies.
- `citeproof from-bibtex`: turn a .bib file into check input.
