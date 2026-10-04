"""Cola local SQLite (offline-first). Solo librería estándar."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel TEXT DEFAULT 'manual', chat_id TEXT, lang TEXT,
  original_text TEXT, translated_text TEXT, intent TEXT, confidence REAL,
  needs_human INTEGER DEFAULT 0, proposed_response TEXT,
  final_response TEXT, final_is_es INTEGER DEFAULT 0,
  status TEXT DEFAULT 'pending',            -- entrante: pending | answered | synced; saliente: approved | synced
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, place_id TEXT NOT NULL, author TEXT NOT NULL,
  rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), text TEXT NOT NULL, lang TEXT,
  status TEXT DEFAULT 'published',          -- published | hidden
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_reviews_place ON reviews(place_id);
"""
FIELDS = {"translated_text", "final_response", "final_is_es", "status", "lang", "proposed_response"}
# Columnas añadidas para el chat (bases de datos viejas se actualizan solas al abrirse).
MIGRATE = {"name": "TEXT", "host_text": "TEXT"}
_ready = set()


def _path():
    default = Path(__file__).resolve().parent.parent / "data" / "local_app.db"
    return os.getenv("DATABASE_PATH", str(default))


@contextmanager
def conn():
    c = sqlite3.connect(_path())
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        if _path() not in _ready:
            have = {r[1] for r in c.execute("PRAGMA table_info(messages)")}
            for col, typ in MIGRATE.items():
                if col not in have:
                    c.execute(f"ALTER TABLE messages ADD COLUMN {col} {typ}")
            c.execute("UPDATE messages SET chat_id='m'||id WHERE chat_id IS NULL")  # cada mensaje viejo = su propio chat
            _ready.add(_path())
        yield c
        c.commit()
    finally:
        c.close()


def add_message(**f):
    cols = ",".join(f)
    with conn() as c:
        cur = c.execute(f"INSERT INTO messages({cols}) VALUES({','.join('?' * len(f))})", list(f.values()))
        return cur.lastrowid


def get(mid):
    with conn() as c:
        r = c.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
        return dict(r) if r else None


def list_messages(status=None):
    with conn() as c:
        q, a = ("SELECT * FROM messages WHERE status=? ORDER BY id", (status,)) if status else \
               ("SELECT * FROM messages ORDER BY id DESC LIMIT 50", ())
        return [dict(r) for r in c.execute(q, a)]


def update(mid, **f):
    f = {k: v for k, v in f.items() if k in FIELDS}
    with conn() as c:
        c.execute(f"UPDATE messages SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), mid])


def meta_get(k):
    with conn() as c:
        r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else None


def meta_set(k, v):
    with conn() as c:
        c.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))


# ---------- Reseñas ----------
def add_review(place_id, author, rating, text, lang=None):
    with conn() as c:
        return c.execute("INSERT INTO reviews(place_id,author,rating,text,lang) VALUES(?,?,?,?,?)",
                         (str(place_id), author, rating, text, lang)).lastrowid


def list_reviews(place_id, limit=50):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT id,author,rating,text,lang,created_at FROM reviews WHERE place_id=? AND status='published' "
            "ORDER BY id DESC LIMIT ?", (str(place_id), limit))]


def review_stats():
    """{place_id: (promedio, cantidad)} solo de reseñas publicadas."""
    with conn() as c:
        return {r[0]: (r[1], r[2]) for r in c.execute(
            "SELECT place_id, AVG(rating), COUNT(*) FROM reviews WHERE status='published' GROUP BY place_id")}


def has_review(place_id, author, text):
    with conn() as c:
        return c.execute("SELECT 1 FROM reviews WHERE place_id=? AND author=? AND text=? AND status='published'",
                         (str(place_id), author, text)).fetchone() is not None


def recent_reviews(seconds=60):
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM reviews WHERE created_at >= datetime('now', ?)",
                         (f"-{int(seconds)} seconds",)).fetchone()[0]


def hide_review(rid):
    with conn() as c:
        return c.execute("UPDATE reviews SET status='hidden' WHERE id=?", (rid,)).rowcount


# ---------- Chat ----------
def chat_rows(channel, chat_id):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM messages WHERE channel=? AND chat_id=? ORDER BY id",
                                           (channel, chat_id))]


def recent_rows(limit=1000):
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,))]


def mark_answered(channel, chat_id):
    """Al responder en el chat, los mensajes pendientes de esa conversación quedan atendidos."""
    with conn() as c:
        c.execute("UPDATE messages SET status='answered' WHERE channel=? AND chat_id=? AND status='pending'",
                  (channel, chat_id))


def recent_in_chat(chat_id, seconds=60):
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM messages WHERE chat_id=? AND original_text IS NOT NULL "
                         "AND created_at >= datetime('now', ?)", (chat_id, f"-{int(seconds)} seconds")).fetchone()[0]


def purge_old(days):
    """Privacidad: borra mensajes ya enviados o atendidos con más de N días."""
    with conn() as c:
        return c.execute("DELETE FROM messages WHERE status IN ('synced','answered') AND created_at < datetime('now', ?)",
                         (f"-{int(days)} days",)).rowcount
