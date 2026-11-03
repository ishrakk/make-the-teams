"""Alembic runner. Needs only DATABASE_URL, so it doesn't need the app's passcodes."""

import os

from alembic import context
from sqlalchemy import create_engine, text

from app.db.models import Base

# Any number with no other meaning. Every migrator takes this same lock.
MIGRATION_LOCK_ID = 7264519

engine = create_engine(os.environ["DATABASE_URL"])

with engine.connect() as connection:
    # Pods start together, so make any others wait while one of them migrates.
    connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
    connection.commit()
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
    connection.commit()
    connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
    connection.commit()
