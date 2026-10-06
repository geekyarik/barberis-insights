# barberis-insights — Design

The design for the dashboard. It follows from the purpose in [`ARCHITECTURE.md`](ARCHITECTURE.md) §1 and uses the rules of the `ui-ux-pro-max` skill (`.claude/skills/ui-ux-pro-max`). Status: **adopted 2026-10-06**; the implementation is in `src/barberis_insights/web/`.

## 1. What the product is for

A side tool for the **owner and managers** of a barbershop. Every week they ask the same questions, and each page exists to answer one of them:

| Question | Page |
|---|---|
| Is the shop healthy, and is anything wrong with the data? | **Overview** |
| How is each barber doing, and why? | **Barber** (one per barber) |
| Who is ahead, who is behind, by how much? | **Team** |
| Are we hitting our goals? | **Goals** |
| Which clients should we call, and did calling work? | **Clients at risk**, **Win-back**, **Client** |
| What was going on that the numbers do not show? | **Context** |
| Is the data fresh, and what ran? | **Data & sync** |

**Main priority: the client** (do they come, return and stay). Retention and overdue regulars therefore get space on the Overview and on every barber page, not a hidden tab.

Users and context: the owner, mostly at a desk (a wide screen, a few minutes, a weekly rhythm), sometimes on a phone after a Telegram message. Ukrainian first, English second. Read-mostly: the few writes are goals, context, case approval and a few buttons.

## 2. Principles

1. **Answer first, detail on demand.** Each page opens with the answer (a number with its change and verdict), then the evidence (a chart), then the table behind it.
2. **Every number carries its comparison** (last week, the same week last year, the team, the goal) and a verdict in words and a sign, never colour alone.
3. **Say how old and how complete the data is**, on every page that shows it.
4. **Show context on the chart**: price rises, holidays and closures are marked on the time axis, because facts without context mislead (ARCHITECTURE §2).
5. **Charts are an aid to the table**: each chart has a text title and description, values on hover and focus, and the table is one click away.
6. **Dense but calm** (density 7 of 10): small multiples and inline bars instead of big decorative charts; one accent colour; no decoration.

## 3. Visual language

