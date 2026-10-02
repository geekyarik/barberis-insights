"""outreach sheet state

Revision ID: e49fc5ca8f99
Revises: 05bad99d6631
Create Date: 2026-10-02 17:29:42.145256

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e49fc5ca8f99'
down_revision: Union[str, Sequence[str], None] = '05bad99d6631'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("outreach_cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sheet_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("outreach_cases", schema=None) as batch_op:
        batch_op.drop_column("sheet_state")
