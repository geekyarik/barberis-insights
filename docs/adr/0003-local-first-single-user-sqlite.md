# Local-first: one SQLite database on the owner's laptop

The tool runs on the owner's laptop with a single SQLite file (`var/insights.sqlite`) and a dashboard bound to 127.0.0.1, rather than a hosted multi-user service. It holds client contact data, the user base is one or two people, and syncs run on demand — hosting would add security and cost without a matching benefit. Everything goes through SQLAlchemy and Alembic (except FTS5 note search), so moving to Postgres on a server stays possible if managers need their own access.
