"""Deterministic R2 contracts for reliable side-effect execution."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from auto_fault_agent.harness import AgentHarness, HarnessConfig
from auto_fault_agent.harness.action_ledger import ActionLedger
from auto_fault_agent.harness.session_manager import SessionManager
from auto_fault_agent.schemas import ToolResult


class ControlledDUT:
    def __init__(self):
        self.active = None
        self.state = "NORMAL"
        self.version = 1
        self.side_effects = 0

    def snapshot(self):
        return {
            "active": self.active,
            "state": self.state,
            "version": self.version,
            "side_effects": self.side_effects,
        }

    def restore(self, value):
        self.active = value.get("active")
        self.state = value.get("state", "NORMAL")
        self.version = value.get("version", 1)
        self.side_effects = value.get("side_effects", 0)


class ControlledDispatcher:
    def __init__(self, *, gate=None, fail=False, mutate=True):
        self.dut = ControlledDUT()
        self.gate = gate
        self.started = threading.Event()
        self.finished = threading.Event()
        self.fail = fail
        self.mutate = mutate
        self.calls = 0
        self.operations = {}
        self.lock = threading.Lock()

    def dispatch_operation(self, name, arguments, operation_id, idempotency_key):
        with self.lock:
            if operation_id in self.operations:
                return self.operations[operation_id]
            self.calls += 1
        self.started.set()
        if self.gate is not None:
            self.gate.wait(2)
        if self.fail:
            result = ToolResult(
                tool_call_id=operation_id,
                tool_name=name,
                success=False,
                error={"type": "PermanentError", "message": "no effect"},
                latency_ms=0,
            )
        else:
            if self.mutate:
                self.dut.side_effects += 1
                self.dut.active = arguments.get("fault_id")
                self.dut.state = "FAULT_INJECTED"
                self.dut.version += 1
            result = ToolResult(
                tool_call_id=operation_id,
                tool_name=name,
                success=True,
                result={"fault_id": arguments.get("fault_id"), "state": self.dut.state},
                latency_ms=0,
            )
        with self.lock:
            self.operations[operation_id] = result
        self.finished.set()
        return result

    def dispatch(self, name, arguments):
        return self.dispatch_operation(name, arguments, f"legacy-{self.calls}", "legacy")

    def query_operation(self, operation_id):
        return self.operations.get(operation_id)


def config(timeout=0.05, retries=2):
    return HarnessConfig(
        timeout_seconds=timeout,
        max_retries=retries,
        enable_timeout=True,
        enable_retry=True,
        enable_checkpoint=True,
    )


def test_ledger_separates_logical_action_attempt_and_operation(tmp_path):
    ledger = ActionLedger(tmp_path / "ledger.sqlite3")
    action = ledger.get_or_create_action("s", "t", "inject_fault", {"fault_id": "F001"})
    attempt = ledger.claim(action["logical_action_id"])
    assert action["logical_action_id"] != attempt["attempt_id"]
    assert action["operation_id"] != attempt["attempt_id"]
    assert attempt["attempt_status"] == "RUNNING"


def test_confirmed_not_started_returns_action_to_pending(tmp_path):
    ledger = ActionLedger(tmp_path / "ledger.sqlite3")
    action = ledger.get_or_create_action("s", "t", "inject_fault", {"fault_id": "F001"})
    attempt = ledger.claim(action["logical_action_id"])
    ledger.mark_not_started(action["logical_action_id"], attempt["attempt_id"])
    assert ledger.get_action(action["logical_action_id"])["action_status"] == "PENDING"
    assert ledger.attempts(action["logical_action_id"])[0]["error_code"] == "NOT_STARTED"


def test_normal_success_and_cached_duplicate_have_one_side_effect(tmp_path):
    dispatcher = ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    first = harness.execute("inject_fault", {"fault_id": "F001"}, context, logical_action_id="same-action")
    second = harness.execute("inject_fault", {"fault_id": "F001"}, context, logical_action_id="same-action")
    assert first.success and second.success
    assert dispatcher.calls == dispatcher.dut.side_effects == 1
    assert harness.metrics["idempotency_intercepts"] == 1


def test_explicit_failure_records_failed_without_state_mutation(tmp_path):
    dispatcher = ControlledDispatcher(fail=True)
    harness = AgentHarness(dispatcher, tmp_path, config(retries=0))
    context = harness.new_context("s", "t")
    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    action = harness.ledger.list_actions("s", "t")[0]
    assert not result.success
    assert action["action_status"] == "FAILED"
    assert dispatcher.dut.side_effects == 0
    assert context.current_fault_id is None


def test_timeout_during_side_effect_is_unknown_and_not_blindly_retried(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate)
    harness = AgentHarness(dispatcher, tmp_path, config(timeout=0.01, retries=3))
    context = harness.new_context("s", "t")
    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    assert dispatcher.started.is_set()
    assert result.error["type"] == "OutcomeUnknown"
    assert dispatcher.calls == 1
    gate.set()
    assert dispatcher.finished.wait(1)
    assert dispatcher.dut.side_effects == 1


def test_timeout_then_late_success_reconciles_without_second_execution(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate)
    harness = AgentHarness(dispatcher, tmp_path, config(timeout=0.01))
    context = harness.new_context("s", "t")
    unknown = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    gate.set()
    assert dispatcher.finished.wait(1)
    recovered = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    assert unknown.error["type"] == "OutcomeUnknown"
    assert recovered.success
    assert dispatcher.calls == dispatcher.dut.side_effects == 1
    assert harness.metrics["reconciliation_successes"] >= 1


def test_timeout_then_late_explicit_failure_is_reconciled_failed(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate, fail=True)
    harness = AgentHarness(dispatcher, tmp_path, config(timeout=0.01, retries=0))
    context = harness.new_context("s", "t")
    harness.execute("inject_fault", {"fault_id": "F001"}, context)
    gate.set()
    assert dispatcher.finished.wait(1)
    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    assert not result.success
    assert dispatcher.calls == 1
    assert harness.ledger.list_actions("s", "t")[0]["action_status"] == "FAILED"


def test_unknown_without_query_or_state_evidence_remains_unknown(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate, mutate=False)
    harness = AgentHarness(dispatcher, tmp_path, config(timeout=0.01))
    context = harness.new_context("s", "t")
    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    again = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    assert result.error["type"] == again.error["type"] == "OutcomeUnknown"
    assert dispatcher.calls == 1
    gate.set()
    assert dispatcher.finished.wait(1)


def test_concurrent_same_idempotency_key_executes_once(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate)
    first = AgentHarness(dispatcher, tmp_path, config(timeout=1))
    second = AgentHarness(dispatcher, tmp_path, config(timeout=1))
    c1 = first.new_context("s", "t")
    c2 = second.new_context("s", "t")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(first.execute, "inject_fault", {"fault_id": "F001"}, c1)
        assert dispatcher.started.wait(1)
        f2 = pool.submit(second.execute, "inject_fault", {"fault_id": "F001"}, c2)
        gate.set()
        r1, r2 = f1.result(), f2.result()
    assert dispatcher.calls == dispatcher.dut.side_effects == 1
    assert r1.success or r2.success


def test_different_session_keys_do_not_collide(tmp_path):
    dispatcher = ControlledDispatcher()
    h1 = AgentHarness(dispatcher, tmp_path / "one", config())
    h2 = AgentHarness(dispatcher, tmp_path / "two", config())
    h1.execute("inject_fault", {"fault_id": "F001"}, h1.new_context("s1", "t"))
    dispatcher.dut.active = None
    dispatcher.dut.state = "NORMAL"
    h2.execute("inject_fault", {"fault_id": "F001"}, h2.new_context("s2", "t"))
    assert dispatcher.calls == 2


def test_different_logical_action_ids_execute_independently(tmp_path):
    dispatcher = ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    harness.execute("inject_fault", {"fault_id": "F001"}, context, logical_action_id="a1")
    dispatcher.dut.active = None
    dispatcher.dut.state = "NORMAL"
    harness.execute("inject_fault", {"fault_id": "F001"}, context, logical_action_id="a2")
    assert dispatcher.calls == 2


def test_recover_incomplete_marks_running_attempt_unknown(tmp_path):
    ledger = ActionLedger(tmp_path / "ledger.sqlite3")
    action = ledger.get_or_create_action("s", "t", "inject_fault", {"fault_id": "F001"})
    ledger.claim(action["logical_action_id"])
    changed = ledger.recover_incomplete("s", "t")
    assert changed == 1
    assert ledger.get_action(action["logical_action_id"])["action_status"] == "OUTCOME_UNKNOWN"


def test_restart_reconciles_successful_unknown_action(tmp_path):
    dispatcher = ControlledDispatcher()
    first = AgentHarness(dispatcher, tmp_path, config())
    context = first.new_context("s", "t")
    result = first.execute("inject_fault", {"fault_id": "F001"}, context)
    action = first.ledger.list_actions("s", "t")[0]
    first.ledger.force_status(action["logical_action_id"], "OUTCOME_UNKNOWN")
    second = AgentHarness(dispatcher, tmp_path, config())
    reconciled = second.reconcile(action["logical_action_id"], context)
    assert result.success and reconciled.success
    assert dispatcher.calls == 1


def test_restart_preserves_unknown_when_operation_cannot_be_proven(tmp_path):
    dispatcher = ControlledDispatcher(mutate=False)
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    action = harness.ledger.get_or_create_action("s", "t", "inject_fault", {"fault_id": "F001"})
    harness.ledger.force_status(action["logical_action_id"], "OUTCOME_UNKNOWN")
    result = harness.reconcile(action["logical_action_id"], context)
    assert result.error["type"] == "OutcomeUnknown"


def test_checkpoint_contains_ledger_recovery_references(tmp_path):
    dispatcher = ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    harness.execute("inject_fault", {"fault_id": "F001"}, context)
    payload = harness.store.read(harness.last_checkpoint)
    assert payload["context"]["current_logical_action_id"]
    assert payload["context"]["current_operation_id"]
    assert payload["ledger"]["logical_action"]["action_status"] == "SUCCEEDED"


def test_checkpoint_ledger_mismatch_is_rejected(tmp_path):
    dispatcher = ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    harness.execute("inject_fault", {"fault_id": "F001"}, context)
    harness.ledger.force_status(context.current_logical_action_id, "FAILED")
    with pytest.raises(RuntimeError, match="checkpoint.*ledger"):
        harness.resume("s")


def test_session_manager_isolates_context_dut_and_ledger(tmp_path):
    manager = SessionManager(tmp_path)
    one = manager.create("one", "task")
    two = manager.create("two", "task")
    one.harness.execute("inject_fault", {"fault_id": "F001"}, one.context)
    assert one.dispatcher.dut.active == "F001"
    assert two.dispatcher.dut.active is None
    assert one.context.session_id != two.context.session_id
    assert one.harness.ledger.path != two.harness.ledger.path


def test_two_workers_compete_for_one_logical_action_without_duplicate(tmp_path):
    gate = threading.Event()
    dispatcher = ControlledDispatcher(gate=gate)
    h1 = AgentHarness(dispatcher, tmp_path, config(timeout=1))
    h2 = AgentHarness(dispatcher, tmp_path, config(timeout=1))
    c1, c2 = h1.new_context("s", "t"), h2.new_context("s", "t")
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(h1.execute, "inject_fault", {"fault_id": "F001"}, c1)
        assert dispatcher.started.wait(1)
        r2 = h2.execute("inject_fault", {"fault_id": "F001"}, c2)
        gate.set()
        r1 = f1.result()
    assert dispatcher.calls == 1
    assert r1.success
    assert r2.error["type"] in {"ActionInProgress", "OutcomeUnknown"}


def test_authoritative_state_conflict_does_not_fabricate_success(tmp_path):
    dispatcher = ControlledDispatcher(mutate=False)
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    action = harness.ledger.get_or_create_action("s", "t", "inject_fault", {"fault_id": "F001"})
    harness.ledger.force_status(action["logical_action_id"], "OUTCOME_UNKNOWN")
    result = harness.reconcile(action["logical_action_id"], context)
    assert not result.success
    assert harness.ledger.get_action(action["logical_action_id"])["action_status"] == "OUTCOME_UNKNOWN"


def test_completed_action_never_executes_side_effect_again(tmp_path):
    dispatcher = ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, config())
    context = harness.new_context("s", "t")
    for _ in range(3):
        assert harness.execute("inject_fault", {"fault_id": "F001"}, context, logical_action_id="completed-once").success
    assert dispatcher.calls == dispatcher.dut.side_effects == 1
