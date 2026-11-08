"""R1 acceptance tests for lifecycle, authoritative state, and completion."""
from __future__ import annotations

from types import SimpleNamespace

from auto_fault_agent.environment.lifecycle import TaskLifecycleState
from auto_fault_agent.environment.task_env import TaskEnvironment, TaskSpec
from auto_fault_agent.harness import AgentHarness
from auto_fault_agent.harness.completion_verifier import (
    CompletionStatus,
    CompletionVerifier,
    CompletionVerifierConfig,
)
from auto_fault_agent.phase5_evaluation import phase5_completion, strict_success
from auto_fault_agent.schemas import ToolResult


def task_spec(
    task_id: str = "R1-F001",
    *,
    scenario: str = "normal",
    expected_outcome: str = "complete",
    expected_dtc: str = "SIM_DTC_001",
    expected_judge: str = "PASS",
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        task_type="multi_turn",
        instruction="完成 F001 的多步诊断、判定和恢复。",
        fault_id="F001",
        scenario=scenario,
        expected_tools=[
            "search_fault_knowledge",
            "get_test_case",
            "inject_fault",
            "read_dtc",
            "judge_test_result",
            "recover_fault",
        ],
        ground_truth={
            "expected_outcome": expected_outcome,
            "expected_dtc": expected_dtc,
            "observed_dtc": expected_dtc,
            "expected_judge": expected_judge,
        },
        difficulty="hard",
    )


def call(env: TaskEnvironment, name: str, **arguments):
    return env.step({"tool_name": name, "arguments": arguments})


def run_complete(env: TaskEnvironment, *, dtc: str = "SIM_DTC_001"):
    call(env, "search_fault_knowledge", query="F001", top_k=3)
    call(env, "get_test_case", fault_id="F001")
    call(env, "inject_fault", fault_id="F001")
    call(env, "read_dtc")
    call(env, "judge_test_result", fault_id="F001", dtc=dtc)
    call(env, "recover_fault", fault_id="F001")


def assess(env: TaskEnvironment, *, cannot_continue: bool = False):
    return phase5_completion(
        env.actions,
        env.task,
        env.dispatcher.dut.snapshot(),
        cannot_continue=cannot_continue,
    )


def test_successful_last_named_tool_does_not_finish_incomplete_contract(tmp_path):
    env = TaskEnvironment(task_spec(), "harness", str(tmp_path))
    env.reset(42)
    call(env, "inject_fault", fault_id="F001")
    result = call(env, "recover_fault", fault_id="F001")

    contract = assess(env)
    assert result["success"] is True
    assert contract.status is CompletionStatus.INCOMPLETE
    assert env.lifecycle.state is TaskLifecycleState.RUNNING
    assert env.is_done() is False


def test_contract_complete_can_finish_after_nonterminal_named_tool(tmp_path):
    env = TaskEnvironment(task_spec(), "harness", str(tmp_path))
    env.reset(42)
    run_complete(env)
    extra = call(env, "search_fault_knowledge", query="F001", top_k=1)
    contract = assess(env)

    assert extra["success"] is True
    assert env.actions[-1]["tool_name"] != env.task.expected_tools[-1]
    assert contract.status is CompletionStatus.COMPLETE
    env.begin_verification()
    env.resolve_verification(contract.status, contract.reason_code)
    assert env.lifecycle.state is TaskLifecycleState.COMPLETED
    assert env.is_done() is True


def test_failed_inject_does_not_change_authoritative_context(tmp_path):
    env = TaskEnvironment(
        task_spec(scenario="tool_error"), "harness", str(tmp_path)
    )
    env.reset(42)
    before = env.dispatcher.dut.snapshot()
    result = call(env, "inject_fault", fault_id="F001")

    assert result["success"] is False
    assert env.context.requested_fault_id == "F001"
    assert env.context.observed_fault_id is None
    assert env.context.current_fault_id is None
    assert env.context.dut_state == before["state"]
    assert env.context.dut_state_version == before["version"]


class _ControlledDUT:
    def __init__(self):
        self.active = None
        self.state = "NORMAL"
        self.version = 11

    def snapshot(self):
        return {
            "state": self.state,
            "active": self.active,
            "version": self.version,
            "failures": {},
            "scenario": "normal",
        }


class _ControlledDispatcher:
    """Separates requested input from observed authoritative state."""

    def __init__(self):
        self.dut = _ControlledDUT()

    def dispatch(self, name, arguments):
        assert name == "inject_fault"
        assert arguments["fault_id"] == "F001"
        self.dut.active = "F002"
        self.dut.state = "FAULT_INJECTED"
        self.dut.version += 1
        return ToolResult(
            tool_call_id="controlled-1",
            tool_name=name,
            success=True,
            result={"fault_id": "F002", "state": "FAULT_INJECTED"},
            latency_ms=0.0,
        )


