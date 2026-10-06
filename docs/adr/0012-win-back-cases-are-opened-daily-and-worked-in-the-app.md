# Win-back cases are opened daily and worked in the app

Win-back used to be: a person proposes cases from a list, the owner approves them, a Google Sheet carries them to the front-desk administrator, and attribution reads the outcomes back. That was a hand-run pipeline with a second source of truth (the sheet).

Now a daily job opens a **case** for each client who newly crossed a risk line, with a snapshot of the data of that day, and the administrator works it in the dashboard. We chose this because the line crossing is a fact the data already knows, so a person selecting and approving adds work without adding judgement, and because a case with its own table (`risk_cases`) keeps the client record free of win-back state.

- The dashboard gets users and roles (super-admin, administrator), because the administrator must reach it and see only the Clients section; it is going to be hosted, so it is behind a login.
- A case closes as visited only when the client really came; a future booking only marks it `booking_exists`. A booking the CRM no longer shows (Altegio drops cancelled appointments from its list) sends the case back to open.
- An unprocessed case expires after 14 days; a closed case is not reopened for the same line and silence; one attempt is made.
- The owner's approval step, the Google Sheet, the A/B arms and the hold lifecycle are removed. Reasons that describe the client (abroad, mobilised, moved, declined themselves, other) also set a client flag so no later case opens.
- Cost accepted: on the first run about 460 clients qualify at once and the administrator cannot work them in 14 days; the most valuable come first and the rest expire.
