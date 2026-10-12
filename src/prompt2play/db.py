"""Database engine and transaction helpers."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from prompt2play.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=10, max_overflow=10)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency providing a transaction-scoped SQLAlchemy session."""

    with SessionLocal() as session:
        yield session
