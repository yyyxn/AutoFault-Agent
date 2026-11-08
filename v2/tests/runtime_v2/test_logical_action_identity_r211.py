"""R2.1.1 production-chain identity and crash-recovery contracts."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from auto_fault_agent.environment import TaskEnvironment, TaskSpec
from auto_fault_agent.harness import AgentHarness, HarnessConfig
from auto_fault_agent.harness.action_ledger import LogicalActionScopeConflict
from auto_fault_agent.schemas import ToolResult


class RepeatableDUT:
    def __init__(self):
        self.active = None
        self.state = "NORMAL"
        self.version = 1
        self.side_effects = 0

    def snapshot(self):
        return {"active": self.active, "state": self.state, "version": self.version}

    def restore(self, value):
        self.active = value.get("active")
        self.state = value.get("state", "NORMAL")
        self.version = int(value.get("version", 1))


class IdentityDispatcher:
    def __init__(self, gate=None):
        self.dut = RepeatableDUT()
        self.gate = gate
        self.started = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.calls = 0
        self.operations = {}

    def dispatch_operation(self, name, arguments, operation_id, idempotency_key):
        with self.lock:
            if operation_id in self.operations:
                return self.operations[operation_id]
            self.calls += 1
        self.started.set()
        if self.gate is not None:
            self.gate.wait(2)
        with self.lock:
            self.dut.side_effects += 1
            self.dut.active = arguments.get("fault_id")
            self.dut.state = "FAULT_INJECTED"
            self.dut.version += 1
            result = ToolResult(
                tool_call_id=operation_id,
                tool_name=name,
                success=True,
                result={"fault_id": self.dut.active, "state": self.dut.state},
                latency_ms=0,
            )
            self.operations[operation_id] = result
        self.finished.set()
        return result

    def query_operation(self, operation_id):
        return self.operations.get(operation_id)


def harness_config(timeout=1, checkpoint=True):
    return HarnessConfig(
        timeout_seconds=timeout,
        max_retries=0,
        enable_timeout=True,
        enable_retry=True,
        enable_checkpoint=checkpoint,
    )


def task_spec(task_id="identity-task"):
    return TaskSpec(
        task_id=task_id,
        task_type="diagnostic",
        instruction="exercise logical action identity",
        fault_id="F323",
        expected_tools=[],
        ground_truth={},
        difficulty="easy",
    )


def environment(tmp_path, dispatcher, *, timeout=1, task_id="identity-task"):
    env = TaskEnvironment(task_spec(task_id), "baseline", str(tmp_path))
    env.reset(42)
    env.mode = "harness"
    env.dispatcher = dispatcher
    env.harness = AgentHarness(dispatcher, tmp_path, harness_config(timeout))
    env.context = env.harness.new_context("session", task_id)
    return env


def ledger_commit_event(ledger):
    committed = threading.Event()
    original = ledger.finish

    def finish(*args, **kwargs):
        value = original(*args, **kwargs)
        committed.set()
        return value

    ledger.finish = finish
    return committed


def test_real_task_environment_generates_distinct_ids_for_identical_actions(tmp_path):
    dispatcher = IdentityDispatcher()
    env = environment(tmp_path, dispatcher)
    first = env.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F323"}})
    second = env.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F323"}})
    actions = env.harness.ledger.list_actions("session", "identity-task")

    assert first["logical_action_id"] != second["logical_action_id"]
    assert len(actions) == len({row["operation_id"] for row in actions}) == 2
    assert dispatcher.calls == dispatcher.dut.side_effects == 2
    assert [row["logical_action_id"] for row in env.actions] == [
        first["logical_action_id"], second["logical_action_id"]
    ]


def test_decision_identity_is_persisted_in_trace_and_checkpoint(tmp_path):
    dispatcher = IdentityDispatcher()
    env = environment(tmp_path, dispatcher)
    result = env.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F323"}})
    logical_id = result["logical_action_id"]
    checkpoint = env.harness.store.read(env.harness.last_checkpoint)
    trace = json.loads((env.harness.trace_dir / "session.jsonl").read_text().splitlines()[-1])

    assert checkpoint["context"]["current_logical_action_id"] == logical_id
    assert checkpoint["ledger"]["logical_action"]["logical_action_id"] == logical_id
    assert trace["logical_action_id"] == logical_id
    assert env.actions[-1]["logical_action_id"] == logical_id


def test_real_chain_timeout_late_success_retry_reuses_identity(tmp_path):
    gate = threading.Event()
    dispatcher = IdentityDispatcher(gate)
    env = environment(tmp_path, dispatcher, timeout=0.01)
    committed = ledger_commit_event(env.harness.ledger)

    unknown = env.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F323"}})
    logical_id = unknown["logical_action_id"]
    operation_id = unknown["operation_id"]
    gate.set()
    assert dispatcher.finished.wait(1) and committed.wait(1)
    retry = env.step({
        "logical_action_id": logical_id,
        "tool_name": "inject_fault",
        "arguments": {"fault_id": "F323"},
    })

    actions = env.harness.ledger.list_actions("session", "identity-task")
    assert unknown["error"]["type"] == "OutcomeUnknown"
    assert retry["success"] and retry["logical_action_id"] == logical_id
    assert len(actions) == 1 and actions[0]["operation_id"] == operation_id
    assert dispatcher.calls == dispatcher.dut.side_effects == 1


def test_real_chain_duplicate_while_unknown_does_not_redispatch(tmp_path):
    gate = threading.Event()
    dispatcher = IdentityDispatcher(gate)
    env = environment(tmp_path, dispatcher, timeout=0.01)
    committed = ledger_commit_event(env.harness.ledger)
    unknown = env.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F323"}})
    duplicate = env.step({
        "logical_action_id": unknown["logical_action_id"],
        "tool_name": "inject_fault",
        "arguments": {"fault_id": "F323"},
    })

    assert unknown["error"]["type"] == duplicate["error"]["type"] == "OutcomeUnknown"
    assert dispatcher.calls == 1
    gate.set()
    assert dispatcher.finished.wait(1) and committed.wait(1)
    assert dispatcher.dut.side_effects == 1


def test_concurrent_duplicate_identity_has_one_action_operation_and_effect(tmp_path):
    gate = threading.Event()
    dispatcher = IdentityDispatcher(gate)
    first = AgentHarness(dispatcher, tmp_path, harness_config())
    second = AgentHarness(dispatcher, tmp_path, harness_config())
    c1 = first.new_context("session", "task")
    c2 = second.new_context("session", "task")
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(
            first.execute, "inject_fault", {"fault_id": "F323"}, c1,
            logical_action_id="act_shared",
        )
        assert dispatcher.started.wait(1)
        duplicate = second.execute(
            "inject_fault", {"fault_id": "F323"}, c2,
            logical_action_id="act_shared",
        )
        gate.set()
        completed = future.result()

    assert completed.success and duplicate.error["type"] == "ActionInProgress"
    assert len(first.ledger.list_actions("session", "task")) == 1
    assert len(dispatcher.operations) == dispatcher.calls == dispatcher.dut.side_effects == 1


def test_explicit_distinct_identities_with_identical_payloads_execute_twice(tmp_path):
    dispatcher = IdentityDispatcher()
    env = environment(tmp_path, dispatcher)
    for logical_id in ("act_one", "act_two"):
        result = env.step({
            "logical_action_id": logical_id,
            "tool_name": "inject_fault",
            "arguments": {"fault_id": "F323"},
        })
        assert result["success"]
    actions = env.harness.ledger.list_actions("session", "identity-task")
    assert [row["logical_action_id"] for row in actions] == ["act_one", "act_two"]
    assert len({row["operation_id"] for row in actions}) == 2
    assert dispatcher.dut.side_effects == 2


def test_same_global_logical_id_in_another_scope_is_rejected(tmp_path):
    dispatcher = IdentityDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, harness_config())
    first = harness.new_context("session-a", "task-a")
    second = harness.new_context("session-b", "task-b")
    assert harness.execute(
        "inject_fault", {"fault_id": "F323"}, first,
        logical_action_id="act_global",
    ).success
    with pytest.raises(LogicalActionScopeConflict):
        harness.execute(
            "inject_fault", {"fault_id": "F323"}, second,
            logical_action_id="act_global",
        )
    assert dispatcher.calls == 1
    assert harness.ledger.list_actions("session-b", "task-b") == []


class PersistentDUT(RepeatableDUT):
    def __init__(self, path):
        self.path = Path(path)
        if self.path.exists():
            value = json.loads(self.path.read_text(encoding="utf-8"))
            self.active = value["active"]
            self.state = value["state"]
            self.version = value["version"]
            self.side_effects = value["side_effects"]
        else:
            super().__init__()
            self._save()

    def _save(self):
        self.path.write_text(json.dumps({
            "active": self.active, "state": self.state, "version": self.version,
            "side_effects": self.side_effects,
        }), encoding="utf-8")


class PersistentDispatcher(IdentityDispatcher):
    def __init__(self, state_path, gate=None):
        super().__init__(gate)
        self.dut = PersistentDUT(state_path)

    def dispatch_operation(self, name, arguments, operation_id, idempotency_key):
        result = super().dispatch_operation(name, arguments, operation_id, idempotency_key)
        self.dut._save()
        return result


def test_unknown_late_success_restart_reuses_ledger_in_independent_process(tmp_path):
    gate = threading.Event()
    state_path = tmp_path / "external_state.json"
    dispatcher = PersistentDispatcher(state_path, gate)
    harness = AgentHarness(dispatcher, tmp_path / "runtime", harness_config(timeout=0.01))
    committed = ledger_commit_event(harness.ledger)
    context = harness.new_context("restart-session", "restart-task")
    unknown = harness.execute(
        "inject_fault", {"fault_id": "F323"}, context,
        logical_action_id="act_restart",
    )
    assert unknown.error["type"] == "OutcomeUnknown" and harness.last_checkpoint
    gate.set()
    assert dispatcher.finished.wait(1) and committed.wait(1)

    code = r'''
import json,sys
from pathlib import Path
from auto_fault_agent.harness import AgentHarness,HarnessConfig
class DUT:
 def __init__(self,path):self.path=Path(path)
 def snapshot(self):return json.loads(self.path.read_text(encoding="utf-8"))
 def restore(self,value):raise AssertionError("stale UNKNOWN checkpoint must not overwrite external state")
class Dispatcher:
 def __init__(self,path):self.dut=DUT(path);self.calls=0
 def dispatch_operation(self,*args,**kwargs):self.calls+=1;raise AssertionError("must not redispatch")
 def query_operation(self,operation_id):return None
root,state=sys.argv[1:3]
h=AgentHarness(Dispatcher(state),root,HarnessConfig(timeout_seconds=.01,max_retries=0,enable_timeout=True,enable_retry=True,enable_checkpoint=True))
c=h.resume("restart-session")
r=h.execute("inject_fault",{"fault_id":"F323"},c,logical_action_id="act_restart")
print(json.dumps({"success":r.success,"calls":h.dispatcher.calls,"actions":len(h.ledger.list_actions("restart-session","restart-task")),"operation_id":r.tool_call_id,"current_fault_id":c.current_fault_id}))
'''
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).parents[2] / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path / "runtime"), str(state_path)],
        text=True, capture_output=True, check=True, env=env,
    )
    value = json.loads(completed.stdout.strip().splitlines()[-1])
    action = harness.ledger.get_action("act_restart")
    assert value == {
        "success": True, "calls": 0, "actions": 1,
        "operation_id": action["operation_id"], "current_fault_id": "F323",
    }
    assert json.loads(state_path.read_text())["side_effects"] == 1


def test_late_timeout_and_stale_finish_cannot_replace_success(tmp_path):
    dispatcher = IdentityDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, harness_config())
    context = harness.new_context("session", "task")
    assert harness.execute(
        "inject_fault", {"fault_id": "F323"}, context,
        logical_action_id="act_terminal",
    ).success
    action = harness.ledger.get_action("act_terminal")
    attempt = harness.ledger.attempts("act_terminal")[0]
    harness.ledger.mark_timeout(
        "act_terminal", attempt["attempt_id"],
        {"type": "OutcomeUnknown", "message": "late timeout"},
    )
    harness.ledger.finish(
        "act_terminal", attempt["attempt_id"], "FAILED",
        error={"type": "StaleFailure", "message": "late failure"},
    )
    current = harness.ledger.get_action("act_terminal")
    assert current["action_status"] == "SUCCEEDED"
    assert current["result_json"] == action["result_json"]


def _unknown_checkpoint(tmp_path, ledger_status):
    dispatcher = IdentityDispatcher()
    harness = AgentHarness(dispatcher, tmp_path, harness_config())
    context = harness.new_context("matrix-session", "matrix-task")
    action = harness.ledger.get_or_create_action(
        context.session_id, context.task_id, "inject_fault", {"fault_id": "F323"},
        logical_action_id="act_matrix",
    )
    harness.ledger.force_status("act_matrix", "OUTCOME_UNKNOWN")
    context.current_logical_action_id = "act_matrix"
    context.current_operation_id = action["operation_id"]
    context.current_idempotency_key = action["idempotency_key"]
    harness.last_checkpoint = harness.store.save(context, dispatcher.dut, harness.ledger.get_action("act_matrix"))
    harness.ledger.force_status("act_matrix", ledger_status)
    return harness


@pytest.mark.parametrize("ledger_status", ["OUTCOME_UNKNOWN", "EXECUTING"])
def test_unknown_checkpoint_nonterminal_ledger_remains_nonexecuting(tmp_path, ledger_status):
    harness = _unknown_checkpoint(tmp_path, ledger_status)
    resumed = harness.resume("matrix-session")
    current = harness.ledger.get_action("act_matrix")
    assert current["action_status"] == "OUTCOME_UNKNOWN"
    assert resumed.current_logical_action_id == "act_matrix"
    assert harness.dispatcher.calls == 0


def test_succeeded_checkpoint_unknown_ledger_is_rejected(tmp_path):
    harness = _unknown_checkpoint(tmp_path, "OUTCOME_UNKNOWN")
    payload = harness.store.read(harness.last_checkpoint)
    payload["ledger"]["logical_action"]["action_status"] = "SUCCEEDED"
    harness.last_checkpoint.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="checkpoint.*ledger"):
        harness.resume("matrix-session")


def test_unknown_checkpoint_missing_ledger_action_is_rejected(tmp_path):
    harness = _unknown_checkpoint(tmp_path, "OUTCOME_UNKNOWN")
    with sqlite3.connect(harness.ledger.path) as db:
        db.execute("DELETE FROM logical_actions WHERE logical_action_id='act_matrix'")
    with pytest.raises(RuntimeError, match="missing from ledger"):
        harness.resume("matrix-session")


def test_unknown_checkpoint_other_scope_action_is_rejected(tmp_path):
    harness = _unknown_checkpoint(tmp_path, "OUTCOME_UNKNOWN")
    with sqlite3.connect(harness.ledger.path) as db:
        db.execute("UPDATE logical_actions SET session_id='other-session' WHERE logical_action_id='act_matrix'")
    with pytest.raises(RuntimeError, match="scope mismatch"):
        harness.resume("matrix-session")
