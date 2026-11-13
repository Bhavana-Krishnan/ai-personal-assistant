"""SQLite storage layer. All persistent state lives in one file: tasks, events,
preferences, notes, job applications, meal plans, and chat history."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(os.environ.get("PA_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
TZ_NAME  = os.environ.get("PA_TZ", "Asia/Kolkata")


def now_local() -> datetime:
    return datetime.now(ZoneInfo(TZ_NAME)).replace(tzinfo=None)


def db_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "assistant.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks(
  id INTEGER PRIMARY KEY,
  title    TEXT NOT NULL,
  due      TEXT,
  priority TEXT DEFAULT 'medium',
  category TEXT DEFAULT 'general',
  notes    TEXT DEFAULT '',
  status   TEXT DEFAULT 'open',
  created  TEXT,
  completed TEXT
);
CREATE TABLE IF NOT EXISTS events(
  id              INTEGER PRIMARY KEY,
  title           TEXT NOT NULL,
  start           TEXT NOT NULL,
  end             TEXT,
  description     TEXT DEFAULT '',
  category        TEXT DEFAULT 'general',
  remind_minutes  INTEGER DEFAULT 15,
  repeat          TEXT DEFAULT 'none',
  created         TEXT
);
CREATE TABLE IF NOT EXISTS prefs(
  key     TEXT PRIMARY KEY,
  value   TEXT NOT NULL,
  updated TEXT
);
CREATE TABLE IF NOT EXISTS notes(
  id      INTEGER PRIMARY KEY,
  topic   TEXT NOT NULL,
  content TEXT NOT NULL,
  created TEXT
);
CREATE TABLE IF NOT EXISTS applications(
  id         INTEGER PRIMARY KEY,
  company    TEXT NOT NULL,
  role       TEXT NOT NULL,
  status     TEXT DEFAULT 'saved',
  link       TEXT DEFAULT '',
  notes      TEXT DEFAULT '',
  follow_up  TEXT,
  applied_on TEXT,
  updated    TEXT
);
CREATE TABLE IF NOT EXISTS meals(
  id    INTEGER PRIMARY KEY,
  day   TEXT NOT NULL,
  meal  TEXT NOT NULL,
  items TEXT NOT NULL,
  notes TEXT DEFAULT '',
  UNIQUE(day, meal)
);
CREATE TABLE IF NOT EXISTS chat(
  id      INTEGER PRIMARY KEY,
  role    TEXT NOT NULL,
  content TEXT NOT NULL,
  created TEXT
);
"""


@contextmanager
def conn():
    c = sqlite3.connect(db_path(), timeout=10)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def rows(sql: str, args=()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def run(sql: str, args=()) -> int:
    with conn() as c:
        return c.execute(sql, args).lastrowid


def stamp() -> str:
    return now_local().isoformat(timespec="minutes")
