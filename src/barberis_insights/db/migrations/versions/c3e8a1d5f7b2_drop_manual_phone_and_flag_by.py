"""drop the manual phone number and the flag's "who said it" (decided redundant)

Revision ID: c3e8a1d5f7b2
Revises: b2d9f4a7c1e6
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3e8a1d5f7b2'
down_revision: Union[str, Sequence[str], None] = 'b2d9f4a7c1e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as b:
        b.drop_column("phone_manual_by"); b.drop_column("phone_manual")
    with op.batch_alter_table("client_flags") as b:
        b.drop_column("by")


def downgrade() -> None:
    op.add_column("clients", sa.Column("phone_manual", sa.String(40)))
    op.add_column("clients", sa.Column("phone_manual_by", sa.String(80)))
    op.add_column("client_flags", sa.Column("by", sa.String(80), nullable=False, server_default=""))
