"""users and login sessions

Revision ID: d4f1b8c6a2e9
Revises: c3e8a1d5f7b2
Create Date: 2026-10-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4f1b8c6a2e9'
down_revision: Union[str, Sequence[str], None] = 'c3e8a1d5f7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("username", sa.String(50), nullable=False, unique=True),
        sa.Column("display_name", sa.String(80), nullable=False, server_default=""), sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False), sa.Column("last_login", sa.DateTime(timezone=True)))
    op.create_table("user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True), sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", sa.Integer(), nullable=False), sa.Column("created", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
    op.drop_table("users")
