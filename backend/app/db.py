"""Database engine and session helpers for the RecoverX transactional store."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory; injectable for tests and workers."""
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


SessionLocal = create_session_factory()


def initialize_database() -> None:
    """Create local development tables; production should use migrations instead."""
    from backend.app.models.base import Base
    import backend.app.models.recovery  # noqa: F401 - registers model metadata

    Base.metadata.create_all(SessionLocal.kw["bind"])


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that closes each request-scoped database session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
