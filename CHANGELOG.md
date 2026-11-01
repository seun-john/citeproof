# Changelog

## Unreleased

- `check --match-initials` (and `citeproof(data, match_initials=True)`): optionally accept `McKinney, W.` as `McKinney, Wes` when the author lists have the same length and order, the family names match, and each given name is identical or one side is the first letter of the other. Off by default; listed in `accepted_equivalences`.
- `check` and `claims` reports have a `coverage` block (references with or without a catalogue record; claims that need a person), a one-line summary on stderr and in the HTML report.
- `--min-coverage PCT`: exit 3 when fewer than PCT percent of items were decided and nothing else failed.
- `check`: an abbreviated journal name (`Nat Prod Rep`) is accepted as the catalogue's full name (`Natural Product Reports`), and a `RETRACTED:` / `Retraction:` / `Withdrawn:` prefix on the catalogue title is ignored in the title comparison. Both are listed in `accepted_equivalences` on the finding. Different journals are still `METADATA_MISMATCH`.

## 0.1.0

First release.

- `citeproof check`: compare references with a catalogue you supply (DOI, title, authors, year, journal), find duplicates, uncited references, missing bibliography entries and supplied retraction flags.
- `citeproof claims`: attach source passages to claims and flag missing citations, unavailable passages, abstract-only evidence and number discrepancies.
- `citeproof from-bibtex`: turn a .bib file into check input.
