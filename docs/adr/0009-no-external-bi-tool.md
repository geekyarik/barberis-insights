# No external BI tool; analysis, reports and ad-hoc exploration are built in

We compared building our own tool with Power BI, Metabase and Looker Studio. None of them can read Altegio (the REST API rejects our partner token), so the import, local database and metrics are ours in any case, and our core needs are application logic a BI tool has no place for: the win-back workflow with the admin's two-way sheet, owner context that excludes or adjusts periods, hypothesis tests, goals measured against baseline runs, Telegram delivery, a Ukrainian interface, and Claude working on the data through MCP. Power BI needs Windows for authoring and paid per-user licences; Looker Studio would move business and client data into Google's cloud; Metabase would add a second service and a second place where metrics are defined. We build ad-hoc exploration ourselves as dashboard components on the same metric registry and analyses, so every number has one definition.

## Considered Options
- **Power BI:** rejected (Windows-only authoring, licence cost, data in Microsoft's cloud for sharing, a second modelling language).
- **Looker Studio:** rejected (data must be copied into Google Sheets or BigQuery, including client data; weak for logic beyond charts).
- **Metabase, self-hosted, as a companion for exploration:** rejected for now. It was the best fit, but it duplicates metric definitions in SQL outside our registry and is one more service to run on the laptop. Revisit only if our own exploration components prove too costly to grow.

## Consequences
- Charts and exploration are code we maintain; we keep them to reusable components (see ARCHITECTURE §6.13) rather than one-off pages.
- Any future BI tool would read the same database through the metric registry's definitions, never redefine them.
