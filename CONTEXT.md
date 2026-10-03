# BARBERIS insights

A side tool that helps the owner and managers run the barbershop as a business. It combines facts from the CRM with the owner's knowledge of what was going on, so conclusions about clients, barbers and the business are correct.

## Sources of truth

**Facts**:
What happened, as recorded in the CRM (Altegio): appointments, visits, schedules, clients, services and prices.
_Avoid_: data (too vague), raw data

**Context**:
The owner's and managers' knowledge of what was going on and why: decisions, outside events, beliefs about cause and effect. It is the second source of truth next to Facts.
_Avoid_: notes, comments, metadata

**Factor** _(proposed)_:
A dated, scoped piece of Context that may affect the numbers, either **external** (outside our control, e.g. a power outage, an air-raid alert, a holiday, a competitor opening) or **internal** (our decision, e.g. a price change, a new barber, a campaign).
_Avoid_: event (overloaded), cause, reason

**Treatment** _(proposed)_:
How analysis handles a Factor: annotate, exclude, adjust, or control for.

**Lens** _(proposed)_:
A named set of Factor treatments that a calculation runs under. Every number states its Lens.
_Avoid_: filter, view, adjustment

**Belief** _(proposed)_:
A Factor's expected effect on the numbers, as the owner sees it, before the data has been checked. It becomes supported, refuted or inconclusive through a Hypothesis.

## People and places

**Shop**:
The barbershop location as a whole.
_Avoid_: salon, company, location (Altegio's word)

**Barber**:
A person who serves clients and has their own schedule.
_Avoid_: master, team member, staff (Altegio's words)

**Tier**:
A barber's level, which sets their prices: Експерт, Старший майстер, Майстер, trainee.
_Avoid_: rank, category

**Team**:
The barbers being tracked, taken together.

**Owner** / **Manager**:
The people who use this tool to run the business. The owner also approves win-back cases.

**Admin**:
The person at the front desk who calls clients for win-back. They work from the call sheet, not this tool.
_Avoid_: receptionist, operator

**Client**:
A person who books and visits the shop. The main priority of the business.
_Avoid_: customer, guest

## Visits and time

**Appointment**:
A booked slot for one client with one barber at a time. It may or may not happen.
_Avoid_: booking, record (Altegio's word)

**Visit**:
An appointment where the client came and was served. Only visits produce revenue.
_Avoid_: arrival, completed appointment

**No-show**:
An appointment where the client did not come.

**Shift**:
A barber's scheduled working time on one day, possibly split by breaks.
_Avoid_: schedule (for one day), slot

**Window**:
A whole number of ISO weeks over which a number is calculated.
_Avoid_: period (too loose), range

## Measuring

**Metric**:
A defined way to calculate one number for a barber, the team or the shop over a Window, e.g. busy share or revenue per scheduled hour.
_Avoid_: KPI, stat

**Busy share**:
The part of scheduled shift time that is booked.
_Avoid_: utilization, occupancy, load

**Measurement**:
The stored values of all metrics for one Window, as of its last day. Goals compare against the latest Measurement.
_Avoid_: snapshot (in conversation), report

**Analysis**:
A defined way to answer one business question for a window, a scope and a lens, e.g. "where did last period's clients go?" It produces a structured result.
_Avoid_: report (a report combines analyses), study

**Analysis run**:
One stored, unchangeable result of an analysis, for one window, scope and lens, at one point in time.
_Avoid_: snapshot, export

**Baseline**:
The analysis run or measurement a goal is set against, the "before" in every comparison.
_Avoid_: starting point (in docs), benchmark

**Comparison**:
What changed between two comparable analysis runs, metric by metric, judged better or worse by each metric's direction.
_Avoid_: diff, delta report

**Report**:
A readable page made of analysis runs, goals and context, e.g. a barber book or the monthly review.
_Avoid_: dashboard (that's the app), analysis

**Revenue**:
The service price after discounts on visits. It is not cash received, because payments are not recorded in the CRM.
_Avoid_: income, takings, sales

## Goals and experiments

**Goal**:
A target value of a metric for a barber or the team, with a start value and a due date.
_Avoid_: KPI target, objective

**Hypothesis**:
A claim that a change or Factor moved a metric, tested against the Facts.
_Avoid_: experiment (that's the method), assumption

**Playbook tip**:
A routine the team agrees to follow, tagged with the barbers it applies to.
_Avoid_: rule, policy

## Clients and win-back

**Regular**:
A client with at least three visits to the same barber.

**Usual gap**:
The median number of days between a client's visits.
_Avoid_: cadence, frequency

**Segment**:
Where a client stands now, from their visit history: active, slipping, overdue, lapsed, one-time, or switched.

**Overdue**:
Silent longer than max(45 days, 1.5 × the client's usual gap), and up to 180 days.
_Avoid_: at risk (too vague), churned

**Lapsed**:
Silent for over 180 days.
_Avoid_: lost, churned

**One-time**:
Came once and not since, for longer than 45 days.

**Switched**:
Still visits the shop, but no longer with their usual barber.

**Win-back case**:
One attempt to bring one client back. A person proposes and approves it, the admin calls, and the client's return is recorded.
_Avoid_: lead, ticket, task

**Offer**:
What the admin may give a client to come back, e.g. a call only, 10% off, or a free add-on.
_Avoid_: discount (an offer may be no discount), promo

**Won back**:
A contacted client who completed a visit within the win-back window after the call.
_Avoid_: converted, recovered

**Call sheet**:
The shared Google Sheet where the admin sees approved cases and records call outcomes.
_Avoid_: CRM, call list (that's the sheet tab)
