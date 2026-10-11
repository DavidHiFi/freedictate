"""Dictation history in SQLite. Stays on this PC; the user can turn it off or clear it."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .log import log
from .textproc import word_count

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id      INTEGER PRIMARY KEY,
    ts      REAL NOT NULL,
    seconds REAL NOT NULL DEFAULT 0,
    words   INTEGER NOT NULL DEFAULT 0,
    text    TEXT NOT NULL,
    model   TEXT NOT NULL DEFAULT '',
    app     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS entries_ts ON entries(ts);
"""


@dataclass(frozen=True)
class Entry:
    id: int
    ts: float
    seconds: float
    words: int
    text: str
    model: str
    app: str


class History:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.HISTORY_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._listeners: list = []

    def on_change(self, fn) -> None:
        self._listeners.append(fn)

    def _changed(self) -> None:
        for fn in list(self._listeners):
            try:
                fn()
            except Exception:
                log.exception("History listener failed")

    def add(self, text: str, seconds: float, model: str = "", app: str = "", ts: float | None = None) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO entries(ts, seconds, words, text, model, app) VALUES (?,?,?,?,?,?)",
                (ts or time.time(), seconds, word_count(text), text, model, app))
            rid = cur.lastrowid
        self._changed()
        return rid

    def _rows(self, sql: str, args: tuple) -> list[Entry]:
        with self._lock:
            return [Entry(*r) for r in self._db.execute(sql, args).fetchall()]

    def recent(self, limit: int = 5) -> list[Entry]:
        return self._rows("SELECT id, ts, seconds, words, text, model, app FROM entries ORDER BY ts DESC LIMIT ?", (limit,))

    def search(self, query: str = "", limit: int = 200, offset: int = 0) -> list[Entry]:
        if query.strip():
            like = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            return self._rows("SELECT id, ts, seconds, words, text, model, app FROM entries "
                              "WHERE text LIKE ? ESCAPE '\\' ORDER BY ts DESC LIMIT ? OFFSET ?",
                              (like, limit, offset))
        return self._rows("SELECT id, ts, seconds, words, text, model, app FROM entries "
                          "ORDER BY ts DESC LIMIT ? OFFSET ?", (limit, offset))

    def count(self, query: str = "") -> int:
        with self._lock:
            if query.strip():
                like = "%" + query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
                return self._db.execute("SELECT COUNT(*) FROM entries WHERE text LIKE ? ESCAPE '\\'", (like,)).fetchone()[0]
            return self._db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]

    def delete(self, entry_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self._changed()

    def clear(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM entries")
            self._db.execute("VACUUM")
        self._changed()

    def prune(self, days: int) -> int:
        if days <= 0:
            return 0
        with self._lock:
            n = self._db.execute("DELETE FROM entries WHERE ts < ?", (time.time() - days * 86400,)).rowcount
        if n:
            self._changed()
        return n

    def stats(self) -> dict:
        week = time.time() - 7 * 86400
        with self._lock:
            total = self._db.execute("SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(seconds),0) FROM entries").fetchone()
            recent = self._db.execute("SELECT COALESCE(SUM(words),0) FROM entries WHERE ts >= ?", (week,)).fetchone()
        return {"count": total[0], "words": total[1], "seconds": total[2], "words_week": recent[0]}

    def export_text(self, target: Path) -> int:
        rows = self._rows("SELECT id, ts, seconds, words, text, model, app FROM entries ORDER BY ts", ())
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            for e in rows:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e.ts))} [{e.seconds:.1f}s] {e.text}\n")
        return len(rows)

    def import_legacy_log(self, path: Path) -> int:
        """Import a v1/v2 transcripts.log ("YYYY-MM-DD HH:MM:SS [12.3s] text")."""
        pat = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[([\d.]+)s\] (.+)$")
        rows = []
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line.rstrip("\n"))
                if m:
                    ts = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                    text = m.group(3).strip()
                    rows.append((ts, float(m.group(2)), word_count(text), text, "", ""))
        with self._lock:
            self._db.execute("BEGIN")
            self._db.executemany("INSERT INTO entries(ts, seconds, words, text, model, app) VALUES (?,?,?,?,?,?)", rows)
            self._db.execute("COMMIT")
        self._changed()
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._db.close()
