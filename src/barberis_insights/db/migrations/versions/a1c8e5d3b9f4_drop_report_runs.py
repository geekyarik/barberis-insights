"""drop stored reports: the weekly message is built from live data; deliveries are keyed by week

Revision ID: a1c8e5d3b9f4
Revises: f7d4c9a2b8e3
Create Date: 2026-10-06

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c8e5d3b9f4'
down_revision: Union[str, Sequence[str], None] = 'f7d4c9a2b8e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    weeks = {}
    for rid, content in bind.execute(sa.text("select id, content from report_runs where report_key = 'weekly_review'")):
        weeks[rid] = (json.loads(content) if isinstance(content, str) else content)["week"]
    for rid, week in weeks.items():           # a week already sent must never be sent again under the new key
        bind.execute(sa.text("update deliveries set dedupe_key = :new where dedupe_key = :old"), {"new": f"weekly:{week}", "old": f"report:{rid}"})
    with op.batch_alter_table("deliveries") as b:
        b.drop_column("report_run_id")
    op.drop_index("ix_report_runs_report_key", table_name="report_runs")
    op.drop_table("report_runs")


def downgrade() -> None:
    op.create_table("report_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("report_key", sa.String(40), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False), sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("lens", sa.String(40), nullable=False), sa.Column("analysis_run_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(20), nullable=False), sa.Column("created", sa.DateTime(), nullable=False), sa.Column("content", sa.JSON(), nullable=False))
    op.create_index("ix_report_runs_report_key", "report_runs", ["report_key"])
    with op.batch_alter_table("deliveries") as b:
        b.add_column(sa.Column("report_run_id", sa.Integer()))
