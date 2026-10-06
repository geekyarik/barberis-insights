# No stored reports

The app shows only data that comes from the CRM and is stored in the local database. A "report" (a frozen page made of analysis runs, goals and Context) was a second copy of those facts that could drift from them, so it is removed.

- The dashboard pages are live views: Overview, Barber, Team, Explore, Goals, Clients at risk, Win-back, Context.
- The weekly Telegram message is computed from the data when it is sent. What went out is recorded as a delivery keyed by week (`weekly:<ISO week>`) and the job run's own record; there is no `report_runs` table.
- Analyses remain stored, immutable runs (ADR-0007): goals and comparisons depend on them. They are not reports.
- The barber book and team comparison builders, the HTML export and the Reports tab are gone. The Barber and Team pages replace them.
- Migration `a1c8e5d3b9f4` drops `report_runs` and renames existing delivery keys so a week that was already sent is not sent again.