def test_context_uses_observed_state_not_requested_argument(tmp_path):
    dispatcher = _ControlledDispatcher()
    harness = AgentHarness(dispatcher, tmp_path)
    context = harness.new_context("controlled", "controlled-task")

    result = harness.execute("inject_fault", {"fault_id": "F001"}, context)

    assert result.success is True
    assert context.requested_fault_id == "F001"
    assert context.observed_fault_id == "F002"
    assert context.current_fault_id == "F002"
    assert context.current_fault_id == dispatcher.dut.snapshot()["active"]
    assert context.dut_state_version == dispatcher.dut.snapshot()["version"]


def test_successful_recovery_clears_current_fault_and_matches_version(tmp_path):
    env = TaskEnvironment(task_spec(), "harness", str(tmp_path))
    env.reset(42)
    call(env, "inject_fault", fault_id="F001")
    assert env.context.current_fault_id == "F001"
    assert env.context.requested_fault_id == "F001"

    result = call(env, "recover_fault", fault_id="F001")
    snapshot = env.dispatcher.dut.snapshot()
    assert result["success"] is True
    assert env.context.observed_fault_id == "F001"
    assert env.context.current_fault_id is None
    assert env.context.dut_state == snapshot["state"]
    assert env.context.dut_state_version == snapshot["version"]


def test_complete_and_incomplete_contract_drive_distinct_lifecycle_states(tmp_path):
    complete = TaskEnvironment(task_spec("complete"), "harness", str(tmp_path / "a"))
    complete.reset(42)
    run_complete(complete)
    complete_contract = assess(complete)
    complete.begin_verification()
    complete.resolve_verification(
        complete_contract.status, complete_contract.reason_code
    )

    incomplete = TaskEnvironment(
        task_spec("incomplete"), "harness", str(tmp_path / "b")
    )
    incomplete.reset(42)
    call(incomplete, "search_fault_knowledge", query="F001", top_k=3)
    incomplete_contract = assess(incomplete)
    incomplete.begin_verification()
    incomplete.resolve_verification(
        incomplete_contract.status,
        incomplete_contract.reason_code,
        continue_allowed=True,
    )

    assert complete_contract.status is CompletionStatus.COMPLETE
    assert strict_success(complete.task, True, complete_contract) is True
    assert complete.lifecycle.state is TaskLifecycleState.COMPLETED
    assert incomplete_contract.status is CompletionStatus.INCOMPLETE
    assert incomplete.lifecycle.state is TaskLifecycleState.RUNNING
    assert incomplete.is_done() is False


def test_business_fail_is_a_valid_completed_business_outcome(tmp_path):
    env = TaskEnvironment(
        task_spec(
            "business-fail",
            scenario="dtc_mismatch",
            expected_dtc="SIM_DTC_999",
            expected_judge="FAIL",
        ),
        "harness",
        str(tmp_path),
    )
    env.reset(42)
    run_complete(env, dtc="SIM_DTC_999")
    contract = assess(env)
    env.begin_verification()
    env.resolve_verification(contract.status, contract.reason_code)

    assert contract.status is CompletionStatus.COMPLETE
    assert strict_success(env.task, True, contract) is True
    assert env.lifecycle.state is TaskLifecycleState.COMPLETED


def test_evidence_backed_blocked_contract_enters_blocked_state(tmp_path):
    task = task_spec("blocked", scenario="tool_error", expected_outcome="blocked")
    task.expected_tools = [
        "search_fault_knowledge",
        "get_test_case",
        "inject_fault",
    ]
    env = TaskEnvironment(task, "harness", str(tmp_path))
    env.reset(42)
    call(env, "search_fault_knowledge", query="F001", top_k=3)
    call(env, "get_test_case", fault_id="F001")
    failed = call(env, "inject_fault", fault_id="F001")
    contract = assess(env)
    env.begin_verification()
    env.resolve_verification(contract.status, contract.reason_code)

    assert failed["success"] is False
    assert contract.status is CompletionStatus.BLOCKED
    assert contract.reason_code == "valid_expected_blocked"
    assert strict_success(env.task, True, contract) is True
    assert env.lifecycle.state is TaskLifecycleState.BLOCKED


def test_verifier_incomplete_feedback_keeps_task_replannable(tmp_path):
    env = TaskEnvironment(task_spec("replan"), "harness", str(tmp_path))
    env.reset(42)
    failed = call(env, "recover_fault", fault_id="F001")
    contract = assess(env)
    verifier = CompletionVerifier(
        CompletionVerifierConfig(enabled=True, max_corrections=2)
    )
    decision = verifier.handle_premature_final(contract, "诊断结束")
    env.begin_verification()
    env.resolve_verification(
        contract.status, contract.reason_code, continue_allowed=True
    )
    replanned = call(env, "search_fault_knowledge", query="F001", top_k=3)

    assert failed["success"] is False
    assert contract.status is CompletionStatus.INCOMPLETE
    assert decision["allow_final"] is False
    assert decision["feedback"]["status"] == "incomplete"
    assert env.lifecycle.state is TaskLifecycleState.RUNNING
    assert replanned["success"] is True
    assert env.is_done() is False
