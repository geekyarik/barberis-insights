# Code in English; the interface in Ukrainian and English, Ukrainian by default

The team using the dashboard and the call sheet is Ukrainian, while the code, tools, skills and agents work best in English and the repository is public. So code, identifiers, docs, the CLI and MCP tools stay in English, and every word a person reads in the dashboard or the call sheet comes from two catalogs (`i18n/uk.json`, `i18n/en.json`) by stable English keys. Domain modules return codes — segments, statuses, ineligibility reasons, verdict keys with numbers — never display sentences, and the interfaces translate them. We rejected writing the interface in Ukrainian only (the owner and Claude also use English) and translating whole templates per language (two copies drift apart).

## Consequences
- The call sheet's headers and dropdown values are translated, but the sync matches them by key in either language, so a sheet in use never breaks when the language changes.
- `tests/test_i18n.py` keeps the catalogs in step; a missing translation falls back to English, then to the key, so it is visible but never crashes a page.
