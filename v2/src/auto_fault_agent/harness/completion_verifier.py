from __future__ import annotations
from dataclasses import dataclass,field
from enum import Enum
from typing import Any
from .progress import NoProgressGuard,ProgressConflictError,ProgressSnapshot,ProgressState,ProgressStore,build_fingerprint

class CompletionStatus(str,Enum):
    COMPLETE="complete"; INCOMPLETE="incomplete"; BLOCKED="blocked"; UNKNOWN="unknown"

@dataclass(frozen=True)
class CompletionVerifierConfig:
    enabled:bool=False
    max_corrections:int=2
    max_no_progress:int=2

@dataclass
class VerifierState:
    corrections:int=0
    interventions:int=0
    premature_finals:int=0
    overcontinue_attempts:int=0
    first_final_was_complete:bool|None=None
    events:list[dict[str,Any]]=field(default_factory=list)
    repeated_final_count:int=0

@dataclass(frozen=True)
class ContractAssessment:
    status:CompletionStatus
    satisfied:tuple[str,...]
    required:tuple[str,...]
    missing:tuple[str,...]
    reason_code:str
    evidence_call_ids:tuple[str,...]
    state:str
    @property
    def completion_ratio(self):return len(self.satisfied)/len(self.required) if self.required else 0.0

CAPABILITIES={
    "fault_retrieval":("knowledge_evidence","test_case_evidence"),
    "dtc_reverse_diagnosis":("dtc_observed","knowledge_evidence","test_case_evidence"),
    "full_fault_test":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
    "exception_recovery":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
    "multi_turn":("knowledge_evidence","test_case_evidence","fault_injected","dtc_observed","judgment_recorded","recovery_postcondition"),
}
NONRETRYABLE={"ValueError","ValidationError","StepLimitExceeded"}

def _facts(actions:list[dict[str,Any]],dut_state:dict[str,Any]):
    facts=set();ids=[];last_error=None
    for action in actions:
        obs=action.get("observation") or {}
        if not obs.get("success"):
            last_error=obs.get("error") or {};continue
        ids.append(obs.get("tool_call_id",""));name=action.get("tool_name");value=obs.get("result") or {}
        if name=="search_fault_knowledge" and value.get("documents"):facts.add("knowledge_evidence")
        elif name=="get_test_case" and value.get("test_case_id"):facts.add("test_case_evidence")
        elif name=="inject_fault" and value.get("state") in {"FAULT_INJECTED","DTC_ACTIVE"}:facts.add("fault_injected")
        elif name=="read_dtc" and value.get("dtc"):facts.add("dtc_observed")
        elif name=="judge_test_result" and value.get("result") in {"PASS","FAIL"}:facts.add("judgment_recorded")
        elif name=="recover_fault" and value.get("recovered") is True:facts.add("recovery_observed")
    if dut_state.get("state")=="RECOVERED" and not dut_state.get("active"):facts.add("recovery_postcondition")
    return facts,tuple(x for x in ids if x),last_error

def verify_completion(actions,task_spec,dut_state,*,cannot_continue=False):
    required=CAPABILITIES.get(task_spec.task_type)
    state=str(dut_state.get("state","UNKNOWN"))
    if not required:return ContractAssessment(CompletionStatus.UNKNOWN,(),(),(),"unsupported_goal",(),state)
    facts,ids,last_error=_facts(actions,dut_state);satisfied=tuple(x for x in required if x in facts);missing=tuple(x for x in required if x not in facts)
    if not missing:return ContractAssessment(CompletionStatus.COMPLETE,satisfied,required,(),"contract_satisfied",ids,state)
    permanent=bool(last_error and last_error.get("type") in NONRETRYABLE)
    if cannot_continue or permanent:return ContractAssessment(CompletionStatus.BLOCKED,satisfied,required,missing,"nonretryable_or_budget_exhausted",ids,state)
    return ContractAssessment(CompletionStatus.INCOMPLETE,satisfied,required,missing,"postconditions_unsatisfied",ids,state)

