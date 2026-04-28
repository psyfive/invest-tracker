"""주가 스냅샷을 SQLite와 CSV에 동시에 저장한다.

- SQLite: 동일 (ticker, date) 조합은 UPSERT로 갱신되어 추적 시계열을 유지.
- CSV: append 모드. 헤더 없으면 자동 생성.
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .fetcher import PriceSnapshot


SCHEMA = """
CREATE TABLE IF NOT EXISTS price_snapshots (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,        -- YYYY-MM-DD (한국 시간 기준)
    fetched_at  TEXT NOT NULL,        -- ISO timestamp
    last_close  REAL,
    prev_close  REAL,
    change_pct  REAL,
    currency    TEXT,
    name        TEXT,
    status      TEXT,
    PRIMARY KEY (ticker, date)
);
"""

CSV_FIELDS = [
    "date",
    "ticker",
    "fetched_at",
    "last_close",
    "prev_close",
    "change_pct",
    "currency",
    "name",
    "status",
]


def _ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def _today_kst() -> str:
    """저장 기준일은 한국시간 날짜로 통일한다."""
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def save_snapshot(
    snap: PriceSnapshot,
    db_path: str | Path = "output/prices.db",
    csv_path: str | Path = "output/prices.csv",
) -> None:
    """스냅샷 1건을 DB와 CSV에 모두 저장한다."""
    db_path = Path(db_path)
    csv_path = Path(csv_path)
    today = _today_kst()
    row = snap.to_row()
    row["date"] = today

    # SQLite (UPSERT)
    conn = _ensure_db(db_path)
    try:
        conn.execute(
            """
            INSERT INTO price_snapshots
                (ticker, date, fetched_at, last_close, prev_close, change_pct,
                 currency, name, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                fetched_at=excluded.fetched_at,
                last_close=excluded.last_close,
                prev_close=excluded.prev_close,
                change_pct=excluded.change_pct,
                currency=excluded.currency,
                name=excluded.name,
                status=excluded.status
            """,
            (
                row["ticker"],
                row["date"],
                row["fetched_at"],
                row["last_close"],
                row["prev_close"],
                row["change_pct"],
                row["currency"],
                row["name"],
                row["status"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # CSV append
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({k: row.get(k) for k in CSV_FIELDS})
