"""risk cases replace the old win-back cases (propose, approve, sheet)

Revision ID: e5a2c9d7b1f3
Revises: d4f1b8c6a2e9
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5a2c9d7b1f3'
down_revision: Union[str, Sequence[str], None] = 'd4f1b8c6a2e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("risk_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(20), nullable=False), sa.Column("trigger_days", sa.Integer(), nullable=False),
        sa.Column("crossed_on", sa.Date(), nullable=False), sa.Column("last_visit", sa.Date(), nullable=False),
        sa.Column("opened", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("outcome", sa.String(20)), sa.Column("reason", sa.String(20)),
        sa.Column("comment", sa.Text(), nullable=False), sa.Column("offer", sa.String(40)), sa.Column("barber_id", sa.Integer()),
        sa.Column("priority", sa.Float(), nullable=False), sa.Column("contacted", sa.Boolean(), nullable=False),
        sa.Column("booked_for", sa.Date()), sa.Column("appointment_id", sa.Integer()), sa.Column("admin_booked_on", sa.Date()),
        sa.Column("visited_on", sa.Date()), sa.Column("visit_revenue", sa.Float()), sa.Column("processed_by", sa.String(50)),
        sa.Column("closed", sa.DateTime(timezone=True)), sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint("client_id", "trigger", "last_visit"))
    op.create_index("ix_risk_cases_client_id", "risk_cases", ["client_id"])
    op.create_index("ix_risk_cases_status", "risk_cases", ["status"])
    op.create_table("case_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("risk_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False), sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("by", sa.String(50), nullable=False), sa.Column("note", sa.Text(), nullable=False))
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])
    # the old cases were hand-made test rows from the sheet flow; the new flow starts clean
    op.drop_table("outreach_events")
    op.drop_table("outreach_cases")


def downgrade() -> None:
    op.create_table("outreach_cases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False), sa.Column("segment", sa.String(20), nullable=False), sa.Column("barber_id", sa.Integer()),
        sa.Column("priority", sa.Float(), nullable=False), sa.Column("suggested_offer", sa.String(40)), sa.Column("offer_arm", sa.String(40)),
        sa.Column("offer_given", sa.String(40)), sa.Column("assigned_to", sa.String(80)), sa.Column("phone", sa.String(40)),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("contacted_on", sa.Date()), sa.Column("returned_on", sa.Date()),
        sa.Column("revenue_recovered", sa.Float()), sa.Column("created", sa.DateTime(timezone=True), nullable=False), sa.Column("due", sa.Date()),
        sa.Column("closed", sa.DateTime(timezone=True)), sa.Column("sheet_state", sa.JSON()))
    op.create_table("outreach_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("case_id", sa.Integer(), sa.ForeignKey("outreach_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False), sa.Column("kind", sa.String(20), nullable=False))
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")
    op.drop_index("ix_risk_cases_status", table_name="risk_cases")
    op.drop_index("ix_risk_cases_client_id", table_name="risk_cases")
    op.drop_table("risk_cases")
