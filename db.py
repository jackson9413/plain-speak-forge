"""SQLite session log for Plain-Speak Forge."""
from __future__ import annotations

import datetime
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PLAIN_SPEAK_DB", os.path.join(BASE, "plain_speak.sqlite3"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT 'general_public',
    verdict TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    self_rating INTEGER,
    notes TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}'
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def save_session(result):
    conn = connect()
    cur = conn.execute(
        "INSERT INTO sessions (created_at, title, audience, verdict, score, word_count, payload)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            datetime.datetime.now().isoformat(timespec="seconds"),
            result.get("title", ""),
            result.get("audience", {}).get("key", "general_public"),
            result.get("verdict", ""),
            float(result.get("score", 0)),
            int(result.get("stats", {}).get("words", 0)),
            json.dumps(result, ensure_ascii=False),
        ),
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def list_sessions(limit=50):
    conn = connect()
    rows = conn.execute(
        "SELECT id, created_at, title, audience, verdict, score, word_count, self_rating, notes"
        " FROM sessions ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_session(sid):
    conn = connect()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    try:
        data["result"] = json.loads(data.get("payload") or "{}")
    except Exception:
        data["result"] = {}
    return data


def update_session(sid, self_rating=None, notes=None):
    conn = connect()
    fields, values = [], []
    if self_rating is not None:
        fields.append("self_rating = ?")
        values.append(int(self_rating))
    if notes is not None:
        fields.append("notes = ?")
        values.append(str(notes))
    if not fields:
        conn.close()
        return get_session(sid)
    values.append(sid)
    conn.execute("UPDATE sessions SET %s WHERE id = ?" % ", ".join(fields), values)
    conn.commit()
    conn.close()
    return get_session(sid)
