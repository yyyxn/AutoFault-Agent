from typing import Any
from pydantic import BaseModel, Field

class ExecutionContext(BaseModel):
    session_id: str
    task_id: str
    requested_fault_id: str | None = None
    observed_fault_id: str | None = None
    current_fault_id: str | None = None
    dut_state: str | None = None
    dut_state_version: int = 0
    task_lifecycle_state: str = "RUNNING"
    current_logical_action_id: str | None = None
    current_attempt_id: str | None = None
    current_operation_id: str | None = None
    current_idempotency_key: str | None = None
    last_reliable_observation: Any = None
    progress_fingerprint: str | None = None
    previous_progress_fingerprint: str | None = None
    consecutive_no_progress_count: int = 0
    repeated_final_count: int = 0
    last_verifier_status: str | None = None
    last_missing_requirements: list[str] = Field(default_factory=list)
    last_progress_reason: str | None = None
    step_count: int = 0
    last_tool: str | None = None
    last_input: dict[str, Any] | None = None
    last_output: Any = None
    last_status: str | None = None
    last_dtc: str | None = None
    last_error: str | None = None
    last_error_type: str | None = None
    retry_count: int = 0
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
