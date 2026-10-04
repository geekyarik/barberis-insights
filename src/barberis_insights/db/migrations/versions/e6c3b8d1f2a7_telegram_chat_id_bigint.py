"""telegram chat id is a bigint (group ids are longer than 32 bits)

Revision ID: e6c3b8d1f2a7
Revises: d5b2a9c4e7f1
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6c3b8d1f2a7'
down_revision: Union[str, Sequence[str], None] = 'd5b2a9c4e7f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("recipients", schema=None) as batch_op:
        batch_op.alter_column("telegram_chat_id", existing_type=sa.Integer(), type_=sa.BigInteger(), existing_nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("recipients", schema=None) as batch_op:
        batch_op.alter_column("telegram_chat_id", existing_type=sa.BigInteger(), type_=sa.Integer(), existing_nullable=True)
