# barberis-insights

A local service for BARBERIS barbershop. It brings these together in one SQLite database:
- Altegio data: appointments, schedules and clients
- barber metrics and goals
- clients at risk and a win-back workflow for the admin
- business context notes and hypothesis tests

You use it through a web dashboard, a CLI, and an MCP server for Claude.

## Quick start

```bash
uv sync
uv run insights init                       # create / upgrade the database (var/insights.sqlite)
uv run insights import-legacy --artifact-export var/artifact_export   # one-time: earlier analysis data
uv run insights seed                       # default offers + known business events
uv run insights serve                      # dashboard on http://127.0.0.1:8765
uv run pytest                              # 32 tests, incl. baseline regression on the real data
```

**Private files.** These live in `var/` and are never committed:
- `var/barbers.json`: the initial staff roster, `[{"key", "altegio_id", "name", "tier"}]`, used by `import-legacy`. After that, manage barbers with `insights barber …`.
- `var/seed_notes.json`: known business events loaded by `insights seed`, as `[{"date_from", "date_to", "kind", "scopes", "title", "body", "tags"}]`.
- `.env`: settings such as `INSIGHTS_SHEET_ID`.
- `var/google_oauth_client.json` and `var/google_token.json`: Google sign-in.
- client exports in `var/imports/`.

## Daily and monthly use

| Task | Command or place |
|---|---|
| See the team, a barber, goals | dashboard: Overview, barber pages, Goals |
| Monthly refresh (fetch → import → measure → report) | ask Claude: "refresh the barber goals" (skill `barberis-goals-refresh`) |
| Where is the data, what window to measure next | `insights status` |
| Import files Claude saved from the Altegio Pro connector | `insights ingest FILE…` |
| Import a barber's schedule (text lines) | `insights import-schedule KEY FILE` |
| Import client names and phones | `insights import-clients EXPORT.xlsx` (`--dry-run` first) |
| Store a measurement | `insights snapshot --from 2026-09-28 --to 2026-10-25`, or Data & sync page |
| Call list | dashboard: Clients at risk, or `insights risk` |
| Send approved cases to the admin, pull outcomes | `insights sheet-sync`, or Win-back page |
| Test an idea | dashboard: Hypotheses, or `insights hypothesis …` |
| Add or remove a barber | `insights barber add|deactivate|list` |

## Win-back workflow
1. **Find candidates.** *Clients at risk* ranks clients by priority (value × how recoverable × loyalty), in segments:
   - **overdue:** silent longer than max(45 days, 1.5 × their own usual gap)
   - **lapsed:** silent for over 180 days
   - **one-time:** came once and not since
   - **slipping:** past their usual gap, not yet overdue
   - **switched:** still coming, but now to a different barber
2. **Propose and approve.** Select clients and **Propose**, then **Approve** them, optionally assigned to an admin. You can also test two offers against each other: tick two offers and each case gets one at random.
3. **The admin calls.** `sheet-sync` adds approved cases to the Google Sheet. The admin fills in *Call date*, *Outcome*, *Offer given* and *Note*.
4. **Outcomes come back.** The next `sheet-sync` pulls the admin's edits.
   - **Came back:** a case becomes **won back** when the client completes a visit within 60 days of the call. Its revenue is recorded.
   - **Did not return:** otherwise the case becomes **not returned**.
   - **Closed cases** move to the *Done* tab without phone numbers.
5. **Review results** on the *Win-back* page: by offer, by admin and by segment. If you ran an offer test, evaluate it as a *Win-back offer A/B* hypothesis.

### Admin call sheet (Google Sheets) setup
1. In Google Cloud Console, create a project and enable the **Google Sheets API** and **Google Drive API**.
2. Create an **OAuth client ID** of type *Desktop app*. Download the JSON to `var/google_oauth_client.json`.
3. Create an empty Google Sheet and share it with the admin (editor). Put its id in `.env`; the id is the part of the URL between `/d/` and `/edit`:
   ```
   INSIGHTS_SHEET_ID=1AbC...xyz
   ```
4. Run `uv run insights sheet-sync`. The first run opens a browser for consent, and the token is stored in `var/google_token.json`. It creates the *Call list* and *Done* tabs, with dropdowns for Outcome and Offer.

`insights sheet-sync --dry-run` shows what would be sent, using an in-memory sheet.

### Client contacts
Contacts come from Altegio's own export: **Clients → Export** (Excel). Run `insights import-clients FILE --dry-run` to see which columns were recognised. If a header isn't matched, add it to `ALIASES` in `ingest/client_export.py`.

Clients without a phone, without data-processing consent, or marked *do not contact* are never sent to the sheet.

## Claude integration
- **MCP server:** registered as `barberis-insights`, with `claude mcp add barberis-insights --scope user -- uv --directory <repo> run insights mcp`. It has 17 tools:
  - metrics and measurements
  - goals (read and write)
  - risk list and client card
  - win-back cases
  - notes (`add_note`, `search_context`)
  - hypotheses (create and evaluate)
  - playbook
  - `ingest_files`
  - `sql_readonly` for ad-hoc analysis
- **Skill:** `~/.claude/skills/barberis-goals-refresh` runs the monthly refresh against this service.
- **Altegio data:** it arrives through the claude.ai **Altegio Pro** connector, because Altegio rejects the REST partner token (see note "Altegio partner token rejected"). Once a working token exists, add a REST source next to `ingest/connector_files.py` and schedule it with launchd.

## Architecture

```
src/barberis_insights/
  config.py              settings (env prefix INSIGHTS_), default barbers
  db/                    SQLAlchemy models, session, Alembic migrations (db/migrations)
  ingest/                connector files, client export, legacy import, shared upserts
  metrics/               registry + built-in metrics (core.py), window context, weekly rows
  clients/               client profiles and risk segments
  outreach/              cases, offers, attribution, Google Sheet sync
  goals/ context/ experiments/ playbook/   domain services
  web/                   FastAPI app, Jinja templates, vendored Chart.js
  mcp_server.py, cli.py
legacy/                  the original analysis scripts and data, kept for reference and tests
var/                     database, exports, credentials — gitignored, never commit
```

**Extending**
- **New metric:** add a function with `@metric("key", "Label", unit, direction)` in `metrics/core.py` or any imported module. Measurements are stored in long format, so no migration is needed. It appears in goals, hypotheses, the API and MCP automatically.
- **New data source:** write rows through `ingest/base.py` (`upsert_appointments`, `replace_schedule`, `sync_run`).
- **Schema change:** edit `db/models.py`, run `uv run alembic revision --autogenerate -m "…"`, then `insights init`.
- **Postgres:** swap `Settings.db_url`. Everything goes through SQLAlchemy, except the FTS5 note search in `context/service.py`.
- **JSON API:** `/api/*`, documented at http://127.0.0.1:8765/api/docs. It can back a future SPA.

## Privacy
- **What is stored:** client names, phones and emails are personal data. They live only in `var/insights.sqlite` and the admin's sheet.
- **Where it runs:** keep this repo private, `var/` gitignored and the disk encrypted (FileVault). The dashboard binds to 127.0.0.1 only and rejects cross-site form posts.
- **What the sheet keeps:** only what the admin needs for the call. Phone numbers are removed when a case closes.
