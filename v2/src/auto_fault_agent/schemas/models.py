from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field

class FaultCase(BaseModel):
    fault_id: str; module: str; component: str; interface: str
    fault_type: str; symptom: str; expected_dtc: str; expected_result: str = "PASS"
    recovery_action: str = "remove_fault"; failure_mode: str = "normal"
    data_source: Literal["synthetic_demo"] = "synthetic_demo"

class TestCase(BaseModel):
    test_case_id: str; fault_id: str; title: str; steps: list[str]; expected_dtc: str
    expected_result: str = "PASS"; data_source: Literal["synthetic_demo"] = "synthetic_demo"

class KnowledgeDocument(BaseModel):
    source_id: str; title: str; content: str; fault_ids: list[str] = Field(default_factory=list)
    module: str = "通用"; fault_type: str = "general"
    data_source: Literal["synthetic_demo"] = "synthetic_demo"

class ToolResult(BaseModel):
    tool_call_id: str; tool_name: str; success: bool; result: Any = None
    error: dict[str, Any] | None = None; latency_ms: float

class TrajectoryStep(BaseModel):
    step: int; action: str; arguments: dict[str, Any]; result: Any; latency_ms: float
    success: bool = True; error: dict[str, Any] | None = None

class Trajectory(BaseModel):
    run_id: str; task_id: str; input: str; steps: list[TrajectoryStep] = Field(default_factory=list)
    final_answer: Any = None; success: bool = False; task_success: bool = False
    tool_correct: bool = False; step_count: int = 0; latency_ms: float = 0
    verification_result: str | None = None; error_count: int = 0

class BenchmarkTask(BaseModel):
    task_id: str; category: str; input: str; expected_tools: list[str]
    expected_result: str; expected_fault_id: str | None = None
    success_condition: dict[str, Any] = Field(default_factory=dict)
