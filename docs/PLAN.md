# barberis-insights — Plan

How we evolve the architecture in [`ARCHITECTURE.md`](ARCHITECTURE.md): which skills to use, in what order, and what "done" means at each step. Update this file when a phase finishes or the order changes.

## Skills we use

From the `mattpocock-skills` plugin, plus our own skills:

| Skill | Used for | Produces |
|---|---|---|
| `setup-matt-pocock-skills` | One-time repo setup: issue tracker (GitHub Issues on `geekyarik/barberis-insights`), labels, doc layout | config |
| `grill-with-docs` (= `grilling` + `domain-modeling`) | Stress-test a plan or design and settle the vocabulary as we go | `CONTEXT.md`, `docs/adr/*` |
| `research` | Facts from primary sources (APIs, data feeds, regulations) | `docs/research/*.md` |
| `improve-codebase-architecture` (uses `codebase-design`) | Find module-boundary and deepening refactors in existing code | refactor candidates, then tickets |
| `wayfinder` | Work too big for one session: a map of decision tickets resolved one by one | GitHub issues |
| `to-spec` → `to-tickets` | A well-understood feature becomes a spec and small tickets with their blocking order | GitHub issues |
| `tdd` / `implement` | Build one ticket, test-first for domain logic | code + tests |
| `code-review` | Review each change before merging | review |
| `handoff` | Pass context between sessions on long work | handoff note |
| `writing-for-agents` | Keep `CLAUDE.md` / `AGENTS.md` pointing agents at these docs | `CLAUDE.md` |
| `prototype` | A throwaway check of a UI or model idea before committing to it | prototype |
| `barberis-goals-refresh` (ours) | The monthly cycle: import → analyze → compare → report | runs + report |

**Default loop for any feature:** `grill-with-docs` (if it brings new concepts) → `to-spec` → `to-tickets` → per ticket: `tdd` → `code-review` → update `ARCHITECTURE.md` §5/§9 if boundaries changed.

## Phases

### Phase 0 — Set up *(short)*
1. Run `setup-matt-pocock-skills`: GitHub Issues as the tracker, the doc layout as in this repo (root `CONTEXT.md`, `docs/adr/`).
2. Run `writing-for-agents` to write the repo's `CLAUDE.md`. It should tell agents to read `CONTEXT.md` and `docs/ARCHITECTURE.md` first, to follow ADR-0006 (no private data in git) and ADR-0007 (analyses are code), and to run `uv run pytest`.

**Done when** the other skills can find the tracker and the docs.

