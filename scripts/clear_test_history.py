"""
Helper to reset/clear test paper trades from SQLite database.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.database.db import get_db_session
from app.database.models import PaperTradeRecord, SignalRecord


def clear_history():
    with get_db_session() as session:
        n_trades = session.query(PaperTradeRecord).delete()
        n_sigs = session.query(SignalRecord).delete()
        session.commit()
        print(f"[SUCCESS] Cleared {n_trades} test paper trades and {n_sigs} test signal records from database.")


if __name__ == "__main__":
    clear_history()
