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
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    default_push_hour INTEGER NOT NULL DEFAULT 9,
    payment_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS user_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'trial',
    preferred_hour INTEGER NOT NULL DEFAULT 9,
    trial_ends_at TEXT,
    paid_until TEXT,
    current_content_id INTEGER,
    last_push_date TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, product_key)
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
    enabled INTEGER NOT NULL DEFAULT 1,
    product_key TEXT NOT NULL DEFAULT 'ai_english',
    content_type TEXT NOT NULL DEFAULT 'knowledge_card',
    review_status TEXT NOT NULL DEFAULT 'approved',
    source_url TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL DEFAULT ''
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
            self._migrate(conn)
            self._seed_products(conn)
            for item in content:
                conn.execute(
                    """INSERT OR IGNORE INTO content_items
                    (term, meaning, explanation, example_en, example_cn, question,
                     options_json, answer, difficulty, topic, product_key, content_type,
                     review_status, source_url, image_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (item["term"], item["meaning"], item["explanation"],
                     item["example_en"], item["example_cn"], item["question"],
                     json.dumps(item["options"], ensure_ascii=False), item["answer"],
                     item["difficulty"], item["topic"], item.get("product_key", "ai_english"),
                     item.get("content_type", "knowledge_card"),
                     item.get("review_status", "approved"), item.get("source_url", ""),
                     item.get("image_url", "")),
                )

    def _migrate(self, conn):
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(content_items)")}
        additions = {
            "product_key": "TEXT NOT NULL DEFAULT 'ai_english'",
            "content_type": "TEXT NOT NULL DEFAULT 'knowledge_card'",
            "review_status": "TEXT NOT NULL DEFAULT 'approved'",
            "source_url": "TEXT NOT NULL DEFAULT ''",
            "image_url": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in additions.items():
            if column not in columns:
                conn.execute(f"ALTER TABLE content_items ADD COLUMN {column} {definition}")
        conn.execute("UPDATE content_items SET product_key = 'ai_english' WHERE product_key = ''")
        conn.execute("UPDATE content_items SET content_type = 'knowledge_card' WHERE content_type = ''")
        conn.execute("UPDATE content_items SET review_status = 'approved' WHERE review_status = ''")

    def _seed_products(self, conn):
        products = [
            (
                "ai_english",
                "AI 英语学习",
                "围绕 AI 行业常用英文词汇和表达的每日学习服务。",
                9,
                "",
            ),
            (
                "ai_briefing",
                "AI 行业早报",
                "面向 AI 从业者的行业动态、产品更新和趋势解读。",
                8,
                "",
            ),
        ]
        for product in products:
            conn.execute(
                """INSERT OR IGNORE INTO products
                (product_key, name, description, default_push_hour, payment_url)
                VALUES (?, ?, ?, ?, ?)""",
                product,
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
