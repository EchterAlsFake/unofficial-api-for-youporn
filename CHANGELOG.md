# Changelog

## 1.8.3 — 2026-10-27

- Fetch search results with default arguments and encode search queries correctly.
- Handle empty listing pages, partial collections and users without public collections safely.
- Resolve absolute collection links without adding a second site prefix.
- Let author, performer and collection helpers work without loading unrelated title or name fields for logging.
- Close CLI sessions reliably and report unsuccessful downloads as errors.
- Use the published `eaf-base-api>=4.2.5` dependency.

