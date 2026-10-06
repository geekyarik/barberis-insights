# Win-back offers

Two offers, decided on 2026-10-06 from the shop's own visit history and its finances. They replace the first guesses (`pct10`, `pct15`, `free_addon`), which were a hand-written rule table with no analysis behind it.

## The offers

| Offer | Code | Who gets it | What it is |
|---|---|---|---|
| **Call** | `call_only` | Regulars (3+ visits) up to 30 days past their own overdue line, and clients with two visits | A personal call that proposes a concrete time with their usual barber. No discount. |
| **Book now** | `book_now` | Regulars more than 30 days past their line; lapsed regulars (180 to 365 days silent); first-time clients 41 to 120 days after their first visit | **15% off if the client books during the call**, with the admin, on a quiet slot, valid 14 days. |

Everyone else (one-time clients older than 120 days, lapsed clients with two visits, regulars silent over a year) gets **no offer**: their chance of returning is too low for a discount to pay back, and the call list would be too long to work. As of 2026-10-06 that is about 2 400 + 590 + 1 180 clients; the offer reaches 60 + 170 + 175 + 59 = about 460.

## Why these groups (our visit history, 28 000 visits)

- Regulars' chance of coming back within 90 days with no contact falls with the days past their line: 47% (0 to 14 days), 36% (15 to 30), 27% (31 to 60), 18% (61 to 90), 13% (91 to 150). Early on half return anyway, so a discount is wasted; later they need a reason.
- 47% of first-time clients never return. Those whose second visit comes within 60 days become regulars (4+ visits in a year) 68 to 69% of the time; after 120 days only 25%. The typical second visit is on day 42.
- The shop is emptiest on Monday (42% busy), Sunday (54%), Wednesday (55%) and Tuesday (58%), against Saturday 69%. Restricting the discount to quiet slots makes it nearly free.

## Why 15%

Source: the shop's monthly financials, January to September 2026 (8 closed months, 4 402 services). Average service ₴854; the shop keeps ₴443 of it (51.9%, steady all year, so barbers earn about 48%); cost per service ₴265; profit ₴178 (20.8% of price). Rent and utilities are ₴71 per service; the rest (cash and external costs, ₴190 per service) is treated as variable, which is deliberately cautious. So one extra full-price visit adds about ₴253 to the shop.

**Barbers are paid a percentage of the full price, discount or not** (confirmed 2026-10-06; they earn 40 to 50% of it). The shop therefore pays the whole discount: at 15% that is ₴128 on every discounted visit, which cuts a new visit's contribution from ₴253 to about ₴126. A booking that would have happened anyway is a pure ₴128 loss. The offer pays while the share `a` of bookings that would have happened anyway stays below `1 − d × 854 / 253`:

| Discount | Safe while the windfall share is below | Per discounted booking: gain if new / loss if windfall |
|---|---|---|
| 10% | 66% | +₴168 / −₴85 |
| 12% | 59% | +₴150 / −₴102 |
| **15%** | **49%** | **+₴126 / −₴128** |
| 20% | 33% | +₴82 / −₴171 |

(If the barbers were paid on the discounted price the safe share at 15% would be 74%; see the note below.)

The windfall share is small because the discount only applies when the client books during the call: only about 13% of first-timers still away at day 30 return on their own in the next 14 days (9% at day 45, 5% at day 60), and 4 to 7% of late-overdue regulars do. At 15% the offer stays profitable unless fewer than about half of the bookings are genuinely new, which for these groups means a call conversion below roughly 10 to 20%. Above 15% the margin is too thin, so **15% is the setting and the ceiling**, and it is the first thing to lower if the test shows that more than half of the bookings would have come anyway.

**Open question, the barbers' side.** Paying barbers on the full price makes the shop carry the discount. The alternative is to pay barbers on the discounted price for these visits: they would earn about 6 to 7% less on each of them (40 to 50% of the 15%), but they gain visits they would not otherwise have had, which is better for them than an empty chair, and the safe share for the shop rises from 49% to 74%. That is a pay decision for the owner and the barbers, not a data one; until it is made, the table above is the rule.

Other assumptions to check: figures are shop averages, so a trainee's cheaper visit has a thinner margin than an expert's; "cash" and "external" costs do not shrink when a visit is added.

## Why lapsed regulars stop at a year

Regulars' chance of returning on their own within 90 days falls with the silence: 10% (180 to 240 days), 8% (240 to 300), 6% (300 to 365), 4% (365 to 540), 1.5% (540 to 720) and 1.3% beyond. Calling the 510 regulars silent 180 to 720 days is too many calls for a few visits, so the offer stops at 365 days: 175 clients (74 + 59 + 42), who have spent ₴1.4M with the shop between them. Raise `INSIGHTS_BOOK_NOW_LAPSED_MAX_DAYS` if the call team has capacity.

## How it is measured

Each offer goes through the existing A/B arms. Record the outcome in the call sheet; win-back counts a return within 60 days of the call. Judge the call against the 32% natural 30-day return, and the booking offer against 13 to 36% (late-overdue regulars) and 29 to 41% (first-timers). Groups are small (60 and 170 regulars, and 59 first-timers right now), so expect several weeks before any difference is readable. Change the percentage with `INSIGHTS_BOOK_NOW_PCT` and update the label in `i18n/*.json` and the `offers` row.
