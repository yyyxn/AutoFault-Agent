from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..tools import ToolDispatcher
from .executor import AgentHarness


@dataclass
class SessionRuntime:
    dispatcher: object
    harness: AgentHarness
    context: object


class SessionManager:
    """Single-process session isolation; no distributed coordination claims."""

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions = {}

    def create(self, session_id, task_id):
        if session_id in self._sessions:
            raise ValueError(f"session already exists: {session_id}")
        dispatcher = ToolDispatcher()
        harness = AgentHarness(dispatcher, self.root / session_id)
        runtime = SessionRuntime(dispatcher, harness, harness.new_context(session_id, task_id))
        self._sessions[session_id] = runtime
        return runtime

    def get(self, session_id):
        return self._sessions[session_id]
