"""SQLite persistence layer.

Simple, dependency-free storage for conversations, events, workspaces,
LLM profiles and settings, following the data model in the product spec (§9).
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import utcnow

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS workspaces (
    id           TEXT PRIMARY KEY,
    path         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL DEFAULT 'local',
    name         TEXT NOT NULL,
    git_remote   TEXT,
    last_opened  TEXT NOT NULL,
    container_id TEXT
);

CREATE TABLE IF NOT EXISTS llm_profiles (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    base_url        TEXT,
    api_key_ref     TEXT,
    temperature     REAL NOT NULL DEFAULT 0,
    max_tokens      INTEGER NOT NULL DEFAULT 4096,
    timeout_seconds INTEGER NOT NULL DEFAULT 300,
    retries         INTEGER NOT NULL DEFAULT 2,
    extra_headers   TEXT NOT NULL DEFAULT '{}',
    is_default      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    workspace_id     TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    mode             TEXT NOT NULL DEFAULT 'local',
    llm_profile_id   TEXT,
    status           TEXT NOT NULL DEFAULT 'idle',
    pinned           INTEGER NOT NULL DEFAULT 0,
    shell            TEXT,
    confirm_risky    INTEGER NOT NULL DEFAULT 1,
    system_suffix    TEXT,
    cost_total       REAL NOT NULL DEFAULT 0,
    tokens_total     INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    type            TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    ts              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_conv_seq ON events(conversation_id, seq);

CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    decision        TEXT,
    remember        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


class Database:
    """Thread-safe wrapper around a single SQLite connection.

    The agent runs in a background thread while FastAPI serves requests, so every
    access goes through a re-entrant lock; SQLite itself is opened with
    ``check_same_thread=False``.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ------------------------------------------------------------ generic
    def query_all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))

    # --------------------------------------------------------- workspaces
    def upsert_workspace(self, data: dict[str, Any]) -> dict[str, Any]:
        existing = self.query_one("SELECT * FROM workspaces WHERE path = ?", (data["path"],))
        if existing:
            wid = existing["id"]
            self.execute("UPDATE workspaces SET last_opened = ?, kind = ? WHERE id = ?", (
                utcnow(),
                data.get("kind", existing["kind"]),
                wid,
            ))
            return dict(self.query_one("SELECT * FROM workspaces WHERE id = ?", (wid,)))
        wid = data.get("id") or new_id()
        self.execute(
            "INSERT INTO workspaces (id, path, kind, name, git_remote, last_opened, container_id)"
            " VALUES (?,?,?,?,?,?,?)",
            (
                wid,
                data["path"],
                data.get("kind", "local"),
                data.get("name") or Path(data["path"]).name or data["path"],
                data.get("git_remote"),
                utcnow(),
                data.get("container_id"),
            ),
        )
        return dict(self.query_one("SELECT * FROM workspaces WHERE id = ?", (wid,)))

    def get_workspace(self, wid: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM workspaces WHERE id = ?", (wid,))
        return dict(row) if row else None

    def list_workspaces(self) -> list[dict[str, Any]]:
        rows = self.query_all("SELECT * FROM workspaces ORDER BY last_opened DESC")
        return [dict(r) for r in rows]

    # ---------------------------------------------------------- llm profiles
    def insert_llm_profile(self, data: dict[str, Any]) -> dict[str, Any]:
        pid = new_id()
        self.execute(
            "INSERT INTO llm_profiles (id, name, provider, model, base_url, api_key_ref, temperature,"
            " max_tokens, timeout_seconds, retries, extra_headers, is_default, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                data["name"],
                data["provider"],
                data["model"],
                data.get("base_url"),
                data.get("api_key_ref"),
                data.get("temperature", 0.0),
                data.get("max_tokens", 4096),
                data.get("timeout_seconds", 300),
                data.get("retries", 2),
                json.dumps(data.get("extra_headers") or {}),
                1 if data.get("is_default") else 0,
                utcnow(),
            ),
        )
        return self.get_llm_profile(pid)  # type: ignore[return-value]

    def update_llm_profile(self, pid: str, data: dict[str, Any]) -> dict[str, Any] | None:
        current = self.get_llm_profile(pid)
        if current is None:
            return None
        merged = {**current, **{k: v for k, v in data.items() if v is not None}}
        self.execute(
            "UPDATE llm_profiles SET name=?, provider=?, model=?, base_url=?, api_key_ref=?,"
            " temperature=?, max_tokens=?, timeout_seconds=?, retries=?, extra_headers=?, is_default=?"
            " WHERE id=?",
            (
                merged["name"],
                merged["provider"],
                merged["model"],
                merged.get("base_url"),
                merged.get("api_key_ref"),
                merged.get("temperature", 0.0),
                merged.get("max_tokens", 4096),
                merged.get("timeout_seconds", 300),
                merged.get("retries", 2),
                json.dumps(merged.get("extra_headers") or {}),
                1 if merged.get("is_default") else 0,
                pid,
            ),
        )
        return self.get_llm_profile(pid)

    def get_llm_profile(self, pid: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM llm_profiles WHERE id = ?", (pid,))
        return _profile_row(row) if row else None

    def list_llm_profiles(self) -> list[dict[str, Any]]:
        rows = self.query_all("SELECT * FROM llm_profiles ORDER BY created_at ASC")
        return [_profile_row(r) for r in rows]

    def delete_llm_profile(self, pid: str) -> None:
        self.execute("DELETE FROM llm_profiles WHERE id = ?", (pid,))

    def clear_default_llm_profiles(self) -> None:
        self.execute("UPDATE llm_profiles SET is_default = 0", ())

    # -------------------------------------------------------- conversations
    def insert_conversation(self, data: dict[str, Any]) -> dict[str, Any]:
        cid = new_id()
        now = utcnow()
        self.execute(
            "INSERT INTO conversations (id, title, workspace_id, mode, llm_profile_id, status, pinned,"
            " shell, confirm_risky, system_suffix, created_at, updated_at)"
            " VALUES (?,?,?,?,?,'idle',0,?,?,?,?,?)",
            (
                cid,
                data["title"],
                data["workspace_id"],
                data["mode"],
                data.get("llm_profile_id"),
                data.get("shell"),
                1 if data.get("confirm_risky_actions", True) else 0,
                data.get("system_prompt_suffix"),
                now,
                now,
            ),
        )
        return self.get_conversation(cid)  # type: ignore[return-value]

    def get_conversation(self, cid: str) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM conversations WHERE id = ?", (cid,))
        if not row:
            return None
        data = dict(row)
        pending = self.query_one(
            "SELECT payload_json FROM approvals WHERE conversation_id = ? AND decision IS NULL"
            " ORDER BY created_at DESC LIMIT 1",
            (cid,),
        )
        data["pending_approval"] = json.loads(pending["payload_json"]) if pending else None
        return data

    def list_conversations(self, search: str | None = None) -> list[dict[str, Any]]:
        if search:
            rows = self.query_all(
                "SELECT * FROM conversations WHERE title LIKE ? ORDER BY pinned DESC, updated_at DESC",
                (f"%{search}%",),
            )
        else:
            rows = self.query_all("SELECT * FROM conversations ORDER BY pinned DESC, updated_at DESC")
        result = []
        for row in rows:
            data = dict(row)
            pending = self.query_one(
                "SELECT payload_json FROM approvals WHERE conversation_id = ? AND decision IS NULL"
                " ORDER BY created_at DESC LIMIT 1",
                (data["id"],),
            )
            data["pending_approval"] = json.loads(pending["payload_json"]) if pending else None
            result.append(data)
        return result

    def update_conversation(self, cid: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "title",
            "pinned",
            "llm_profile_id",
            "status",
            "cost_total",
            "tokens_total",
            "system_suffix",
        }
        sets, params = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"cannot update conversation field {key!r}")
            sets.append(f"{key} = ?")
            params.append(int(value) if isinstance(value, bool) else value)
        sets.append("updated_at = ?")
        params.append(utcnow())
        params.append(cid)
        self.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id = ?", params)

    def delete_conversation(self, cid: str) -> None:
        self.execute("DELETE FROM events WHERE conversation_id = ?", (cid,))
        self.execute("DELETE FROM approvals WHERE conversation_id = ?", (cid,))
        self.execute("DELETE FROM conversations WHERE id = ?", (cid,))

    # --------------------------------------------------------------- events
    def append_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            row = self.query_one(
                "SELECT COALESCE(MAX(seq), 0) AS s FROM events WHERE conversation_id = ?",
                (event["conversation_id"],),
            )
            seq = (row["s"] if row else 0) + 1
            event = {**event, "seq": seq}
            cur = self._conn.execute(
                "INSERT INTO events (conversation_id, seq, type, payload_json, ts) VALUES (?,?,?,?,?)",
                (
                    event["conversation_id"],
                    seq,
                    event["type"],
                    json.dumps(event, default=str),
                    event.get("ts") or utcnow(),
                ),
            )
            self._conn.commit()
            event["id"] = cur.lastrowid
            return event

    def list_events(self, cid: str, after_seq: int = 0) -> list[dict[str, Any]]:
        rows = self.query_all(
            "SELECT payload_json FROM events WHERE conversation_id = ? AND seq > ? ORDER BY seq ASC",
            (cid, after_seq),
        )
        return [json.loads(r["payload_json"]) for r in rows]

    # ------------------------------------------------------------ approvals
    def create_approval(self, cid: str, payload: dict[str, Any]) -> dict[str, Any]:
        aid = payload.get("id") or new_id()
        created = utcnow()
        record = {**payload, "id": aid, "conversation_id": cid, "created_at": created}
        self.execute(
            "INSERT INTO approvals (id, conversation_id, payload_json, created_at) VALUES (?,?,?,?)",
            (aid, cid, json.dumps(record), created),
        )
        return record

    def decide_approval(self, aid: str, approved: bool, remember: bool = False) -> dict[str, Any] | None:
        row = self.query_one("SELECT * FROM approvals WHERE id = ?", (aid,))
        if not row:
            return None
        self.execute(
            "UPDATE approvals SET decision = ?, remember = ? WHERE id = ?",
            ("approved" if approved else "denied", 1 if remember else 0, aid),
        )
        return json.loads(row["payload_json"])

    def get_approval_decision(self, aid: str) -> str | None:
        row = self.query_one("SELECT decision FROM approvals WHERE id = ?", (aid,))
        return row["decision"] if row and row["decision"] else None

    def list_remembered_commands(self, cid: str) -> set[str]:
        rows = self.query_all(
            "SELECT payload_json FROM approvals WHERE conversation_id = ? AND remember = 1 AND decision = 'approved'",
            (cid,),
        )
        remembered = set()
        for row in rows:
            payload = json.loads(row["payload_json"])
            cmd = (payload.get("action") or {}).get("args", {}).get("command")
            if cmd:
                remembered.add(cmd)
        return remembered

    # ------------------------------------------------------------- settings
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.query_one("SELECT value_json FROM settings WHERE key = ?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings (key, value_json) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, json.dumps(value)),
        )


def _profile_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["extra_headers"] = json.loads(data.get("extra_headers") or "{}")
    data["is_default"] = bool(data.get("is_default"))
    return data


def new_id() -> str:
    return uuid.uuid4().hex
