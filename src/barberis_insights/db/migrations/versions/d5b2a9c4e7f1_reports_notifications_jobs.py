"""report runs, recipients, subscriptions, deliveries, job runs

Revision ID: d5b2a9c4e7f1
Revises: c3e8f1a7d520
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5b2a9c4e7f1'
down_revision: Union[str, Sequence[str], None] = 'c3e8f1a7d520'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("report_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_key", sa.String(40), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("lens", sa.String(40), nullable=False),
        sa.Column("analysis_run_ids", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(20), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False))
    op.create_index("ix_report_runs_report_key", "report_runs", ["report_key"])
    op.create_table("recipients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("lang", sa.String(5), nullable=False),
        sa.Column("telegram_chat_id", sa.Integer()),
        sa.Column("active", sa.Boolean(), nullable=False))
    op.create_table("subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("recipients.id"), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.UniqueConstraint("recipient_id", "kind", "channel"))
    op.create_index("ix_subscriptions_recipient_id", "subscriptions", ["recipient_id"])
    op.create_table("deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id"), nullable=False),
        sa.Column("report_run_id", sa.Integer(), sa.ForeignKey("report_runs.id")),
        sa.Column("dedupe_key", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("external_id", sa.String(40), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("subscription_id", "dedupe_key"))
    op.create_index("ix_deliveries_subscription_id", "deliveries", ["subscription_id"])
    op.create_table("job_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job", sa.String(40), nullable=False),
        sa.Column("slot", sa.String(20), nullable=False),
        sa.Column("started", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("counts", sa.JSON()),
        sa.Column("error", sa.Text(), nullable=False))
    op.create_index("ix_job_runs_job", "job_runs", ["job"])


def downgrade() -> None:
    for t in ("job_runs", "deliveries", "subscriptions", "recipients", "report_runs"):
        op.drop_table(t)
