"""client flags (why not to call) and a manual phone number

Revision ID: b2d9f4a7c1e6
Revises: b4d7e2a9c6f1
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2d9f4a7c1e6'
down_revision: Union[str, Sequence[str], None] = 'b4d7e2a9c6f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("client_flags",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False), sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("until", sa.Date()), sa.Column("by", sa.String(80), nullable=False),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False), sa.Column("lifted", sa.DateTime(timezone=True)))
    op.create_index("ix_client_flags_client_id", "client_flags", ["client_id"])
    op.add_column("clients", sa.Column("phone_manual", sa.String(40)))
    op.add_column("clients", sa.Column("phone_manual_by", sa.String(80)))


def downgrade() -> None:
    with op.batch_alter_table("clients") as b:
        b.drop_column("phone_manual_by"); b.drop_column("phone_manual")
    op.drop_index("ix_client_flags_client_id", table_name="client_flags")
    op.drop_table("client_flags")
