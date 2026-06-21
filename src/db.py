import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_user_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    subscription_status TEXT NOT NULL DEFAULT 'pending',
    preferred_hour INTEGER NOT NULL DEFAULT 9,
    difficulty INTEGER NOT NULL DEFAULT 1,
    current_content_id INTEGER,
    streak INTEGER NOT NULL DEFAULT 0,
    last_push_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS content_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT UNIQUE NOT NULL,
    meaning TEXT NOT NULL,
    explanation TEXT NOT NULL,
    example_en TEXT NOT NULL,
    example_cn TEXT NOT NULL,
    question TEXT NOT NULL,
    options_json TEXT NOT NULL,
    answer TEXT NOT NULL,
    difficulty INTEGER NOT NULL,
    topic TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    direction TEXT NOT NULL,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'text',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS learning_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    answer TEXT,
    is_correct INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS push_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    content_id INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS callback_events (
    event_key TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'received',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);
CREATE TABLE IF NOT EXISTS channel_contacts (
    channel_user_id TEXT PRIMARY KEY,
    name TEXT,
    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self, content):
        import json
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            for item in content:
                conn.execute(
                    """INSERT OR IGNORE INTO content_items
                    (term, meaning, explanation, example_en, example_cn, question,
                     options_json, answer, difficulty, topic)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item["term"], item["meaning"], item["explanation"],
                     item["example_en"], item["example_cn"], item["question"],
                     json.dumps(item["options"], ensure_ascii=False), item["answer"],
                     item["difficulty"], item["topic"]),
                )

    def all(self, sql, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def one(self, sql, params=()):
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    def execute(self, sql, params=()):
        with self.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.lastrowid

    def claim_callback_event(self, event_key):
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO callback_events (event_key) VALUES (?)", (event_key,)
            )
            return cur.rowcount == 1

    def finish_callback_event(self, event_key, error=None):
        status = "failed" if error else "processed"
        self.execute(
            """UPDATE callback_events
               SET status = ?, error = ?, processed_at = CURRENT_TIMESTAMP
               WHERE event_key = ?""",
            (status, error, event_key),
        )

    def record_channel_contacts(self, contacts):
        added = []
        with self.connect() as conn:
            for contact in contacts:
                channel_user_id = str(contact.get("user_id") or "").strip()
                if not channel_user_id.startswith("788"):
                    continue
                name = str(contact.get("name") or "微信用户").strip()
                cur = conn.execute(
                    "INSERT OR IGNORE INTO channel_contacts (channel_user_id, name) VALUES (?, ?)",
                    (channel_user_id, name),
                )
                conn.execute(
                    "UPDATE channel_contacts SET name = ?, last_seen_at = CURRENT_TIMESTAMP WHERE channel_user_id = ?",
                    (name, channel_user_id),
                )
                if cur.rowcount == 1:
                    added.append({"user_id": channel_user_id, "name": name})
        return added
