"""The smallest possible embedding database: one SQLite file, vectors stored as BLOBs.

Search is exact (cosine over all rows with NumPy), which is plenty for thousands of memories.
Delete server/data/legacy.db to start again from empty.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

import numpy as np

PATH = Path(os.getenv("LEGACY_DATA") or Path(__file__).resolve().parent / "data") / "legacy.db"
PATH.parent.mkdir(parents=True, exist_ok=True)
_lock = threading.Lock()
_con = sqlite3.connect(PATH, check_same_thread=False)
_con.executescript("""
CREATE TABLE IF NOT EXISTS memories(
  id TEXT PRIMARY KEY, kind TEXT, title TEXT, content TEXT,
  dim INTEGER, vector BLOB, record TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
""")
_con.commit()


def save(m):
    rec = {k: v for k, v in m.items() if k != "vec"}
    vec = m.get("vec")
    blob = np.asarray(vec, dtype=np.float32).tobytes() if vec is not None else None
    with _lock:
        _con.execute(
            "INSERT INTO memories(id,kind,title,content,dim,vector,record) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,title=excluded.title,content=excluded.content,"
            "dim=excluded.dim,vector=excluded.vector,record=excluded.record",
            (m["id"], m.get("kind"), m.get("title"), m.get("embed_text", ""),
             len(vec) if vec is not None else None, blob, json.dumps(rec, ensure_ascii=False)))
        _con.commit()


def load_all():
    out = {}
    with _lock:
        rows = _con.execute("SELECT record,vector FROM memories ORDER BY created_at").fetchall()
    for rec, blob in rows:
        m = json.loads(rec)
        if blob:
            m["vec"] = np.frombuffer(blob, dtype=np.float32).copy()
        out[m["id"]] = m
    return out


def kv_get(key, default=None):
    with _lock:
        row = _con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(key, value):
    with _lock:
        _con.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, json.dumps(value, ensure_ascii=False)))
        _con.commit()


def size_kb():
    return round(PATH.stat().st_size / 1024, 1)