class CompletionVerifier:
    def __init__(self,config:CompletionVerifierConfig|None=None,progress_store:ProgressStore|None=None,session_id="local",task_id="task"):
        self.config=config or CompletionVerifierConfig();self.state=VerifierState();self.progress_store=progress_store;self.session_id=session_id;self.task_id=task_id
        saved=progress_store.load(session_id,task_id) if progress_store else None
        self.progress_guard=NoProgressGuard(self.config.max_no_progress,saved or ProgressState(session_id,task_id))
    def reset(self,preserve_progress=False):
        self.state=VerifierState()
        if not preserve_progress:self.progress_guard=NoProgressGuard(self.config.max_no_progress,ProgressState(self.session_id,self.task_id))
    def assess(self,actions,task_spec,dut_state,*,cannot_continue=False):return verify_completion(actions,task_spec,dut_state,cannot_continue=cannot_continue)
    def _snapshot(self,assessment,value=None):
        if value:return value
        return ProgressSnapshot(task_id=self.task_id,session_id=self.session_id,lifecycle_state="RUNNING",contract_status=assessment.status.value,missing_requirements=assessment.missing,dut_state=assessment.state,evidence_ids=assessment.evidence_call_ids)
    def _public_feedback(self,status,assessment,snapshot,decision):
        return {"type":"completion_feedback","status":status.value,"reason":"当前任务所要求的执行后置条件尚未满足" if status==CompletionStatus.INCOMPLETE else "当前任务无法继续完成","missing_requirements":list(assessment.missing),"completed_actions":list(snapshot.succeeded_action_ids),"failed_actions":list(snapshot.failed_action_ids),"current_authoritative_state":{"state":snapshot.dut_state,"version":snapshot.dut_version},"progress_status":decision.status,"progress_reason":decision.reason,"repeated_final_count":self.progress_guard.state.repeated_final_count,"allowed_next_actions":list(snapshot.allowed_next_actions),"remaining_attempts":max(0,self.config.max_corrections-self.state.corrections)}
    def _record_progress(self,fingerprint,event_type,blocked_evidence=False,invalid=False):
        for conflict_number in range(3):
            expected=self.progress_guard.state.version
            decision=self.progress_guard.record(fingerprint,event_type,blocked_evidence)
            if invalid:self.progress_guard.state.consecutive_invalid_tool_count+=1
            if not self.progress_store:return decision
            try:self.progress_store.save(self.progress_guard.state,expected_version=expected);return decision
            except ProgressConflictError:
                latest=self.progress_store.load(self.session_id,self.task_id)
                if latest is None:raise RuntimeError("progress state disappeared during CAS retry")
                self.progress_guard=NoProgressGuard(self.config.max_no_progress,latest)
        raise RuntimeError("progress CAS conflict retry limit exceeded")
    def handle_premature_final(self,assessment,raw_output,progress_snapshot=None):
        if not self.config.enabled or assessment.status==CompletionStatus.COMPLETE:return {"allow_final":True,"feedback":None}
        if self.state.first_final_was_complete is None:self.state.first_final_was_complete=False
        self.state.premature_finals+=1
        snapshot=self._snapshot(assessment,progress_snapshot);decision=self._record_progress(build_fingerprint(snapshot),"final",blocked_evidence=assessment.status==CompletionStatus.BLOCKED)
        self.state.repeated_final_count=self.progress_guard.state.repeated_final_count
        if assessment.status==CompletionStatus.BLOCKED:return {"allow_final":True,"blocked":True,"feedback":self._public_feedback(assessment.status,assessment,snapshot,decision)}
        feedback=self._public_feedback(assessment.status,assessment,snapshot,decision)
        if decision.limit_reached or self.state.corrections>=self.config.max_corrections:return {"allow_final":False,"limit_exhausted":True,"terminal_recommendation":decision.terminal_recommendation or "BUDGET_EXHAUSTED","no_progress":decision.status!="PROGRESS","repeated_final":decision.status=="REPEATED_FINAL","feedback":feedback}
        self.state.corrections+=1;self.state.interventions+=1
        self.state.events.append({"event_type":"verifier_feedback","trigger":"premature_final","raw_model_output":raw_output,"public_feedback":feedback,"private_reason_hash":assessment.reason_code})
        return {"allow_final":False,"no_progress":decision.status!="PROGRESS","repeated_final":decision.status=="REPEATED_FINAL","feedback":feedback}
    def observe_tool_decision(self,progress_snapshot,valid=True):
        decision=self._record_progress(build_fingerprint(progress_snapshot),"tool",invalid=not valid)
        return decision
    def handle_overcontinue(self,assessment,raw_call):
        if not self.config.enabled or assessment.status!=CompletionStatus.COMPLETE:return {"block_tool":False,"feedback":None}
        self.state.overcontinue_attempts+=1
        if self.state.corrections>=self.config.max_corrections:return {"block_tool":True,"limit_exhausted":True,"feedback":{"type":"completion_feedback","status":"complete","reason":"任务后置条件已经满足，请结束任务","last_observed_state":assessment.state,"remaining_attempts":0}}
        self.state.corrections+=1;self.state.interventions+=1;feedback={"type":"completion_feedback","status":"complete","reason":"任务后置条件已经满足，请结束任务","last_observed_state":assessment.state,"remaining_attempts":max(0,self.config.max_corrections-self.state.corrections)}
        self.state.events.append({"event_type":"overcontinue_attempt","raw_tool_call":raw_call,"public_feedback":feedback,"private_reason_hash":assessment.reason_code})
        return {"block_tool":True,"feedback":feedback}

FORBIDDEN_FEEDBACK_KEYS={"ground_truth","expected_tools","expected_dtc","oracle","reward","next_tool"}
def audit_feedback(value):
    text_keys=set()
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():text_keys.add(str(k).lower());walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(value);return sorted(FORBIDDEN_FEEDBACK_KEYS & text_keys)
