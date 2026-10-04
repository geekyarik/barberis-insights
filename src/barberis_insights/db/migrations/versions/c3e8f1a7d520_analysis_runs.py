"""analysis runs

Revision ID: c3e8f1a7d520
Revises: b7c1d9e2a410
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3e8f1a7d520'
down_revision: Union[str, Sequence[str], None] = 'b7c1d9e2a410'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("analysis_key", sa.String(40), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("window_from", sa.Date(), nullable=False),
        sa.Column("window_to", sa.Date(), nullable=False),
        sa.Column("asof", sa.Date(), nullable=False),
        sa.Column("lens", sa.String(40), nullable=False),
        sa.Column("lens_resolved", sa.JSON(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("metric_versions", sa.JSON(), nullable=False),
        sa.Column("data_fingerprint", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(20), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
    )
    op.create_index("ix_analysis_runs_analysis_key", "analysis_runs", ["analysis_key"])
    op.create_index("ix_analysis_runs_lookup", "analysis_runs", ["analysis_key", "scope", "window_to"])


def downgrade() -> None:
    op.drop_index("ix_analysis_runs_lookup", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_analysis_key", table_name="analysis_runs")
    op.drop_table("analysis_runs")
