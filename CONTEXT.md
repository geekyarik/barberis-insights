# BARBERIS insights

A side tool that helps the owner and managers run the barbershop as a business. It combines facts from the CRM with the owner's knowledge of what was going on, so conclusions about clients, barbers and the business are correct.

## Sources of truth

**Facts**:
What happened, as recorded in the CRM (Altegio): appointments, visits, schedules, clients, services and prices.
_Avoid_: data (too vague), raw data

**Context**:
The owner's and managers' knowledge of what was going on and why: decisions, outside events, beliefs about cause and effect. It is the second source of truth next to Facts.
_Avoid_: notes, comments, metadata

**Factor**:
A dated, scoped piece of Context (days or weeks, never hours) that may affect the numbers, and may recur every year (its effect is then estimated from the shop's own history), either **external** (outside our control, e.g. a power outage, an air-raid alert, a holiday, a competitor opening) or **internal** (our decision, e.g. a price change, a new barber, a campaign).
_Avoid_: event (overloaded), cause, reason

**Treatment**:
How analysis handles a Factor: annotate (show only), exclude (remove the period), adjust (count only a share of scheduled time), control for it, or, for one client, suppress overdue.

**Lens**:
A named rule (which Factors, and how each is treated) that a calculation runs under. At run time it is resolved to a fixed list of Factors, and the run keeps that list. Two runs with the same Lens name but different resolved Factors are not comparable. Every number states its Lens.
_Avoid_: filter, view, adjustment

**Belief**:
A Factor's expected effect on the numbers (a direction, optionally a size range), as the owner sees it, before the data has been checked. It becomes supported, refuted or inconclusive through a Hypothesis; that verdict is read from the linked Hypotheses, never stored on the Factor.

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
The people who use this tool to run the business. 

**Admin**:
The person at the front desk who calls clients for win-back. They work the cases in this tool, with an Administrator login that opens only the Clients section.
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
The queryable copy of the metric values of one Analysis run (or manual snapshot, which is itself a run), for one Window, as of its last day. Goals compare against the latest Measurement. A Measurement is never written on its own.
_Avoid_: snapshot (in conversation)

**Analysis**:
A defined way to answer one business question for a window, a scope and a lens, e.g. "where did last period's clients go?" It produces a structured result.
_Avoid_: report, study

**Analysis run**:
One stored, unchangeable result of an analysis, for one window, scope and lens, at one point in time.
_Avoid_: snapshot, export

**Baseline**:
The analysis run or measurement a goal is set against, the "before" in every comparison.
_Avoid_: starting point (in docs), benchmark

**Comparison**:
What changed between two comparable analysis runs, metric by metric, judged better or worse by each metric's direction.
_Avoid_: diff, delta report

**Job**:
Work the tool does by itself on a cadence (daily, weekly, monthly), such as sending the daily digest.
_Avoid_: cron, task (a task is a person's work)

**Slot**:
One scheduled moment of a Job, a date and an hour on the shop's clock. Every missed Slot is processed, in order; a Slot whose data is incomplete is blocked until the data arrives.

**Weekly review**:
The Monday message to the owner: last week's figures against the week before and last year, overdue regulars and goals. Its figures are computed from the data when it is sent; nothing is stored as a report, and the dashboard shows the same facts live.
_Avoid_: report

**Digest**:
A short message of yesterday's or today's numbers, built from day-level facts. It is not an Analysis, is not stored as a Measurement, and does not feed Goals. A digest summarises.
_Avoid_: newsletter, notification

**Alert**:
A message sent because something needs attention now, such as data that is too old or a failed sync.
_Avoid_: warning, notification

**Channel**:
The way a message reaches a person: Telegram, email, and so on.

**Subscription**:
Who gets which message (the weekly review or an alert), through which channel.

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

**Do not contact**:
A client the shop must not call for win-back. It is a Fact held in Altegio (a tagged line in the client's description), so staff can set or clear it there; the tool also writes it when the admin marks a case that way.
_Avoid_: blacklist, opt-out

**Client flag**:
A reason someone who knows the client gives for not calling them (left the country, mobilised, moved, declined themselves, other), with a comment and an optional date to check again. A flagged client leaves the call list until the flag is lifted or its date passes. A flag stays in this tool only.
_Avoid_: blacklist, note

**Case**:
One possibly lost client, opened by the daily job when the client crossed a risk line (overdue, lapsed, or a first-timer who did not return), with a snapshot of what we knew that day. An administrator processes it once: booked, rejected with a reason, or no answer. It is open, booking exists, or closed (visited, rejected, no answer, expired), and one client has at most one active case.
_Avoid_: lead, ticket, task, win-back case

**Offer**:
What the administrator may give a client to come back, a call only, or 15% off if the client books during the call (docs/OFFERS.md).
_Avoid_: discount (an offer may be no discount), promo

**Won back**:
A client whose case closed as visited after an administrator had processed it. A client who visits before anyone called is "came on their own", and is not counted as won back.
_Avoid_: converted, recovered

