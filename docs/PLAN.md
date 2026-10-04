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

## Build order (decided 2026-10-03)
Phases below keep their descriptions; this is the order they ship in.
1. **History import** *(appointments done 2026-10-04: 2022–2024, 18,643 rows, no gaps)*. Shifts done 2026-10-04: continuous from 2022-01-03 for the six current barbers and eleven former ones, who were added to `barbers` as inactive; four deleted team members have no fetchable shifts.
2. **Metrics split** *(done 2026-10-04, with versioned measurements and goals)*. The 2026-09-27 baseline test stays green; `risk_n` is at version 2.
3. **Analysis framework** and the first three analyses: `client_retention`, `overdue_regulars`, `barber_scorecard`, with `analysis_runs`. *(Done 2026-10-04.)*
4. **Thin Phase 2b:** Notifications with a Telegram adapter (separate bot), the Scheduler with `data_watch` and `sheet_sync`, then `weekly_review`.
5. **The remaining analyses** in the order `weekly_book`, `weekday_pattern`, `return_cohorts`, `new_clients`, `client_sources`, `exclusive_clients`, `departure_impact`, `price_demand`, `service_mix`, `seasonality`; then Reports with `report_runs`; then retire the two artifact pages (with your go-ahead).
6. **Research** (Phase 4) any time after step 1. **Context v2** (Phase 5) after step 5. **Explorer** (Phase 2c) last.

**Rules while building:** new modules (Analyses, Reports, Scheduler, Notifications) get a service interface from their first commit: one entry point, no reads of foreign tables. Existing modules are refactored in Phase 3. The Baseline stays 2026-09-27 and existing Goals stay against it; the 2022–2025 history is a separate *reference* run for same-week-last-year and seasonality comparisons.

## Phases

### Phase 0 — Set up *(short)*
1. Run `setup-matt-pocock-skills`: GitHub Issues as the tracker, the doc layout as in this repo (root `CONTEXT.md`, `docs/adr/`).
2. Run `writing-for-agents` to write the repo's `CLAUDE.md`. It should tell agents to read `CONTEXT.md` and `docs/ARCHITECTURE.md` first, to follow ADR-0006 (no private data in git) and ADR-0007 (analyses are code), and to run `uv run pytest`.

**Done when** the other skills can find the tracker and the docs.

### Phase 1 — Settle the architecture *(done 2026-10-03)*
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
   - `seasonality` (measures recurring-factor effects from 3–4 years of history)
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

### Phase 2c — Explorer *(after Phase 2 metrics are split; alongside 2b)*
`to-spec` → `to-tickets` → `tdd` for the Explorer page (ARCHITECTURE §6.13, ADR-0009): reusable chart and table components first, then the explorer with comparisons and breakdowns, then saved views that reports and scheduled jobs can use.

**Done when** the owner can answer "how did Tuesday afternoons change for each barber since the price rise, compared with last year?" in the dashboard without asking Claude, and save it as a view.

### Phase 2b — Scheduled reports and delivery *(right after the Phase 2 framework; can start before all analyses exist)*
`to-spec` → `to-tickets` → `tdd`, after the channel questions below are answered:
1. **Notifications + Telegram adapter:** recipients, subscriptions, deliveries; `insights notify test` sends a test message.
2. **Scheduler:** `jobs`, `job_runs`, `insights jobs tick|run|list`, the launchd agent (`insights jobs install`), *Run now* in the dashboard, MCP tools.
3. **First jobs:** `data_watch` and `sheet_sync` (useful immediately), then `daily_digest`, then `weekly_review`.
4. *(Deferred.)* `monthly_review` once the Reports module exists; email as the second channel for it.

**Done when** the owner gets the daily digest in Telegram every morning without doing anything, sees each run in *Data & sync*, and gets an alert when data is older than the agreed limit.

### Phase 6 — Automation and new data *(blocked or optional)*
- **Altegio REST adapter:** lets the scheduled jobs fetch new data by themselves. Blocked until Altegio issues a working partner token (ADR-0002).
- **Factor feeds:** whichever ones Phase 4 recommended.
- **Finance module:** product sales, costs, payroll, if Altegio access allows.

### Every month
Run `barberis-goals-refresh`. Until Phase 2 lands, it saves a measurement and reports from goals. After that, it runs all analyses and compares them with the baseline and the previous run. Record new Context while doing it.

## Decided in the Phase 1 grilling (2026-10-03)
Owner-only, local-first for now; client retention is the first goal; analyses are built in the order in Phase 2; daily digest is deferred; Telegram uses a separate bot; no local retention rule for contact data; Windows stay whole ISO weeks. Details are in `ARCHITECTURE.md`, `CONTEXT.md` and the ADRs.

## TODO (blocked or later)
- **Profitability** per service and per barber (needs costs and payroll in the Finance module).
- **Front-desk vs online conversion** (Altegio gives no funnel, only `online_share`).
- **Capacity planning** for next quarter (needs forecasts).
- **Daily digest** job (deferred; only weekly reports for now).
- **Monthly review** job and report (deferred; the window rule is in ARCHITECTURE §6.4).
- **Date-range Windows** (the owner's 15th–14th month), if the weekly month proves too coarse.
- **Segment-scoped Factors**.
- **Hosting**: needs authentication and its own ADR.

## Open questions
1. **Research (Phase 4):** holidays and the run-up to them, migration and mobilisation (a proxy), air-raid alerts (low priority), competition (unsure).
