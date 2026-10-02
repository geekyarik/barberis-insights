from logging.config import fileConfig

from alembic import context

from barberis_insights.db.models import Base
from barberis_insights.db.session import engine

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def include_name(name, type_, parent_names):
    """Skip FTS5 tables before reflection (SQLite cannot reflect virtual tables)."""
    return not (type_ == "table" and name and name.startswith("notes_fts"))


def include_object(obj, name, type_, reflected, compare_to):
    """Ignore the FTS5 tables (created by db.session.ensure_fts, not by the models)."""
    return not (type_ == "table" and name and name.startswith("notes_fts"))


def run_migrations_offline() -> None:
    context.configure(url=str(engine().url), target_metadata=target_metadata, literal_binds=True, render_as_batch=True, include_object=include_object, include_name=include_name)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    with engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True, include_object=include_object, include_name=include_name)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
