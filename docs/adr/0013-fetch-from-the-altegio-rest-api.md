# Fetch from the Altegio REST API

The jobs now fetch fresh data straight from Altegio's REST API. This replaces having a headless Claude pull it through the claude.ai Altegio Pro connector (ADR-0002), which had become the weakest link: it took about two minutes, it needed a signed-in Claude and `uv` on the scheduler's PATH, the model had to retype each result into a file, and when the connector renamed a field (`date` became `datetime`, October 2026) every file was silently skipped and the data went stale for five days.

- **Access:** `Authorization: Bearer <partner token>, User <user token>` with `Accept: application/vnd.api.v2+json` (Altegio support). The partner token is in `.env`. The user token is not stored by hand: the adapter logs in with the user's login and password (`POST /auth`), keeps the token in `var/`, and logs in again when the API answers 401 or 403. A token pasted into a shell profile had already gone stale.
- **What it reads:** appointments (`/records`, 200 a page), each barber's shifts (`/schedule`), and each appointment's client contact (phone, email). A fetch of the appointments of two months and the shifts of 22 staff takes about three seconds.
- **Mapping, validated on 936 appointments against the connector data (same ids, same values):** `attendance` 1 = arrived, -1 = no show, 2 = confirmed, 0 = waiting; the total is the sum of the services' `cost` (already the line total).
- **Cancelled appointments** are not returned at all, so a future booking that disappears is treated as gone (the daily cases job already does this).
- **A fetch counts as successful only if the database received an import.** Errors carry no credential.
- The connector files and the client export stay as manual routes. The full client list (6 987 clients with phone, comment and consent flags) is also available and is the next step; today only the clients that appear in fetched appointments get their phone refreshed.
