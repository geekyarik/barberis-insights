# The repository is public; business and personal data never enter git

The code lives in a public GitHub repository, so client contacts, the staff roster, business notes, the database, exports, credentials and the original analysis are kept in git-ignored `var/` and `legacy/`, and the code loads them from there (`var/barbers.json`, `var/seed_notes.json`, `.env`). Tests that need real data skip when it is absent. Anything new that carries names, phones, revenue figures or business events belongs in `var/`, never in source files or fixtures.
