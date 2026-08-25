"""
Database Session & Lifecycle Manager
====================================
Configures SQLite / SQLAlchemy connection pooling and session context management.
"""

from contextlib import contextmanager
from typing import Generator, Dict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from app.config import config, DATABASE_DIR
from .models import Base

DATABASE_DIR.mkdir(parents=True, exist_ok=True)
db_url = config.db_url

engine_kwargs = {"echo": False}
if db_url.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 10

engine = create_engine(db_url, **engine_kwargs)

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


def prune_database(max_records: int = 1000) -> Dict[str, int]:
    """
    Prunes older signals and paper trade records to keep the database lightweight
    and prevent exceeding Render free tier disk quotas. Reclaims disk space with VACUUM.
    """
    from .models import SignalRecord, PaperTradeRecord
    from sqlalchemy import text

    deleted_counts = {"signals": 0, "paper_trades": 0}

    try:
        with get_db_session() as session:
            # 1. Prune SignalRecords
            total_signals = session.query(SignalRecord).count()
            if total_signals > max_records:
                excess = total_signals - max_records
                subquery = session.query(SignalRecord.id).order_by(SignalRecord.timestamp.asc()).limit(excess)
                ids_to_del = [r[0] for r in subquery.all()]
                if ids_to_del:
                    session.query(SignalRecord).filter(SignalRecord.id.in_(ids_to_del)).delete(synchronize_session=False)
                    deleted_counts["signals"] = len(ids_to_del)

            # 2. Prune PaperTradeRecords
            total_trades = session.query(PaperTradeRecord).count()
            if total_trades > max_records:
                excess = total_trades - max_records
                subquery = session.query(PaperTradeRecord.id).order_by(PaperTradeRecord.entry_time.asc()).limit(excess)
                ids_to_del = [r[0] for r in subquery.all()]
                if ids_to_del:
                    session.query(PaperTradeRecord).filter(PaperTradeRecord.id.in_(ids_to_del)).delete(synchronize_session=False)
                    deleted_counts["paper_trades"] = len(ids_to_del)

        # 3. If SQLite, run VACUUM to reclaim disk pages
        if db_url.startswith("sqlite"):
            try:
                with engine.connect() as conn:
                    conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
            except Exception:
                pass

    except Exception:
        pass

    return deleted_counts

