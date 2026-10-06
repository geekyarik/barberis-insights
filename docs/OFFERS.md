# Win-back offers

Two offers, decided on 2026-10-06 from the shop's own visit history and its finances. They replace the first guesses (`pct10`, `pct15`, `free_addon`), which were a hand-written rule table with no analysis behind it.

## The offers

| Offer | Code | Who gets it | What it is |
|---|---|---|---|
| **Call** | `call_only` | Regulars (3+ visits) up to 30 days past their own overdue line | A personal call that proposes a concrete time with their usual barber. No discount. |
| **Book now** | `book_now` | Regulars more than 30 days past their line; lapsed regulars (180 to 720 days silent); first-time clients 46 to 120 days after their first visit | **15% off if the client books during the call**, with the admin, on a quiet slot, valid 14 days. |

Everyone else (one-time clients older than 120 days, lapsed clients with two visits, regulars silent over two years) gets **no offer**: their chance of returning is too low for a discount to pay back. As of 2026-10-06 that is about 2 400 + 590 + 850 clients.

## Why these groups (our visit history, 28 000 visits)

- Regulars' chance of coming back within 90 days with no contact falls with the days past their line: 47% (0 to 14 days), 36% (15 to 30), 27% (31 to 60), 18% (61 to 90), 13% (91 to 150). Early on half return anyway, so a discount is wasted; later they need a reason.
- 47% of first-time clients never return. Those whose second visit comes within 60 days become regulars (4+ visits in a year) 68 to 69% of the time; after 120 days only 25%. The typical second visit is on day 42.
- The shop is emptiest on Monday (42% busy), Sunday (54%), Wednesday (55%) and Tuesday (58%), against Saturday 69%. Restricting the discount to quiet slots makes it nearly free.

## Why 15%

Source: the shop's monthly financials, January to September 2026 (8 closed months, 4 402 services). The 2026-10-06 figures: average service ₴854, shop income ₴443 (51.9%, steady at 51 to 52% all year, so barbers get about 48% of the price), cost per service ₴265, profit ₴178 (20.8% of price). Rent and utilities are ₴71 per service; the rest (cash and external costs, ₴190 per service) is treated as variable, which is deliberately cautious. So one extra full-price visit adds about ₴253 to the shop.

A discount `d` costs `d × ₴443` on every booking, and gains `₴253` for each booking that would not have happened otherwise. Let `a` be the share of bookings that would have happened anyway. The offer pays when `a < 1 − d × 443 / 253`:

| Discount | Safe while windfall share is below (barbers paid on the discounted price) | If barbers are paid on the full price | Counting all costs, fully loaded |
|---|---|---|---|
| 10% | 82% | 66% | 75% |
| **15%** | **74%** | **49%** | **63%** |
| 20% | 65% | 33% | 50% |
| 25% | 56% | 16% | 38% |

The expected windfall share is small, because the discount only applies when the client books during the call: only about 13% of first-timers still away at day 30 return on their own in the next 14 days (9% at day 45, 5% at day 60), and 4 to 7% of late-overdue regulars do in 14 days. 15% stays profitable even if the call converts only a fraction of clients and even in the worst pay case. 20% does not hold in the worst case, so **15% is the setting and 20% the ceiling**.

Assumptions to check: barbers are paid a percentage of the price actually charged (if they are paid on the full price, the shop absorbs the whole discount, the middle column); the figures are shop averages, so a trainee's cheaper visit has a thinner margin than an expert's; "cash" and "external" costs do not shrink when a visit is added.

## How it is measured

Each offer goes through the existing A/B arms. Record the outcome in the call sheet; win-back counts a return within 60 days of the call. Judge the call against the 32% natural 30-day return, and the booking offer against 13 to 36% (late-overdue regulars) and 29 to 41% (first-timers). Groups are small (60 and 170 regulars, and 59 first-timers right now), so expect several weeks before any difference is readable. Change the percentage with `INSIGHTS_BOOK_NOW_PCT` and update the label in `i18n/*.json` and the `offers` row.
