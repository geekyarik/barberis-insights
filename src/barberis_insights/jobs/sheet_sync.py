"""sheet_sync: pull the admin's outcomes from the call sheet, attribute returns, push approved cases. Speaks up only on problems."""
from __future__ import annotations

from ..config import settings
from ..i18n import normalize
from .registry import JobContext, job


@job("sheet_sync", "Sync the admin's call sheet", hours=(9, 19))
def sheet_sync(ctx: JobContext) -> dict:
    from ..outreach.offers import active_offers
    from ..outreach.sheets import FakeSheet, GspreadSheet, sync
    if ctx.dry_run:
        sheet = FakeSheet()
    elif ctx.sheet_factory:
        sheet = ctx.sheet_factory()
    elif settings.sheet_id:
        sheet = GspreadSheet(settings.sheet_id)
    else:
        return {"status": "skipped", "reason": "INSIGHTS_SHEET_ID is not set"}
    out = sync(ctx.s, sheet, [o.code for o in active_offers(ctx.s)], normalize(settings.sheet_lang))
    return {k: v for k, v in out.items() if isinstance(v, (int, float, str, bool))}
