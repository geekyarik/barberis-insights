# Cases: when one opens, and what it offers

Status: rules as built on 2026-10-06 (`clients/risk.py`, `cases/service.py`). The owner has asked to adjust them; the open points at the end are the candidates.

## Client categories (segments)

Every client with at least one visit falls into exactly one. "Days" are days since the last completed visit. A client's **usual gap** is the median days between their own visits; their **overdue line** is `max(45, 1.5 × usual gap)`.

| Category | Rule | Opens a case? |
|---|---|---|
| **active** | One visit up to 45 days ago; or within their usual gap | No |
| **switched** | Within the gap, but the last visit was with another barber than usual | No |
| **slipping** | Past the usual gap, not yet past the overdue line | No |
| **overdue** | At least 2 visits, silent past the overdue line, up to 180 days | Yes |
| **lapsed** | At least 2 visits, silent over 180 days | Only some (below) |
| **one-time** | One visit, silent over 45 days | Only some (below) |

## When a case opens

The daily job (08:00) opens a case for a client in these cases, then gives it an offer. A client has at most one active case, and never a second case for the same line and the same silence (the last visit date identifies the silence).

| Case type | Who | Offer |
|---|---|---|
| **overdue** | Overdue, and **up to 30 days past their own line** | Call, no discount |
| **overdue** | Overdue, **more than 30 days past** their line | 15% off if they book during the call |
| **lapsed** | Lapsed **with at least 3 visits and silent 365 days or less** | 15% off if they book during the call |
| **first-timer** | One-time, **first visit 46 to 120 days ago** | 15% off if they book during the call |

**Never gets a case** (even in those categories): a client with a "do not contact" mark, who refused data processing, who has a flag (abroad, mobilised, moved, declined themselves, other) that has not ended, or who has no phone number in Altegio.

**Not reached by any rule today** (no offer, so no case): one-time clients whose first visit was over 120 days ago, lapsed clients with only 2 visits, and lapsed clients silent over a year.

## What happens to a case

An administrator processes it once: *booked*, *rejected with a reason*, or *no answer*. A visit closes it as **visited**; a future booking only marks it "booking exists". Unprocessed for 14 days, it expires. Details in `ARCHITECTURE.md` §6.7 and ADR-0012.

## Size today (2026-10-06)

About 462 cases would open on the first run: 60 overdue (call), 170 overdue (15%), 175 lapsed, 59 first-timers, minus 2 left out. In steady state about 4 new cases a day (1.8 overdue, 1.1 lapsed, 0.8 first-timers, per the last 120 days).

## Open points (candidates for change)

1. **Clients of a barber who left.** A client's "usual barber" may be someone who no longer works here (several of the top overdue clients are). Their silence has a different cause and needs a different script (offer another barber). Today they are treated like any other.
2. **Two-visit clients are "overdue".** The usual gap comes from a single interval, so it is unreliable; the same client is not treated as a regular (3+ visits) for lapsed.
3. **The lapsed line is a flat 180 days.** A client who normally comes every 4 to 5 months is only slightly late at day 181.
4. **First-timers start at day 46.** The data says the second visit usually comes around day 42, and the chance of returning on their own drops quickly; an earlier nudge might work better, and day 46 to 120 leaves a long tail.
5. **Switched and slipping clients get no case.** A client who moved to another barber at the shop, or who is just past their rhythm, is invisible.
6. **No value floor.** A client with two small visits gets the same case as one who spent ₴38 000; only the order differs.
7. **No account of shop closures or the Context.** Holidays, closures and the mobilisation waves are not considered when a line is crossed.
8. **The first run opens about 460 cases at once**, which the administrator cannot work in 14 days; the rest expire unprocessed.
