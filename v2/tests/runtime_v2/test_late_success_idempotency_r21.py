"""R2.1 contracts for timeout/late-completion idempotency races."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from auto_fault_agent.harness import AgentHarness, HarnessConfig
from auto_fault_agent.schemas import ToolResult


class LateDispatcher:
    def __init__(self, gate=None):
        self.gate = gate
        self.started = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0
        self.operations = {}
        self.dut = self
        self.active = None
        self.state = "NORMAL"
        self.version = 1
        self.side_effects = 0

    def snapshot(self):
        return {"active": self.active, "state": self.state, "version": self.version}

    def dispatch_operation(self, name, arguments, operation_id, idempotency_key):
        with self.lock:
            if operation_id in self.operations:
                return self.operations[operation_id]
            self.calls += 1
        self.started.set()
        if self.gate is not None:
            self.gate.wait(2)
        with self.lock:
            self.side_effects += 1
            self.active = arguments["fault_id"]
            self.state = "FAULT_INJECTED"
            self.version += 1
            result = ToolResult(
                tool_call_id=operation_id,
                tool_name=name,
                success=True,
                result={"fault_id": self.active, "state": self.state},
                latency_ms=0,
            )
            self.operations[operation_id] = result
        self.finished.set()
        return result

    def query_operation(self, operation_id):
        return self.operations.get(operation_id)


def cfg(timeout=0.01):
    return HarnessConfig(
        timeout_seconds=timeout,
        max_retries=0,
        enable_timeout=True,
        enable_retry=True,
        enable_checkpoint=False,
    )


def completion_event(ledger):
    """Signal only after the background callback commits its ledger update."""
    committed = threading.Event()
    original = ledger.finish

    def finish(*args, **kwargs):
        value = original(*args, **kwargs)
        committed.set()
        return value

    ledger.finish = finish
    return committed


def test_timeout_late_success_duplicate_reuses_completed_action(tmp_path):
    gate = threading.Event()
    dispatcher = LateDispatcher(gate)
    harness = AgentHarness(dispatcher, tmp_path, cfg())
    committed = completion_event(harness.ledger)
    context = harness.new_context("session", "task")

    unknown = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    logical_id = context.current_logical_action_id
    operation_id = context.current_operation_id
    gate.set()
    assert dispatcher.finished.wait(1)
    assert committed.wait(1)
    assert harness.ledger.get_action(logical_id)["action_status"] == "SUCCEEDED"

    duplicate = harness.execute(
        "inject_fault", {"fault_id": "F001"}, context,
        logical_action_id=logical_id,
    )
    actions = harness.ledger.list_actions("session", "task")
    assert unknown.error["type"] == "OutcomeUnknown"
    assert duplicate.success
    assert len(actions) == 1
    assert actions[0]["logical_action_id"] == logical_id
    assert actions[0]["operation_id"] == operation_id
    assert len(dispatcher.operations) == dispatcher.calls == dispatcher.side_effects == 1


def test_duplicate_while_unknown_does_not_start_second_operation(tmp_path):
    gate = threading.Event()
    dispatcher = LateDispatcher(gate)
    harness = AgentHarness(dispatcher, tmp_path, cfg())
    committed = completion_event(harness.ledger)
    context = harness.new_context("session", "task")

    first = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    duplicate = harness.execute(
        "inject_fault", {"fault_id": "F001"}, context,
        logical_action_id=context.current_logical_action_id,
    )
    assert first.error["type"] == duplicate.error["type"] == "OutcomeUnknown"
    assert len(harness.ledger.list_actions("session", "task")) == 1
    assert dispatcher.calls == 1

    gate.set()
    assert dispatcher.finished.wait(1)
    assert committed.wait(1)
    assert harness.ledger.get_action(context.current_logical_action_id)["action_status"] == "SUCCEEDED"
    assert dispatcher.side_effects == 1


def test_concurrent_same_logical_identity_claims_once(tmp_path):
    gate = threading.Event()
    dispatcher = LateDispatcher(gate)
    first = AgentHarness(dispatcher, tmp_path, cfg(timeout=1))
    second = AgentHarness(dispatcher, tmp_path, cfg(timeout=1))
    c1 = first.new_context("session", "task")
    c2 = second.new_context("session", "task")

    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(
            first.execute, "inject_fault", {"fault_id": "F001"}, c1,
            logical_action_id="shared-action",
        )
        assert dispatcher.started.wait(1)
        duplicate = second.execute(
            "inject_fault", {"fault_id": "F001"}, c2,
            logical_action_id="shared-action",
        )
        gate.set()
        completed = future.result()

    actions = first.ledger.list_actions("session", "task")
    assert completed.success
    assert duplicate.error["type"] == "ActionInProgress"
    assert len(actions) == len(dispatcher.operations) == dispatcher.calls == dispatcher.side_effects == 1


def test_same_tool_arguments_with_distinct_logical_ids_remain_distinct(tmp_path):
    dispatcher = LateDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, cfg(timeout=1))
    context = harness.new_context("session", "task")

    one = harness.execute(
        "inject_fault", {"fault_id": "F001"}, context, logical_action_id="action-one"
    )
    two = harness.execute(
        "inject_fault", {"fault_id": "F001"}, context, logical_action_id="action-two"
    )
    actions = harness.ledger.list_actions("session", "task")
    assert one.success and two.success
    assert len(actions) == len({row["operation_id"] for row in actions}) == 2
    assert dispatcher.calls == dispatcher.side_effects == 2


def test_late_timeout_marker_cannot_overwrite_success(tmp_path):
    dispatcher = LateDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, cfg(timeout=1))
    context = harness.new_context("session", "task")
    result = harness.execute(
        "inject_fault", {"fault_id": "F001"}, context,
        logical_action_id="monotonic-action",
    )
    action = harness.ledger.get_action("monotonic-action")
    attempt = harness.ledger.attempts("monotonic-action")[0]

    harness.ledger.mark_timeout(
        "monotonic-action", attempt["attempt_id"],
        {"type": "OutcomeUnknown", "message": "late timeout"},
    )
    current = harness.ledger.get_action("monotonic-action")
    assert result.success
    assert current["action_status"] == "SUCCEEDED"
    assert current["result_json"] == action["result_json"]
    assert len(harness.ledger.list_actions("session", "task")) == 1
