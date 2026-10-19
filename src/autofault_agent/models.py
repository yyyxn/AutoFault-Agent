from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

class Scenario(BaseModel):
    id: str = Field(pattern=r"^DEMO-[0-9]{3}$")
    title: str
    description: str
    fault_id: str
    component: str
    expected_dtc: str
    test_case: list[str]
    scenario: Literal["normal", "dtc_mismatch", "transient_tool_error"] = "normal"

class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

class TraceStep(BaseModel):
    index: int
    kind: Literal["model", "tool", "verifier", "final"]
    label: str
    status: str
    latency_ms: float = 0
    tool_call: ToolCall | None = None
    observation: dict[str, Any] | None = None
    model_output: str | None = None
    verifier_feedback: dict[str, Any] | None = None

class RunRequest(BaseModel):
    scenario_id: str
    goal: str = Field(min_length=3, max_length=1000)
    mode: Literal["replay", "live"] = "replay"
    model: Literal["base", "sft-b"] = "base"
    verifier_enabled: bool = False

class RunResult(BaseModel):
    run_id: str
    mode: Literal["replay", "live"]
    model: str
    verifier_enabled: bool
    scenario_id: str
    goal: str
    trace: list[TraceStep]
    final_answer: str
    dut_state: dict[str, Any]
    task_success: bool
    latency_ms: float
    disclosure: str
