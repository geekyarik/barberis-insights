# Provenance

Third-party skill, MIT licence (see `LICENSE`): https://github.com/nextlevelbuilder/ui-ux-pro-max-skill, path `.claude/skills/ui-ux-pro-max`,
copied on 2026-10-06 unchanged except that its `scripts/tests` folder was left out. Reviewed before use: the scripts make no network
calls and run no shell commands; the only file write is the optional `--persist` design-system output.

How to run it from this repo (the skill text says `${CLAUDE_PLUGIN_ROOT}`, which is not set for a project skill):

    python3 .claude/skills/ui-ux-pro-max/scripts/search.py "<query>" --domain ux

Our stack is server-rendered Jinja with plain CSS, which is not one of its 22 stacks: use `--domain` searches, not `--stack`. Its
"design system" pattern for this product was a marketing-site layout and was discarded; the accessibility rules were applied (see
ARCHITECTURE.md, "UI baseline").
