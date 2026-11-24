"""SQLite schema and per-request connections."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = Path(os.environ.get("ROBOTAXI_DB", ROOT / "data" / "robotaxi.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    payment TEXT NOT NULL DEFAULT 'card'
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    csrf TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    expires INTEGER NOT NULL,
    challenge_phone TEXT,
    challenge_expires INTEGER,
    challenge_digest TEXT,
    challenge_purpose TEXT NOT NULL DEFAULT 'access',
    attempts INTEGER NOT NULL DEFAULT 0,
    quote TEXT
);

CREATE TABLE IF NOT EXISTS vehicles (
    id INTEGER PRIMARY KEY,
    plate TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    passenger_id INTEGER NOT NULL REFERENCES accounts(id),
    quote_token TEXT NOT NULL UNIQUE,
    pickup TEXT NOT NULL,
    destination TEXT NOT NULL,
    pickup_minutes INTEGER NOT NULL,
    seats INTEGER NOT NULL,
    distance INTEGER NOT NULL,
    duration INTEGER NOT NULL,
    price INTEGER NOT NULL,
    payment TEXT NOT NULL,
    payment_status TEXT NOT NULL DEFAULT 'pending',
    vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
    status TEXT NOT NULL DEFAULT 'assigned',
    completion TEXT,
    created_at INTEGER NOT NULL,
    pickup_at INTEGER NOT NULL,
    ended_at INTEGER,
    route_map TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS active_order_passenger ON orders(passenger_id)
WHERE status IN ('assigned', 'arrived', 'unlocked', 'riding');

CREATE UNIQUE INDEX IF NOT EXISTS active_order_vehicle ON orders(vehicle_id)
WHERE status IN ('assigned', 'arrived', 'unlocked', 'riding');

CREATE TABLE IF NOT EXISTS feedback (
    order_id INTEGER PRIMARY KEY REFERENCES orders(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    passenger_id INTEGER NOT NULL REFERENCES accounts(id),
    order_id INTEGER REFERENCES orders(id),
    topic TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS orders_passenger ON orders(passenger_id, id);
CREATE INDEX IF NOT EXISTS tickets_passenger ON tickets(passenger_id, id);
"""

VEHICLES = [
    (38, "А 047 ВС 102", "Белый"),
    (41, "Е 138 КМ 102", "Серебристый"),
    (47, "Т 569 РА 102", "Белый"),
    (52, "М 205 ОН 102", "Серебристый"),
]


@contextmanager
def connect(path=DATA_PATH, write=False):
    db = sqlite3.connect(path, timeout=8)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")
        with db:
            yield db
    finally:
        db.close()


def initialize(path=DATA_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        for table, column, definition in (
            ("sessions", "challenge_digest", "TEXT"),
            ("sessions", "challenge_purpose", "TEXT NOT NULL DEFAULT 'access'"),
            ("orders", "route_map", "TEXT"),
        ):
            if column not in {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        db.executemany("INSERT OR IGNORE INTO vehicles VALUES (?, ?, ?)", VEHICLES)
