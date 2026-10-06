"""client profiles keep the chance of returning

Revision ID: f6b3d1e8c2a4
Revises: e5a2c9d7b1f3
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6b3d1e8c2a4'
down_revision: Union[str, Sequence[str], None] = 'e5a2c9d7b1f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("client_profiles", sa.Column("return_chance", sa.Float()))


def downgrade() -> None:
    with op.batch_alter_table("client_profiles") as b:
        b.drop_column("return_chance")
