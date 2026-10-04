"""factors, factor events, lenses; hypotheses.factor_id; existing notes become annotate-only factors

Revision ID: f7d4c9a2b8e3
Revises: e6c3b8d1f2a7
Create Date: 2026-10-04

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7d4c9a2b8e3'
down_revision: Union[str, Sequence[str], None] = 'e6c3b8d1f2a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("factors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False), sa.Column("category", sa.String(30), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False), sa.Column("date_to", sa.Date()),
        sa.Column("recurrence", sa.String(10), nullable=False), sa.Column("lead_days", sa.Integer(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False), sa.Column("expected_effects", sa.JSON(), nullable=False),
        sa.Column("treatment", sa.String(20), nullable=False), sa.Column("adjust_factor", sa.Float()),
        sa.Column("tags", sa.JSON(), nullable=False), sa.Column("source", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False), sa.Column("effect_run_id", sa.Integer()),
        sa.Column("created", sa.DateTime(timezone=True), nullable=False), sa.Column("updated", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_factors_date_from", "factors", ["date_from"])
    op.create_table("factor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("factor_id", sa.Integer(), nullable=False), sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("detail", sa.JSON()))
    op.create_index("ix_factor_events_factor_id", "factor_events", ["factor_id"])
    op.create_table("lenses",
        sa.Column("key", sa.String(40), primary_key=True), sa.Column("label", sa.String(80), nullable=False), sa.Column("rule", sa.JSON(), nullable=False))
    with op.batch_alter_table("hypotheses", schema=None) as batch_op:
        batch_op.add_column(sa.Column("factor_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_hypotheses_factor_id", ["factor_id"])
        batch_op.create_foreign_key("fk_hypotheses_factor_id", "factors", ["factor_id"], ["id"])
    bind = op.get_bind()
    bind.execute(sa.text("INSERT INTO lenses (key, label, rule) VALUES ('clean', 'Clean weeks', :r)"), {"r": json.dumps({"honour": ["exclude", "adjust"], "categories": None, "ids": None})})
    now = sa.text("CURRENT_TIMESTAMP")
    for n in bind.execute(sa.text("SELECT id, date_from, date_to, kind, scopes, title, body, tags, source, created FROM notes ORDER BY id")).fetchall():
        bind.execute(sa.text(
            "INSERT INTO factors (title, body, kind, category, date_from, date_to, recurrence, lead_days, scopes, expected_effects, treatment, tags, source, active, created, updated) "
            "VALUES (:title, :body, :kind, :cat, :f, :t, 'none', 0, :scopes, '[]', 'annotate', :tags, :src, 1, :created, :created)"),
            {"title": n.title, "body": n.body or "", "kind": "external" if n.kind == "external" else "internal", "cat": n.kind, "f": n.date_from, "t": n.date_to,
             "scopes": n.scopes or "[]", "tags": n.tags or "[]", "src": f"note:{n.id}", "created": n.created})


def downgrade() -> None:
    with op.batch_alter_table("hypotheses", schema=None) as batch_op:
        batch_op.drop_constraint("fk_hypotheses_factor_id", type_="foreignkey")
        batch_op.drop_index("ix_hypotheses_factor_id")
        batch_op.drop_column("factor_id")
    for t in ("lenses", "factor_events", "factors"):
        op.drop_table(t)
