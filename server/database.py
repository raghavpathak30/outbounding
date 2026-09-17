"""
Database connection, session management, and SQLite WAL configuration.
"""
import os
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, Session
from server.models.base import Base
# Import all entities so Base.metadata knows about them
import server.models  # noqa: F401

DEFAULT_DB_FILE = "data/outbound.db"


def get_database_url() -> str:
    """Returns database URL from env or defaults to local SQLite file."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    db_path = Path(DEFAULT_DB_FILE)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.resolve()}"


def create_db_engine(db_url: str | None = None, echo: bool = False):
    url = db_url or get_database_url()
    connect_args = {}

    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    engine = create_engine(url, echo=echo, connect_args=connect_args)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA foreign_keys=ON;")
            cursor.execute("PRAGMA busy_timeout=5000;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.close()

    return engine


# Default application engine & sessionmaker
engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """
    Creates all database tables defined in Base metadata,
    and safely applies backward-compatible migrations for existing databases.
    """
    e = target_engine or engine
    Base.metadata.create_all(bind=e)

    # Safe Phase-6 schema migration: ensure checkpoint_state_json exists on pipeline_runs
    try:
        inspector = inspect(e)
        if "pipeline_runs" in inspector.get_table_names():
            columns = [col["name"] for col in inspector.get_columns("pipeline_runs")]
            if "checkpoint_state_json" not in columns:
                with e.begin() as conn:
                    conn.execute(text("ALTER TABLE pipeline_runs ADD COLUMN checkpoint_state_json TEXT;"))
    except Exception:
        pass


def reset_db(target_engine=None) -> None:
    """Drops and recreates all database tables (used in test fixtures)."""
    e = target_engine or engine
    Base.metadata.drop_all(bind=e)
    Base.metadata.create_all(bind=e)


def get_db() -> Generator[Session, None, None]:
    """FastAPI / context manager dependency yielding an active database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
