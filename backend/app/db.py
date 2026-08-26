"""Database engine and session helpers for the RecoverX transactional store."""

import contextvars
from collections.abc import Generator
from typing import Callable

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from backend.app.config import get_settings

_current_session_context: contextvars.ContextVar[Session | None] = contextvars.ContextVar(
    "current_session_context", default=None
)


def set_current_session(session: Session | None) -> contextvars.Token:
    """Set the thread/task-local active database session."""
    return _current_session_context.set(session)


def reset_current_session(token: contextvars.Token) -> None:
    """Reset the thread/task-local database session."""
    _current_session_context.reset(token)


def get_current_session() -> Session | None:
    """Get the thread/task-local active database session if any."""
    return _current_session_context.get()


def create_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory; injectable for tests and workers."""
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


_default_session_factory = create_session_factory()
_active_session_factory: sessionmaker[Session] = _default_session_factory


def get_session_factory() -> sessionmaker[Session]:
    """Return the currently configured session factory."""
    return _active_session_factory


def set_session_factory(factory: sessionmaker[Session]) -> None:
    """Override session factory (useful for tests)."""
    global _active_session_factory
    _active_session_factory = factory


def reset_session_factory() -> None:
    """Reset session factory to default."""
    global _active_session_factory
    _active_session_factory = _default_session_factory


# Backward compatible alias
SessionLocal = _default_session_factory


def initialize_database() -> None:
    """Create local development tables; production should use migrations instead."""
    from backend.app.models.base import Base
    import backend.app.models.recovery  # noqa: F401 - registers model metadata

    engine = _active_session_factory.kw["bind"]
    Base.metadata.create_all(engine)


def check_database_health(session: Session | None = None) -> bool:
    """Verify database connectivity with a lightweight ping."""
    try:
        if session is not None:
            session.execute(text("SELECT 1"))
            return True
        engine = _active_session_factory.kw["bind"]
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that closes each request-scoped database session."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()
