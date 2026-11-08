from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskLifecycleState(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_TOOL = "WAITING_TOOL"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    CANCELLED = "CANCELLED"
    FAILED_INTERNAL = "FAILED_INTERNAL"


TERMINAL_TASK_STATES = frozenset(
    {
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.BUDGET_EXHAUSTED,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.FAILED_INTERNAL,
    }
)


_ALLOWED_TRANSITIONS = {
    TaskLifecycleState.CREATED: {
        TaskLifecycleState.RUNNING,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.FAILED_INTERNAL,
    },
    TaskLifecycleState.RUNNING: {
        TaskLifecycleState.WAITING_TOOL,
        TaskLifecycleState.VERIFYING,
        TaskLifecycleState.BUDGET_EXHAUSTED,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.FAILED_INTERNAL,
    },
    TaskLifecycleState.WAITING_TOOL: {
        TaskLifecycleState.RUNNING,
        TaskLifecycleState.BUDGET_EXHAUSTED,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.FAILED_INTERNAL,
    },
    TaskLifecycleState.VERIFYING: {
        TaskLifecycleState.RUNNING,
        TaskLifecycleState.COMPLETED,
        TaskLifecycleState.BLOCKED,
        TaskLifecycleState.BUDGET_EXHAUSTED,
        TaskLifecycleState.CANCELLED,
        TaskLifecycleState.FAILED_INTERNAL,
    },
}


@dataclass
class TaskLifecycle:
    state: TaskLifecycleState = TaskLifecycleState.CREATED
    revision: int = 0
    reason: str | None = None

    @property
    def done(self) -> bool:
        return self.state in TERMINAL_TASK_STATES

    def transition(self, target: TaskLifecycleState, reason: str) -> None:
        if self.done:
            raise RuntimeError(f"terminal task cannot transition from {self.state.value}")
        allowed = _ALLOWED_TRANSITIONS.get(self.state, set())
        if target not in allowed:
            raise RuntimeError(
                f"invalid task lifecycle transition: {self.state.value} -> {target.value}"
            )
        self.state = target
        self.reason = reason
        self.revision += 1
