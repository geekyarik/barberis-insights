# Cases: when one opens, and what it offers

Status: rules as decided with the owner on 2026-10-06 (`clients/risk.py`, `clients/return_model.py`, `cases/service.py`). Numbers behind them come from the shop's own visit history (28 000 visits, 2022 to 2026).

## Client categories (segments)

Every client with at least one visit falls into exactly one. "Days" are days since the last completed visit. A client's **usual gap** is the median days between their own visits (known from three visits).

| Category | Rule |
|---|---|
| **active** | One visit up to 28 days ago; or within their usual gap |
| **switched** | Within the gap, but the last visit was with another barber than usual |
| **slipping** | Past the usual gap, not yet past the overdue line |
| **overdue** | At least 2 visits and silent past the **overdue line**, up to the lapsed line |
| **lapsed** | At least 2 visits and silent past the **lapsed line** |
| **one-time** | One visit, silent over 28 days |

- **Overdue line:** 1.5 × the usual gap, at least 45 days. A client with **two visits** has no reliable rhythm (one gap), so one fixed line: **60 days**.
- **Lapsed line:** 2 × the usual gap, but not before **120** and not after **365** days, and always after the overdue line.
- **First-timer line:** **28 days.** A first visit is the best moment to win someone back, and by day 28 about 30% of those who will ever return are already back; a call at day 28 reaches the rest while only about 14% would have come in the next two weeks anyway.

## Which clients get a case, and what it offers

A client has at most one active case, and never a second case for the same line and the same silence.

| Case type | Who | Offer |
|---|---|---|
| **overdue** | Two visits | Call, no discount (their yearly value does not carry a discount) |
| **overdue** | Three or more visits, up to 30 days past their line | Call, no discount |
| **overdue** | Three or more visits, more than 30 days past their line | 15% off if they book during the call |
| **lapsed** | Three or more visits, silent 365 days or less | 15% off if they book during the call |
| **first-timer** | One visit, 29 to 120 days ago | 15% off if they book during the call |

**Never gets a case:** a client with a "do not contact" mark, who refused data processing, who has an active flag (abroad, mobilised, moved, declined themselves, other), or who has no phone in Altegio.

**A client whose barber left** still gets a case by the same rules. The case is marked "barber left" and names a suggested barber: a current one of the same level, the least busy in the last 90 days.

## When a case opens

- **The first run** opens only the **highest-priority tenth** of the clients who qualify (at least 20): nobody can work hundreds of old cases. About 44 of 433 on 2026-10-06.
- **After that** a case opens only for a client who crossed their line within the last 14 days, the term of a case. About 4 new cases a day (the last 120 days: 1.8 overdue, 1.1 lapsed, 0.8 first-timers).

## Priority: chance to return × a year's value

`priority = chance × yearly value`, so the clients most likely to come back and worth most go first.

- **Chance:** the probability the client comes back within 90 days with no contact, learned from the shop's history by *visits so far* and *days silent* (a table recomputed whenever the profiles are rebuilt). Examples: a regular of 6 to 10 visits silent 45 to 74 days, 58%; one silent 105 to 179 days, 18%; a first-timer silent 45 to 74 days, 21%.
- **Yearly value:** the client's average check × their own visits a year (365 ÷ usual gap, at most 15). A first-timer is assumed to make 5 visits a year, which is what those who return do.
- It includes returns that would happen without a call, so it ranks who is likely to come after a call, not who a call changes most. The results page counts "came on their own" separately to show the size of that effect.

## What happens to a case

An administrator processes it once: *booked*, *rejected with a reason*, or *no answer*. A visit closes it as **visited**; a future booking only marks it "booking exists". Unprocessed for 14 days, it expires. Details in `ARCHITECTURE.md` §6.7 and ADR-0012.

## Still open (decided to skip for now)

- Clients who moved to another barber at the shop ("switched") or are only slightly past their rhythm ("slipping") get no case.
- Shop closures and the Context are not considered when a line is crossed.
