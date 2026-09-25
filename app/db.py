from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS areas(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, zone TEXT NOT NULL,
  contact TEXT NOT NULL, contact_source TEXT NOT NULL,
  contact_updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incidents(
  id INTEGER PRIMARY KEY, area_id INTEGER NOT NULL REFERENCES areas(id),
  status TEXT NOT NULL CHECK(status IN ('investigating','outage','restoring','resolved')),
  started_at TEXT NOT NULL, eta_minutes INTEGER,
  source_note TEXT NOT NULL, updated_at TEXT NOT NULL,
  created_by TEXT NOT NULL,
  CHECK(eta_minutes IS NULL OR eta_minutes BETWEEN 0 AND 10080)
);
CREATE INDEX IF NOT EXISTS idx_incidents_area_updated ON incidents(area_id, updated_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_incident_per_area ON incidents(area_id) WHERE status != 'resolved';
CREATE TABLE IF NOT EXISTS incident_revisions(
  id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL REFERENCES incidents(id),
  status TEXT NOT NULL, eta_minutes INTEGER, source_note TEXT NOT NULL,
  changed_at TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_audit(
  id INTEGER PRIMARY KEY, trace_id TEXT NOT NULL, tool_name TEXT NOT NULL,
  arguments TEXT NOT NULL, result_status TEXT NOT NULL,
  elapsed_ms INTEGER NOT NULL, attempts INTEGER NOT NULL,
  occurred_at TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (1)")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def seed_demo(self) -> None:
        from .models import utc_now
        with self.connect() as db:
            if db.execute("SELECT count(*) FROM areas").fetchone()[0]:
                return
            now = utc_now()
            db.executemany(
                "INSERT INTO areas(name,zone,contact,contact_source,contact_updated_at) VALUES(?,?,?,?,?)",
                [("Nandanam Block A", "North campus", "Facility desk · extension 101", "Demo facility directory", now),
                 ("Nandanam Block B", "North campus", "Facility desk · extension 101", "Demo facility directory", now),
                 ("Courtyard Tower", "East campus", "Facility desk · extension 204", "Demo facility directory", now),
                 ("Workshop Wing", "Service zone", "Facility desk · extension 305", "Demo facility directory", now)],
            )
            db.execute("INSERT INTO incidents(area_id,status,started_at,eta_minutes,source_note,updated_at,created_by) VALUES(?,?,?,?,?,?,?)",
                       (2,"outage",now,75,"Synthetic training report from the facility desk.",now,"demo-seed"))
            incident_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            db.execute("INSERT INTO incident_revisions(incident_id,status,eta_minutes,source_note,changed_at,actor) VALUES(?,?,?,?,?,?)",
                       (incident_id,"outage",75,"Synthetic training report from the facility desk.",now,"demo-seed"))
