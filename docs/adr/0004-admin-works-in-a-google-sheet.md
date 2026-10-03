# The admin works in a shared Google Sheet, accessed by a service account

The admin who calls clients gets approved win-back cases in a Google Sheet and records outcomes there; the service syncs both ways. We chose this over giving the admin dashboard access (the laptop would have to be reachable) and over writing tasks into Altegio client comments (outcomes would be free text). The service authenticates with a service account that sees only sheets shared with it, because a Testing-mode OAuth sign-in expires every 7 days. Phone numbers are removed from the sheet when a case closes.
