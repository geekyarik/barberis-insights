"""metric versions on measurements and goals

Revision ID: b7c1d9e2a410
Revises: 25a5a305980d
Create Date: 2026-10-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c1d9e2a410'
down_revision: Union[str, Sequence[str], None] = '25a5a305980d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade() -> None:
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"))
    with op.batch_alter_table("measurements", schema=None, naming_convention=NAMING) as batch_op:
        batch_op.add_column(sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.drop_constraint("uq_measurements_asof", type_="unique")
        batch_op.create_unique_constraint("uq_measurements_version", ["asof", "scope", "metric", "metric_version"])


def downgrade() -> None:
    with op.batch_alter_table("measurements", schema=None, naming_convention=NAMING) as batch_op:
        batch_op.drop_constraint("uq_measurements_version", type_="unique")
        batch_op.create_unique_constraint("uq_measurements_asof", ["asof", "scope", "metric"])
        batch_op.drop_column("metric_version")
    with op.batch_alter_table("goals", schema=None) as batch_op:
        batch_op.drop_column("metric_version")