### Phase 1 — Settle the architecture *(next)*
Run `grill-with-docs` on `docs/ARCHITECTURE.md`. It should resolve the [open questions](#open-questions), turn the *proposed* terms in `CONTEXT.md` into accepted ones, and accept, rewrite or reject ADR-0005.

**Done when** no *open question* markers remain in `ARCHITECTURE.md` §6, and ADR-0005 has a final status.

### Phase 2 — Analyses as code *(the highest-value build)*
Turn the hand-made analyses into code, so the analysis cycle (ARCHITECTURE §3) can run. Use `wayfinder`, because it spans several sessions, then `to-tickets` and `tdd`:
1. **Metrics, one module each:** split `metrics/core.py` into `metrics/<family>/<metric>.py` with `VERSION` and a fixture test each. Add the metrics the analyses need but which don't exist yet: revenue per work day, visits per work day, booking length, unique clients, revenue concentration, usual gap. The baseline regression test must stay green.
2. **Analysis framework:** the `Analysis` contract, `AnalysisResult`, the `analysis_runs` table, `insights analyze` and `insights compare`, and the MCP tools `run_analysis`, `list_runs`, `compare_runs`.
3. **First analyses**, ported from the hand-built pages and `legacy/`, each against fixture data first, then checked against the legacy numbers:
   - `barber_scorecard`
   - `weekly_book`
   - `weekday_pattern`
   - `price_demand`
   - `client_retention`
   - `return_cohorts`
   - `client_sources`
   - `exclusive_clients`
   - `departure_impact`
   - `new_clients`
   - `service_mix`
   - `overdue_regulars`
4. **Baseline:** run every analysis for the 2026-01-12 – 2026-09-27 window and store the runs as **Baseline 2026-09-27**. Re-point the existing goals at it.
5. **Reports:** the barber book and team comparison as dashboard pages rendered from stored runs, plus HTML export. Then retire the two claude.ai artifact pages, with your go-ahead before deleting.
6. **Monthly cycle:** update `barberis-goals-refresh` to run import → analyze → compare (with the baseline and previous run) → report.

**Done when** a new month's data produces runs for every analysis, and the dashboard shows each barber's and the team's comparison with the baseline and goal status, with no hand-made analysis needed.

### Phase 3 — Clean module boundaries
Run `improve-codebase-architecture` on the code, after Phase 2 has added the Analyses module. Expected candidates:
- **Module service interfaces:** each module exposes one, instead of passing a database session around.
- **Interfaces call services:** `web/app.py` and `mcp_server.py` go through module services, not tables.
- **Shared scope type:** a single `Scope` type (shop / team / barber / segment) used by every module.

Then `to-tickets`, and `tdd` per ticket.

**Done when** no interface queries another module's tables and §9 "Module boundaries" is marked done.

### Phase 4 — Research outside data *(can run any time from Phase 1)*
Run `research` on candidate sources for external factors:
- air-raid alert history for Lviv
- planned power-outage schedules
- Ukrainian public holidays and school calendar
- weather

Record availability, licence, history depth and reliability.

**Done when** `docs/research/external-factor-feeds.md` recommends which feeds to build, if any.

### Phase 5 — Context v2: factors, treatments, lenses
The second source of truth, built into the analyses. Use `wayfinder`:
1. The `factors` model and its migration from `notes` (existing notes become *annotate* factors).
2. Dashboard and MCP: create, edit and list factors; show them on timelines, charts and reports.
3. Lenses: define them and apply them in Metrics and Analyses (*exclude* and *adjust* first). Runs, measurements and goals record their lens.
4. Experiments: *control* treatment, and "test this belief" from a factor.
5. Per-client and segment factors, if Phase 1 decides we need them.

**Done when** the owner can record "a power outage cut Tuesday 14–18 short", see the barber book with and without it, and compare runs under the same lens.

### Phase 6 — Automation and new data *(blocked or optional)*
- **Altegio REST adapter + scheduler (launchd)** for the full monthly cycle: blocked until Altegio issues a working partner token (ADR-0002).
- **Factor feeds:** whichever ones Phase 4 recommended.
- **Finance module:** product sales, costs, payroll, if Altegio access allows.

### Every month
Run `barberis-goals-refresh`. Until Phase 2 lands, it saves a measurement and reports from goals. After that, it runs all analyses and compares them with the baseline and the previous run. Record new Context while doing it.

## Open questions
For the Phase 1 grilling session.

1. **Users:** only the owner, or managers too? Does anyone besides the owner need access off the laptop? This affects ADR-0003.
2. **Factor time grain:** do factors need hours (outages, alerts) or are days enough? Do we need recurring factors (every summer, school holidays)?
3. **Per-client context:** can a factor apply to one client or a segment (for example "abroad until June")? Should that pause overdue status and win-back?
4. **Beliefs:** how precise should a belief be: direction only, rough size, or a number with confidence?
5. **Default lens:** should every analysis, goal and report use one default lens, or does each goal choose its own?
6. **Versions:** when a metric or analysis definition changes, do we re-run past windows automatically so old and new stay comparable?
7. **Analysis cadence:** monthly runs only, or also weekly runs for operational use (busy share, overdue clients)? Which windows does a comparison use: same length, or month against month?
8. **First analyses:** are the twelve listed in Phase 2 the right ones, and in what order? Is anything missing (for example per-service profitability, front-desk vs online conversion)?
9. **Priorities:** which decisions should the tool help with first: pricing, schedules and staffing, client retention, marketing, or barber development?
10. **External factors:** which matter most for this shop and its clients: air-raid alerts, power outages, migration and mobilisation, the economy, weather, holidays, competition?
11. **Personal data retention:** how long do we keep contact details for clients who haven't visited in years?
12. **Reports:** how often, for whom, and in what form (dashboard page, HTML export, message)?
