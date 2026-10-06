"""outreach case phone

Revision ID: b4d7e2a9c6f1
Revises: a1c8e5d3b9f4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b4d7e2a9c6f1'
down_revision: Union[str, Sequence[str], None] = 'a1c8e5d3b9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("outreach_cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("phone", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outreach_cases", schema=None) as batch_op:
        batch_op.drop_column("phone")
