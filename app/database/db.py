"""
Database Session & Lifecycle Manager
====================================
Configures SQLite / SQLAlchemy connection pooling, schema migration compatibility,
and session context management.
"""

from contextlib import contextmanager
from typing import Dict, Generator, List, Tuple

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import DATABASE_DIR, config
from app.observability.logger import redact_secret_text, setup_structured_logger
from .models import Base

logger = setup_structured_logger("TradingPlatform.Database")

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


def _apply_additive_migrations(target_engine=None) -> None:
    """
    Adds newly introduced columns and indexes to pre-existing SQLite/Postgres tables
    so upgrades never fail against existing databases like database/platform.db.
    """
    eng = target_engine or engine
    inspector = inspect(eng)
    dialect = eng.dialect.name
    ts_type = "TIMESTAMP" if dialect == "postgresql" else "DATETIME"

    migrations: Dict[str, List[Tuple[str, str]]] = {
        "signals": [
            ("idempotency_key", "VARCHAR(128)"),
            ("candle_timestamp", ts_type),
            ("data_source", "VARCHAR(64)"),
        ],
        "paper_trades": [
            ("idempotency_key", "VARCHAR(128)"),
            ("candle_timestamp", ts_type),
            ("settled_at", ts_type),
            ("entry_source", "VARCHAR(64)"),
            ("expiry_source", "VARCHAR(64)"),
            ("settlement_attempts", "INTEGER DEFAULT 0"),
            ("settlement_detail", "TEXT"),
        ],
    }

    with eng.begin() as conn:
        existing_tables = set(inspector.get_table_names())
        for table_name, cols in migrations.items():
            if table_name not in existing_tables:
                continue
            existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
            for col_name, col_type in cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))

            existing_indexes = {idx["name"] for idx in inspector.get_indexes(table_name)}
            idx_name = f"ix_{table_name}_idempotency_key"
            if idx_name not in existing_indexes:
                conn.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} "
                        f"ON {table_name} (idempotency_key)"
                    )
                )


def init_db(target_engine=None) -> None:
    """Creates all database tables and runs additive compatibility migrations."""
    eng = target_engine or engine
    Base.metadata.create_all(bind=eng)
    _apply_additive_migrations(eng)


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
    from .models import PaperTradeRecord, SignalRecord

    deleted_counts = {"signals": 0, "paper_trades": 0}

    try:
        with get_db_session() as session:
            total_signals = session.query(SignalRecord).count()
            if total_signals > max_records:
                excess = total_signals - max_records
                subquery = session.query(SignalRecord.id).order_by(SignalRecord.timestamp.asc()).limit(excess)
                ids_to_del = [r[0] for r in subquery.all()]
                if ids_to_del:
                    session.query(SignalRecord).filter(SignalRecord.id.in_(ids_to_del)).delete(
                        synchronize_session=False
                    )
                    deleted_counts["signals"] = len(ids_to_del)

            total_trades = session.query(PaperTradeRecord).count()
            if total_trades > max_records:
                excess = total_trades - max_records
                subquery = session.query(PaperTradeRecord.id).order_by(PaperTradeRecord.entry_time.asc()).limit(excess)
                ids_to_del = [r[0] for r in subquery.all()]
                if ids_to_del:
                    session.query(PaperTradeRecord).filter(PaperTradeRecord.id.in_(ids_to_del)).delete(
                        synchronize_session=False
                    )
                    deleted_counts["paper_trades"] = len(ids_to_del)

        if db_url.startswith("sqlite"):
            try:
                with engine.connect() as conn:
                    conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
            except Exception as vac_exc:
                logger.warning("SQLite VACUUM failed during maintenance: %s", redact_secret_text(str(vac_exc)))

    except Exception as exc:
        logger.error("Database pruning failed: %s", redact_secret_text(str(exc)), exc_info=True)
        raise

    return deleted_counts
