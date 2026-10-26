# Rework — from insights sidecar to the shop's operating system

> Status: **option A accepted** (2026-10-26): rebuild the insights tool cleanly on top of Altegio, keeping option B (own CRM modules) possible. The domain model is the first piece of work (Step 2 is pulled forward and runs together with Step 1's process walk-through). Whether to build any CRM module is still decided at the Step 1 gate.
> Vocabulary: [`CONTEXT.md`](../CONTEXT.md). Past decisions: [`docs/adr/`](adr/).

## 1. What we are actually deciding

Two different ideas hide in "rework from scratch":

| | A. Rebuild the insights tool cleanly | B. Build our own CRM |
|---|---|---|
| Altegio | stays the system staff work in | replaced |
| Risk | low | high: booking, payments, payroll, SMS, online booking widget, fiscal rules, staff retraining |
| Value | decisions, win-back, goals | everything, but only after parity |
| Time to first value | weeks | many months |

**Recommendation: do A now, designed so B is possible later (strangler pattern).**
A CRM earns its place only when Altegio blocks something we need (for example: no way to write a field we need, an API limit, cost, or lock-in). We do not know that yet. We find out by building a thin operational layer on top of Altegio first and logging every place Altegio hurts. If the log shows a few painful, specific gaps, we fill them. If it shows Altegio is fundamentally the wrong tool, we have the domain model, the data and the workflows ready to migrate onto our own system, with no big-bang cutover.

## 2. What we keep (the experience we gained)

Keep as **knowledge**, whatever happens to the code:

- The domain language in `CONTEXT.md`: Facts vs Context, Factor, Lens, Window, Visit vs Appointment, Busy share. It is the most valuable thing in the repo.
- ADRs 0001, 0005, 0006, 0007, 0008, 0010, 0011, 0012: Altegio owns facts; context is a second source; private data stays out of git; analyses are code and results are stored runs; English code with a Ukrainian UI; narrow write-back; no stored reports; win-back cases worked in the app.
- The data: 2022 onward appointments, shifts, clients, the Baseline of 2026-09-27, the fixtures behind the baseline regression test.
- The lessons: connector-file import was fragile and we moved to the REST API (ADR-0002 to 0013); a single-user local SQLite app hit its limit once the admin needed a login (ADR-0003 and 0004 are now under pressure); `web/app.py` at 900 lines is a sign that routes, view-models and logic got mixed.

Treat as **reference, not template**: the code. Port behavior with tests, not by copy-paste.

## 3. Principles for the rewrite

1. **Walking skeleton first.** One thin slice end to end (Altegio sync → store → one screen a real person uses) before any breadth.
2. **Event-sourced facts, derived everything else.** Raw Altegio payloads are stored immutably; the normalized model is rebuilt from them. A bad parser can then never lose data.
3. **Characterization tests before porting.** The existing numbers (baseline snapshot, risk rules, cases) become golden tests. The new system must reproduce them or explain the difference in writing.
4. **Domain core has no framework imports.** Metrics, analyses, risk and case rules are pure functions over typed data. Web, jobs, Telegram and MCP are adapters.
5. **Every user gets one job-shaped screen**, not a dashboard: owner (decisions), manager (barbers), admin (today's calls). Design from jobs-to-be-done, not from available data.
6. **Ship weekly, behind the existing tool.** The old app keeps running until the new one is better for the admin's daily work.
7. **Privacy by design.** Client names and phones are personal data: encrypted at rest, access logged, minimal fields, per-role visibility, retention rules.

## 4. Steps

Each step has an output and a "done when". Stop and review at every gate.

### Step 0 — Freeze and learn *(this week)*
- Commit and push the pending UI work; tag the result `v0-insights`.
- Write `docs/RETROSPECTIVE.md`: what worked, what hurt, what we would never repeat, with evidence from commits and ADRs.
- Record the real baseline numbers the new system must match.

**Done when** the old system is a tagged, reproducible reference.

### Step 1 — Discovery and the decision gate *(1 to 2 weeks)*
- Interview the owner, managers, admin and two or three barbers (30 minutes each). Ask for the last week's actual workflow, not wishes.
- Map the shop's processes: booking, reminders, no-show handling, win-back, schedule building, payroll, pricing, stock, onboarding a barber.
- For each process: who does it, in which tool, how long, what goes wrong, what it costs.
- Audit Altegio: which API endpoints exist, which fields are writable, rate limits, webhooks, cost per month, export rights.
- Score pains by (money or time lost) × (frequency).

**Output:** `docs/DISCOVERY.md` and a ranked pain list. **Gate:** decide A-only, A plus selected CRM modules, or B. Record as an ADR.

### Step 2 — Target model *(1 week)*
- Run `grill-with-docs` on the new scope; extend `CONTEXT.md`.
- Draw bounded contexts: Ingestion, Clients, Scheduling, Performance, Retention (cases), Context (factors and hypotheses), Notifications, Identity. Fix who owns which table.
- Define the canonical data model and the events: `AppointmentBooked`, `VisitCompleted`, `NoShow`, `ClientMarkedDoNotContact`, and so on.
- Decide the stack by constraints, not taste: multi-user with roles, small team, one operator. Default proposal: Python + FastAPI or Django, Postgres, server-rendered UI with light interactivity, a job queue, deployed on one small VPS or a managed platform, with backups and monitoring from day one. SQLite single-user is retired (amend ADR-0003).

**Done when** `ARCHITECTURE.md` v2 and the stack ADR are accepted.

### Step 3 — Foundation and walking skeleton *(2 weeks)*
- Repo layout, CI (lint, types, tests), migrations, secrets handling, structured logging, error tracking, automated backups with a tested restore.
- Auth with roles (owner, manager, admin) and an audit log.
- Raw ingestion from Altegio's REST API into an immutable store; normalized tables rebuilt from it; idempotent and resumable sync with a visible sync status.
- One real screen: **Today for the admin** (who to call, with context), end to end.

**Done when** the admin can do one real day of calling in the new system.

### Step 4 — Port the core with golden tests *(3 to 4 weeks)*
In this order: metrics → risk rules → cases → analyses and runs → goals → factors, lenses and hypotheses. For each, write the characterization test against the old output first, then the implementation. Differences are either bugs in the old system (documented) or bugs in the new one (fixed).

**Done when** the Baseline 2026-09-27 reproduces and the old and new case lists agree on the same day.

### Step 5 — Role-based product *(3 weeks)*
- **Admin:** daily call list, one-click outcome capture, scripts and offers, do-not-contact handling.
- **Manager:** barber book, schedule load, no-show and cancellation views.
- **Owner:** weekly review, goals vs baseline, factor effects, what to do this week.
- Telegram digests carry over. The MCP server is rebuilt as a thin adapter over the same services, so Claude remains an analyst on top.

**Done when** the three roles use the new system daily and the old one is read-only.

### Step 6 — Cut over and retire *(1 week)*
Parallel run for two weeks with daily diff checks, then switch off the old app and archive it with its data. Update the docs and ADRs.

### Step 7 — Earn the CRM modules *(ongoing, one at a time)*
Only the modules the pain list justifies, each as its own small project with a spec and tickets. Likely candidates, in order of expected value: client communication (reminders, win-back messages, review requests), waitlist and rebooking, online booking tuned for our no-show data, then scheduling optimization. Each module runs next to Altegio first and takes over only after it measurably beats it. Payments, fiscal rules and payroll are last, and only if Altegio itself is the blocker.

## 5. Cross-cutting tracks (from Step 3 onward)

| Track | Practice |
|---|---|
| Quality | Tests before porting; property tests for metrics; a golden-data suite; types in CI |
| Observability | Sync freshness, job success, data-quality checks (gaps, duplicates, impossible values) shown in the app |
| Security and privacy | Roles, audit log, encrypted backups, no private data in git (ADR-0006), data-export and deletion procedure |
| Documentation | ADR for every hard-to-reverse decision; `CONTEXT.md` stays current; the plan below is updated at every gate |
| Delivery | Small tickets, trunk-based, weekly demo to the owner |

## 6. Risks

| Risk | Mitigation |
|---|---|
| Rewrite never reaches parity | Walking skeleton plus golden tests; the old tool stays alive until parity |
| Building a CRM nobody needed | Step 1 gate and the module-by-module rule in Step 7 |
| Altegio API changes or limits | Raw immutable store; the sync adapter is the only code that knows the API |
| Staff do not adopt it | Design with the admin and manager from Step 1; measure the daily use |
| Personal data leak | Step 3 security basics; minimal data in the UI and logs |
| One-person bus factor | ADRs, tests, runbook, automated deployment |

## 7. Open questions for the owner

1. Is leaving Altegio on the table in a one- to two-year view, or is it fixed?
2. Who are the real daily users, and who decides what to buy and build?
3. What does Altegio cost per month, and what does it block today?
4. Where should the system run (own machine, VPS, managed cloud) and who maintains it?
5. What is the budget for time and money, and the horizon for the first visible win?