Style: **Minimalism / Swiss** (the skill's pick for dashboards): a grid, white space, high contrast, sans-serif, one accent. Light first, with a dark theme.

**Colour tokens** (all text pairs checked at 4.5:1 or better in both themes; `web/templates/base.html` is the source):

| Role | Light | Use |
|---|---|---|
| Ink / ink-2 / ink-3 | `#0f172a` / `#334155` / `#556070` | Text, secondary text, labels |
| Surface / page / rule | `#ffffff` / `#f5f7fa` / `#dfe4ec` | Cards, background, borders |
| Primary | `#1e40af` | Links, the current series, selection, focus ring |
| Good / bad / warn | `#157a3c` / `#b42318` / `#9a5b00` | Verdicts (always with a sign or a word) |
| Series (lines, at most 6) | blue `#0b5cad`, vermilion `#c24f00`, purple `#7a3e9d`, green `#00806a`, gold `#946f00`, magenta `#c2185b` | Different barbers on one chart; each line also has a direct end label |
| Composition fills | blue = healthy / returning, light blue `#8fb8e0` = in between / from other barbers, orange = at risk / lost, grey = gone, pale grey = one-time, purple = new / switched | Stacked bars; segments separated by a 2 px gap |
| Intensity ramp | teal, five steps `#e1f1ee` to `#0b5a4d` | Busy share and return rates only; values printed in each cell |
| Comparison | grey dashed `#7b8798` | Last year |
| Context marker | amber `#b45309` | Factors on a time axis |

**Colour rules** (data-analysis practice, checked 2026-10-06): colour carries one meaning per role and a colour is never reused for another role; categories are limited to six hues with large gaps (an Okabe-Ito-style, colour-blind-safe set), and identity is also given by a direct label; part-to-whole uses meaning-ordered colours rather than a rainbow; intensity uses one hue in lightness steps, a different hue from the accent so a heat cell is never mistaken for a series; green and red appear only for better/worse and always with a sign or a word; ranked bars of barbers use one colour because the name is on the row. Every text-on-fill pair is at least 4.5:1 in both themes.

Typography: the **system font stack** (the tool is local-first and works offline, so no web fonts; the skill's suggested Fira pairing needs a download). Numbers use tabular figures. Sizes: labels 12, body and tables 14 and 13, page title 24, tile numbers 28. Nothing under 12.

Spacing: 4, 8, 12, 16, 24, 32. Radius: 6 (cards) and 4 (controls). Motion: none beyond a 150 ms colour change on hover, and none under `prefers-reduced-motion`.

## 4. Visual vocabulary (data analysis)

| Element | Used for | Rules |
|---|---|---|
| **Stat tile** | Headline numbers | Label, value, change chip (▲▼ with a signed value and a verdict word), the comparison in words, a 26-week sparkline |
| **Sparkline** | Trend inside a tile or a table row | The last point is marked; a text value beside it |
| **Line chart** | Weekly trends (revenue, busy share) | This year solid, last year dashed, direct labels at the line ends, no more than 6 series, context markers on the axis, a table fallback |
| **Ranked bars** | Barbers on one metric | Sorted by value, the value printed on the bar, a marker for the team figure |
| **Diverging bars** | Difference from the team or from last year | Centred on zero, signed values, direction in words |
| **100% stacked bar** | Composition: client segments, retention outcomes (stayed, switched, lost), client sources | Direct labels with percentages; a single bar, because the skill advises against pies above five categories |
| **Stacked columns** | Weekly clients by type (new, from another barber, returning) | Direct legend, values on hover |
| **Heat grid** | Busy share by weekday and hour, cohort matrix | Values printed in every cell, a numeric legend, text colour chosen for contrast |
| **Bullet bar** | Goal progress | Start, current, target and today's expected position, with the numbers beside the bar and a status word |
| **Data table** | The evidence | Sticky header, numbers right-aligned in tabular figures, inline bars or sparklines in cells, `scope` on headers, a card layout on a phone |
| **Timeline** | Context factors | Periods as bars on a date axis, recurring ones repeated, the run-up shaded |
| **Chips** | Status | A dot and a word; never colour alone |
| **Banner** | Data age, blocked jobs | At the top of the page, with the action to take |

## 5. Layout and navigation

Desktop: a left rail (grouped: *Overview*, *Barbers*, *Analyze*, *Clients*, *Plan*, *System*) and a content column on a 12-column grid, with a page header that always shows the period, the data age and the active lens. Phone: a top bar with a menu button, a single column, tables as cards, charts at full width. Skip link, visible focus, `aria-current` on the active item.

```
Overview
┌──────────┬──────────────────────────────────────────────────────────┐
│ rail     │ Overview            period · data fresh 0 d · lens raw   │
│          │ ┌ attention banner (data age, review status) ──────────┐ │
│ Overview │ ├ stat ─ stat ─ stat ─ stat ─ stat ─ stat (sparklines) ─┤ │
│ Barbers  │ │ revenue by week, this year / last year, context marks │ │
│  ...     │ ├ barber table: bars + sparklines ┬ client health 100% bar┤ │
│ Analyze  │ ├ weekday × barber heat grid      ┴ goals as bullet bars │ │
│ Clients  │ └ to do this week: calls, blocked jobs ─────────────────┘ │
└──────────┴──────────────────────────────────────────────────────────┘
```

## 6. Deviations from the skill, and why

- Its recommended **pattern** ("Enterprise Gateway": a marketing site) does not fit an internal dashboard and was discarded; nothing was persisted from it.
- Its **font pairing** (Fira) needs a network download; the tool is local-first, so a system stack is used.
- It found **no chart** for a cohort triangle; the heat-grid rules (printed values, numeric legend) were applied as the closest guidance, and this is a fallback, not a database match.
- It prefers **pies** for part-to-whole up to five categories and warns against more; the 100% stacked bar is used throughout.
