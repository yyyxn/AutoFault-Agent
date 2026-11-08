from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class LogicalActionScopeConflict(RuntimeError):
    """A globally unique logical action ID was presented in another scope."""


class ActionLedger:
    """Small transactional ledger for logical actions and their attempts."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS logical_actions (
                    logical_action_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    operation_id TEXT NOT NULL,
                    action_status TEXT NOT NULL,
                    result_json TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(session_id, task_id, idempotency_key),
                    UNIQUE(session_id, task_id, operation_id)
                );
                CREATE TABLE IF NOT EXISTS tool_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    logical_action_id TEXT NOT NULL,
                    attempt_number INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    attempt_status TEXT NOT NULL,
                    error_code TEXT,
                    error_message TEXT,
                    result_reference TEXT,
                    FOREIGN KEY(logical_action_id) REFERENCES logical_actions(logical_action_id),
                    UNIQUE(logical_action_id, attempt_number)
                );
                CREATE INDEX IF NOT EXISTS idx_actions_scope
                ON logical_actions(session_id, task_id, action_status);
                """
            )

    @staticmethod
    def identity(session_id, task_id, tool_name, arguments, logical_action_id=None, idempotency_key=None):
        arguments_json = canonical_json(arguments)
        arguments_hash = hashlib.sha256(arguments_json.encode()).hexdigest()
        if logical_action_id is None:
            raw = f"{session_id}\0{task_id}\0{tool_name}\0{arguments_hash}"
            logical_action_id = "act_" + hashlib.sha256(raw.encode()).hexdigest()[:24]
        if idempotency_key is None:
            raw = f"{session_id}\0{task_id}\0{logical_action_id}"
            idempotency_key = "idem_" + hashlib.sha256(raw.encode()).hexdigest()[:32]
        operation_id = "op_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        return logical_action_id, idempotency_key, operation_id, arguments_json, arguments_hash

    def get_or_create_action(self, session_id, task_id, tool_name, arguments, *, logical_action_id=None, idempotency_key=None):
        logical_action_id, idempotency_key, operation_id, arguments_json, arguments_hash = self.identity(
            session_id, task_id, tool_name, arguments, logical_action_id, idempotency_key
        )
        now = utc_now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM logical_actions WHERE logical_action_id=?", (logical_action_id,)
            ).fetchone()
            if existing and (existing["session_id"] != session_id or existing["task_id"] != task_id):
                db.rollback()
                raise LogicalActionScopeConflict(
                    "logical_action_id already belongs to another session/task"
                )
            if existing and existing["idempotency_key"] != idempotency_key:
                db.rollback()
                raise RuntimeError("logical_action_id reused with a different idempotency key")
            db.execute(
                """INSERT OR IGNORE INTO logical_actions
                (logical_action_id,session_id,task_id,tool_name,arguments_json,arguments_hash,
                 idempotency_key,operation_id,action_status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (logical_action_id, session_id, task_id, tool_name, arguments_json, arguments_hash,
                 idempotency_key, operation_id, "PENDING", now, now),
            )
            row = db.execute(
                "SELECT * FROM logical_actions WHERE session_id=? AND task_id=? AND idempotency_key=?",
                (session_id, task_id, idempotency_key),
            ).fetchone()
            db.commit()
        if row is None or row["logical_action_id"] != logical_action_id:
            raise RuntimeError("idempotency key reused for a different logical action")
        if row["tool_name"] != tool_name or row["arguments_hash"] != arguments_hash:
            raise RuntimeError("idempotency key reused for a different logical action")
        return dict(row)

    def get_action(self, logical_action_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM logical_actions WHERE logical_action_id=?", (logical_action_id,)).fetchone()
        return dict(row) if row else None

    def get_action_by_idempotency_key(self, session_id, task_id, idempotency_key):
        """Resolve one logical action within its session/task idempotency scope."""
        with self._connect() as db:
            row = db.execute(
                """SELECT * FROM logical_actions
                WHERE session_id=? AND task_id=? AND idempotency_key=?""",
                (session_id, task_id, idempotency_key),
            ).fetchone()
        return dict(row) if row else None

    def list_actions(self, session_id, task_id=None):
        query = "SELECT * FROM logical_actions WHERE session_id=?"
        values = [session_id]
        if task_id is not None:
            query += " AND task_id=?"; values.append(task_id)
        query += " ORDER BY created_at, logical_action_id"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query, values).fetchall()]

    def claim(self, logical_action_id):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            action = db.execute("SELECT * FROM logical_actions WHERE logical_action_id=?", (logical_action_id,)).fetchone()
            if not action or action["action_status"] != "PENDING":
                db.rollback(); return None
            number = db.execute(
                "SELECT COALESCE(MAX(attempt_number),0)+1 FROM tool_attempts WHERE logical_action_id=?",
                (logical_action_id,),
            ).fetchone()[0]
            attempt_id = "att_" + uuid.uuid4().hex
            now = utc_now()
            db.execute(
                "INSERT INTO tool_attempts VALUES (?,?,?,?,?,?,?,?,?)",
                (attempt_id, logical_action_id, number, now, None, "RUNNING", None, None, None),
            )
            db.execute(
                "UPDATE logical_actions SET action_status='EXECUTING', updated_at=? WHERE logical_action_id=?",
                (now, logical_action_id),
            )
            db.commit()
        return {"attempt_id": attempt_id, "logical_action_id": logical_action_id, "attempt_number": number, "attempt_status": "RUNNING"}

    def finish(self, logical_action_id, attempt_id, action_status, *, result=None, error=None, attempt_status=None):
        if action_status not in {"SUCCEEDED", "FAILED", "OUTCOME_UNKNOWN", "PENDING"}:
            raise ValueError(action_status)
        attempt_status = attempt_status or action_status
        now = utc_now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE tool_attempts SET finished_at=?, attempt_status=?, error_code=?,
                error_message=?, result_reference=? WHERE attempt_id=?""",
                (now, attempt_status, (error or {}).get("type"), (error or {}).get("message"),
                 canonical_json(result) if result is not None else None, attempt_id),
            )
            db.execute(
                """UPDATE logical_actions SET action_status=?, result_json=?, error_json=?, updated_at=?
                WHERE logical_action_id=? AND action_status NOT IN ('SUCCEEDED','FAILED')""",
                (action_status, canonical_json(result) if result is not None else None,
                 canonical_json(error) if error is not None else None, now, logical_action_id),
            )
            db.commit()

    def force_status(self, logical_action_id, status):
        with self._connect() as db:
            db.execute("UPDATE logical_actions SET action_status=?, updated_at=? WHERE logical_action_id=?", (status, utc_now(), logical_action_id))

    def mark_timeout(self, logical_action_id, attempt_id, error):
        """Mark an in-flight call unknown without overwriting a late committed result."""
        now = utc_now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT action_status FROM logical_actions WHERE logical_action_id=?", (logical_action_id,)).fetchone()
            if row and row[0] == "EXECUTING":
                db.execute(
                    "UPDATE logical_actions SET action_status='OUTCOME_UNKNOWN',error_json=?,updated_at=? WHERE logical_action_id=?",
                    (canonical_json(error), now, logical_action_id),
                )
                db.execute(
                    "UPDATE tool_attempts SET attempt_status='OUTCOME_UNKNOWN',finished_at=?,error_code=?,error_message=? WHERE attempt_id=? AND attempt_status='RUNNING'",
                    (now, error.get("type"), error.get("message"), attempt_id),
                )
            db.commit()

    def mark_not_started(self, logical_action_id, attempt_id, reason="execution was not dispatched"):
        """Return a claimed action to PENDING only when no tool code ran."""
        now = utc_now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE tool_attempts SET attempt_status='FAILED',finished_at=?,error_code='NOT_STARTED',error_message=? WHERE attempt_id=? AND attempt_status='RUNNING'",
                (now, reason, attempt_id),
            )
            db.execute(
                "UPDATE logical_actions SET action_status='PENDING',updated_at=? WHERE logical_action_id=? AND action_status='EXECUTING'",
                (now, logical_action_id),
            )
            db.commit()

    def recover_incomplete(self, session_id, task_id=None):
        actions = [row for row in self.list_actions(session_id, task_id) if row["action_status"] == "EXECUTING"]
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for action in actions:
                now = utc_now()
                db.execute(
                    "UPDATE logical_actions SET action_status='OUTCOME_UNKNOWN',updated_at=? WHERE logical_action_id=?",
                    (now, action["logical_action_id"]),
                )
                db.execute(
                    """UPDATE tool_attempts SET attempt_status='OUTCOME_UNKNOWN',finished_at=?
                    WHERE logical_action_id=? AND attempt_status='RUNNING'""",
                    (now, action["logical_action_id"]),
                )
            db.commit()
        return len(actions)

    def attempts(self, logical_action_id):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tool_attempts WHERE logical_action_id=? ORDER BY attempt_number", (logical_action_id,)
            ).fetchall()]
