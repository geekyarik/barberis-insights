# Import Altegio data through connector files and the client export, not the REST API

> **Superseded by [ADR-0013](0013-fetch-from-the-altegio-rest-api.md) on 2026-10-17** for appointments, shifts and client contacts. The client export is still the source for the do-not-contact tags.

Altegio's REST API rejects our partner token ("Partner ID not specified", the account owns no developer account), so imports go through files saved by Claude from the claude.ai Altegio Pro connector plus Altegio's own client export (Excel). The export has no client ID column, so rows are matched to clients by first/last visit time, with names breaking ties. All adapters write through one ingest interface, so a REST adapter and a scheduler can replace this path once a working partner token exists, without touching other modules.
