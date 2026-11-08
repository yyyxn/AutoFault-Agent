"""AutoFault-Agent 2.0 runtime reliability contracts.

These tests intentionally describe the desired 2.0 behaviour before the runtime
implementation is changed.  Failing tests are evidence of known 1.0 defects;
they must not be weakened merely to make the suite green.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from auto_fault_agent.environment.task_env import TaskEnvironment, TaskSpec
from auto_fault_agent.harness import AgentHarness, HarnessConfig
from auto_fault_agent.harness.completion_verifier import (
    CompletionVerifier,
    CompletionVerifierConfig,
)
from auto_fault_agent.schemas import ToolResult
from auto_fault_agent.tools import ToolDispatcher


def full_task(task_id: str = "RUNTIME_F323") -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_type="multi_turn",
        instruction="完成 F001 的多步诊断、判定和恢复。",
        fault_id="F001",
        expected_tools=[
            "search_fault_knowledge",
            "get_test_case",
            "inject_fault",
            "read_dtc",
            "judge_test_result",
            "recover_fault",
        ],
        ground_truth={
            "expected_outcome": "complete",
            "expected_dtc": "SIM_DTC_001",
            "observed_dtc": "SIM_DTC_001",
            "expected_judge": "PASS",
        },
        difficulty="hard",
    )


def test_failed_terminal_tool_does_not_finish_environment(tmp_path):
    """F323 regression: a failed final-named tool is not task completion."""
    env = TaskEnvironment(full_task(), "harness", str(tmp_path))
    env.reset(42)

    observation = env.step(
        {"tool_name": "recover_fault", "arguments": {"fault_id": "F001"}}
    )

    assert observation["success"] is False
    assert env.is_done() is False


def test_replanning_is_allowed_after_failed_recover(tmp_path):
    """Verifier-directed replanning must remain executable after a bad action."""
    env = TaskEnvironment(full_task(), "harness", str(tmp_path))
    env.reset(42)
    env.step({"tool_name": "recover_fault", "arguments": {"fault_id": "F001"}})

    next_observation = env.step(
        {
            "tool_name": "search_fault_knowledge",
            "arguments": {"query": "F001", "top_k": 3},
        }
    )

    assert next_observation["success"] is True
    assert env.is_done() is False


def test_failed_tool_request_does_not_mutate_verified_context_state(tmp_path):
    """Context state must follow verified DUT results, not requested arguments."""
    dispatcher = ToolDispatcher()
    harness = AgentHarness(dispatcher, tmp_path)
    context = harness.new_context("session-f323", "task-f323")

    result = harness.execute("recover_fault", {"fault_id": "F001"}, context)

    assert result.success is False
    assert dispatcher.dut.active is None
    assert context.current_fault_id is None


def test_successful_fault_transition_updates_context_from_dut(tmp_path):
    """The positive control: successful transitions may update verified state."""
    dispatcher = ToolDispatcher()
    harness = AgentHarness(dispatcher, tmp_path)
    context = harness.new_context("session-success", "task-success")

    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)

    assert result.success is True
    assert dispatcher.dut.active == "F001"
    assert context.current_fault_id == dispatcher.dut.active


class _SlowSideEffectDispatcher:
    """A deterministic side-effecting tool that outlives the harness timeout."""

    def __init__(self):
        self.calls = 0
        self.dut = SimpleNamespace(
            snapshot=lambda: {
                "state": "NORMAL",
                "active": None,
                "failures": {},
                "scenario": "normal",
            }
        )

    def dispatch(self, name, arguments):
        self.calls += 1
        time.sleep(0.05)
        return ToolResult(
            tool_call_id=f"slow-{self.calls}",
            tool_name=name,
            success=True,
            result={"side_effect_applied": True},
            latency_ms=50.0,
        )


def test_timeout_with_unknown_outcome_is_not_blindly_retried(tmp_path):
    """A timeout is outcome-unknown; repeating a side effect is unsafe."""
    dispatcher = _SlowSideEffectDispatcher()
    harness = AgentHarness(
        dispatcher,
        tmp_path,
        HarnessConfig(timeout_seconds=0.01, max_retries=1),
    )
    context = harness.new_context("session-timeout", "task-timeout")

    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)
    time.sleep(0.12)  # allow any uncancelled worker to reveal its side effect

    assert result.success is False
    assert result.error["type"] in {"OutcomeUnknown", "HarnessTimeoutError"}
    assert dispatcher.calls == 1


def test_two_task_environments_have_isolated_dut_state(tmp_path):
    """Positive isolation contract for the in-process TaskEnvironment path."""
    first = TaskEnvironment(full_task("A"), "harness", str(tmp_path / "a"))
    second = TaskEnvironment(full_task("B"), "harness", str(tmp_path / "b"))
    first.reset(42)
    second.reset(42)

    first.step({"tool_name": "inject_fault", "arguments": {"fault_id": "F001"}})

    assert first.dispatcher.dut.active == "F001"
    assert second.dispatcher.dut.active is None
    assert second.dispatcher.dut.snapshot()["state"] == "NORMAL"


def test_repeated_identical_final_is_reported_as_no_progress():
    """Repeated Final text after identical feedback must be observable."""
    verifier = CompletionVerifier(
        CompletionVerifierConfig(enabled=True, max_corrections=2)
    )
    task = SimpleNamespace(task_type="multi_turn")
    assessment = verifier.assess([], task, {"state": "NORMAL", "active": None})

    first = verifier.handle_premature_final(assessment, "F001 未激活，无法验证。")
    second = verifier.handle_premature_final(assessment, "F001 未激活，无法验证。")

    assert first.get("no_progress") is not True
    assert second.get("no_progress") is True
