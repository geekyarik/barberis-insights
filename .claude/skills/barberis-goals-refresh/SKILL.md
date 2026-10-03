---
name: barberis-goals-refresh
description: Monthly refresh of BARBERIS barbershop data in the local barberis-insights service. Pulls the latest weeks of appointments and work schedules from Altegio (Altegio Pro connector), imports them, saves a monthly measurement so goals update, refreshes the client risk list and win-back attribution, syncs the admin's call sheet, and reports progress. Use when the user asks to refresh, update or measure the barber goals, the monthly barbershop numbers, or the win-back results.
---

# BARBERIS monthly refresh

This skill lives in the barberis-insights repo (`.claude/skills/`), next to the code it drives. Everything lives in the local service at `~/Public/Projects/barberis/barberis-insights`:
- **Database:** `var/insights.sqlite`
- **Dashboard:** `insights serve` → http://127.0.0.1:8765
- **MCP tools:** the `barberis-insights` server

Run its CLI as `uv --directory ~/Public/Projects/barberis/barberis-insights run insights <command>` (written `insights …` below).

Tools needed: the **Altegio Pro** connector (`mcp__claude_ai_Altegio_Pro__*`) and the **barberis-insights** MCP server. Load them with ToolSearch. The local `altegio` MCP server is not used, because Altegio rejects its partner token.

## Steps

### 1. Where are we?
Run `insights status`. It reports:
- **`completed_visits_up_to`:** how fresh the data is.
- **`last_measurement_window_to`:** the end of the last measurement.
- **`next_window`:** the suggested measurement window (whole ISO weeks, at least 2). If it says too early, still refresh data and risk (steps 2–3 and 5), but skip step 4.
- **`fetch_appointments_from`:** start fetching here. It is 14 days before the next window, so visit statuses that staff changed late are updated.

### 2. Fetch and import appointments
1. Call `appointments_list` with:
   - `location_id: 209563`, `page_size: 300`
   - one calendar month at a time, from `fetch_appointments_from` to the end of `next_window` (or yesterday if it's too early)
2. Follow `pagination.next_page` until it is `null`.
3. Fetch pages **one at a time**. Parallel calls can save two results under one filename, and a page is lost.
4. Import:
   - **Large results** are saved to files (the result names the path). Pass the paths to `insights ingest <file> [<file> …]`, or to the MCP tool `ingest_files`.
   - **A small page that comes back inline:** Write its `items` array to a JSON file in scratch, then ingest that file.
5. Check the per-month counts on the dashboard's *Data & sync* page. A month has roughly 450–600 appointments.

### 3. Fetch and import schedules
1. Run `team_members_list` for the location.
   - **New barber** (active, offers haircuts), or a tracked barber now **dismissed:** tell the user and ask before changing anything.
   - **Barbers table:** after the user confirms, run `insights barber add --key <key> --altegio-id <id> --name <name> --tier <level>` or `insights barber deactivate --key <key> --left YYYY-MM-DD`. `insights barber list` shows who is tracked.
2. For each active barber, call `schedules_get` for the same window. It is small and comes back inline.
3. Write the working days to a text file, one line per day: `YYYY-MM-DD HH:MM-HH:MM [HH:MM-HH:MM …]`, with the slots exactly as returned.
4. Run `insights import-schedule <barber-key> <file>`. Dates in the file replace that barber's existing slots.

Barber keys and their Altegio IDs: run `insights barber list`. The roster is private (ADR-0006) and is never written into this file.

### 4. Save the measurement
Run `insights snapshot --from <next_window[0]> --to <next_window[1]>`, or use the MCP `compute_snapshot`. Goals on the dashboard update immediately.

### 5. Clients and win-back
1. `insights risk --limit 20`: rebuilds client profiles and shows the top of the call list.
2. Contacts:
   - **The source:** phone numbers come from the Altegio client export. Remind the user to export Clients → Export in Altegio when phones are stale or missing (`clients_with_phone` in `status`).
   - **Importing:** run `insights import-clients FILE`, with `--dry-run` first to confirm the columns are recognised.
   - **Never fetch contacts in bulk** through the connector. It returns them inline, into the conversation.
3. Admin sheet:
   - **If `INSIGHTS_SHEET_ID` is set:** run `insights sheet-sync`. It pulls the admin's outcomes, marks returned clients, sends approved cases and archives closed ones.
   - **Otherwise:** run `insights attribute`.
4. Don't propose or approve cases yourself unless the user asks. They review the risk list in the dashboard.

### 6. Report
Use `insights goals` (or the MCP `list_goals`), `list_cases`, and `search_context` for anything that explains a change: price changes, staff changes, time off. Tell the user:
- **Goals:** for each barber and the team, which moved, which are behind, and which reached their target.
- **Biggest changes** since the previous measurement, with context from notes.
- **Win-back results:** won back, revenue recovered, open cases.
- **Data gaps:** stale contacts, missing schedule days.

Record anything new you learned as a note with `add_note` (kind `observation`, the right scopes).

## Metric definitions
See `insights` → `list_metrics`, and the docstrings in `src/barberis_insights/metrics/core.py`. They are validated against the 2026-09-27 baseline by `tests/test_metrics_baseline.py`. Run `uv run pytest` in the repo after any change to metrics.

## Known limits
- **Revenue:** it is the service price after discounts. Service payments are not recorded in Altegio, and product sales are excluded.
- **No-shows and cancellations:** cancelled appointments are deleted in Altegio. No-shows depend on staff marking them.
- **Time off:** monthly values swing with time off. Mention it rather than reading it as a trend.

The original refresh scripts and data cache were imported into the service on 2026-10-02. They are kept only as a private archive in `var/legacy-skill/` (git-ignored); don't use them for the refresh.
