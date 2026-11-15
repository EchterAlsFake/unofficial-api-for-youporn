# 2.0.0

Release 2.0.0

Update pagination handling, validation, and documentation.

Changes since v1.8.4:

```text
README.md          |  13 +++++++
 pyproject.toml     |   4 +--
 youporn_api/api.py | 100 ++++++++++++++++++++++++++++++-----------------------
 3 files changed, 72 insertions(+), 45 deletions(-)
```

# Changelog

## 1.8.4 - 2026-11-14

- Retain scene cast link labels alongside existing performer URLs for metadata export.

## 1.8.3 — 2026-10-27

- Fetch search results with default arguments and encode search queries correctly.
- Handle empty listing pages, partial collections and users without public collections safely.
- Resolve absolute collection links without adding a second site prefix.
- Let author, performer and collection helpers work without loading unrelated title or name fields for logging.
- Close CLI sessions reliably and report unsuccessful downloads as errors.
- Use the published `eaf-base-api>=4.2.5` dependency.

