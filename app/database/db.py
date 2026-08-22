"""
Database Session & Lifecycle Manager
====================================
Configures SQLite / SQLAlchemy connection pooling and session context management.
"""

from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import config, DATABASE_DIR
from .models import Base

DATABASE_DIR.mkdir(parents=True, exist_ok=True)
db_url = config.db_url

engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Creates all database tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """Context manager for safe session handling and transaction committing."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
