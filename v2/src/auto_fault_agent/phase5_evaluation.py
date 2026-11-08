"""Semantic completion contract for Phase 5 synthetic tasks.

This module is evaluation-only. It does not change the frozen Phase 4 contract.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from auto_fault_agent.harness.completion_verifier import CompletionStatus, ContractAssessment

CAPABILITIES={
    "fault_retrieval":("knowledge_evidence","test_case_evidence"),
    "dtc_reverse_diagnosis":("dtc_observed","knowledge_evidence","test_case_evidence"),
    "full_fault_test":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
    "exception_recovery":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
    "multi_turn":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
}

def phase5_completion(actions:list[dict[str,Any]],task,dut_state:dict[str,Any],*,cannot_continue=False)->ContractAssessment:
    required=CAPABILITIES.get(task.task_type)
    state=str(dut_state.get("state","UNKNOWN"))
    if not required:return ContractAssessment(CompletionStatus.UNKNOWN,(),(),(),"unsupported_goal",(),state)
    facts=set();ids=[];failures=[];actual_dtc=None;actual_judge=None
    for action in actions:
        obs=action.get("observation") or {};name=action.get("tool_name");args=action.get("arguments") or {}
        if not obs.get("success"):
            failures.append((name,args,obs.get("error") or {}));continue
        ids.append(obs.get("tool_call_id", ""));value=obs.get("result") or {}
        if name=="search_fault_knowledge" and value.get("documents"):facts.add("knowledge_evidence")
        elif name=="get_test_case" and value.get("test_case_id"):facts.add("test_case_evidence")
        elif name=="inject_fault" and value.get("state") in {"FAULT_INJECTED","DTC_ACTIVE"}:facts.add("fault_injected")
        elif name=="read_dtc" and value.get("dtc"):facts.add("dtc_observed");actual_dtc=value.get("dtc")
        elif name=="judge_test_result" and value.get("result") in {"PASS","FAIL"}:facts.add("judgment_recorded");actual_judge=value.get("result")
        elif name=="recover_fault" and value.get("recovered") is True:facts.add("recovery_observed")
    if dut_state.get("state")=="RECOVERED" and not dut_state.get("active"):facts.add("recovery_postcondition")
    truth=task.ground_truth; expected_outcome=truth.get("expected_outcome","complete")
    expected_dtc=truth.get("observed_dtc",truth.get("expected_dtc"));expected_judge=truth.get("expected_judge")
    semantic_errors=[]
    if "dtc_observed" in facts and actual_dtc!=expected_dtc:semantic_errors.append("dtc_mismatch_to_oracle")
    if expected_judge is not None and ("judgment_recorded" not in facts or actual_judge!=expected_judge):semantic_errors.append("business_judgment_mismatch")
    if expected_outcome=="blocked":
        prerequisites={"knowledge_evidence","test_case_evidence"}
        terminal_failure=any(n==task.expected_tools[-1] and a.get("fault_id",task.fault_id)==task.fault_id for n,a,e in failures)
        satisfied=tuple(x for x in ("knowledge_evidence","test_case_evidence","blocked_terminal_attempt") if x in facts or (x=="blocked_terminal_attempt" and terminal_failure))
        required_blocked=("knowledge_evidence","test_case_evidence","blocked_terminal_attempt")
        missing=tuple(x for x in required_blocked if x not in satisfied)
        if not missing:return ContractAssessment(CompletionStatus.BLOCKED,satisfied,required_blocked,(),"valid_expected_blocked",tuple(x for x in ids if x),state)
        return ContractAssessment(CompletionStatus.INCOMPLETE,satisfied,required_blocked,missing,"blocked_claim_without_required_evidence",tuple(x for x in ids if x),state)
    satisfied=tuple(x for x in required if x in facts)
    missing=tuple(x for x in required if x not in facts)
    if not missing and not semantic_errors:return ContractAssessment(CompletionStatus.COMPLETE,satisfied,required,(),"semantic_contract_satisfied",tuple(x for x in ids if x),state)
    if cannot_continue:return ContractAssessment(CompletionStatus.BLOCKED,satisfied,required,missing,"budget_or_runtime_exhausted",tuple(x for x in ids if x),state)
    reason=";".join(semantic_errors) if semantic_errors else "postconditions_unsatisfied"
    return ContractAssessment(CompletionStatus.INCOMPLETE,satisfied,required,missing,reason,tuple(x for x in ids if x),state)

def strict_success(task, accepted:bool, assessment:ContractAssessment)->bool:
    if not accepted:return False
    expected=task.ground_truth.get("expected_outcome","complete")
    return assessment.status==CompletionStatus.COMPLETE if expected!="blocked" else assessment.status==CompletionStatus.BLOCKED and assessment.reason_code=="valid_expected_blocked"
