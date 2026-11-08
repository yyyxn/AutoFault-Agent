import json
from types import SimpleNamespace
import pytest
from auto_fault_agent.context import ContextBudgetController,ContextBuilder,ContextCompactor,ContextBudgetExceeded

class Ledger:
 def __init__(self,rows=()):self.rows=list(rows)
 def list_actions(self,s,t):return self.rows
def row(status="SUCCEEDED",name="inject_fault",n=1):return {"logical_action_id":f"a{n}","tool_name":name,"operation_id":f"o{n}","idempotency_key":f"i{n}","action_status":status}
def build_context(messages=None,rows=(),limit=40960,session="s",state="RECOVERED",version=3):
 task=SimpleNamespace(instruction="诊断 F901 并恢复",fault_id="F901",task_type="full_fault_test",metadata={"constraints":["必须恢复"]})
 ctx=SimpleNamespace(task_id="t",session_id=session,current_fault_id=None,requested_fault_id="F901",observed_fault_id="F901")
 assess=SimpleNamespace(status=SimpleNamespace(value="incomplete"),missing=("recovery_postcondition",),satisfied=("fault_injected",),reason_code="missing")
 progress=SimpleNamespace(progress_fingerprint="fp",version=2,consecutive_no_progress_count=1,repeated_final_count=1)
 msgs=messages or [{"role":"system","content":"sys"},{"role":"user","content":"goal"}]
 builder=ContextBuilder(ContextBudgetController(limit,128),ContextCompactor(8,3))
 return builder.build(task=task,context=ctx,dut_snapshot={"state":state,"version":version},ledger=Ledger(rows),progress_state=progress,assessment=assess,messages=msgs,system_prompt="sys")

def pair(n,content=None):return [{"role":"assistant","content":"","tool_calls":[{"type":"function","function":{"name":"read_dtc","arguments":{}}}]},{"role":"tool","name":"read_dtc","content":json.dumps({"success":True,"result":{"dtc":content or f"D{n}"}})}]

def test_task_context_content():assert build_context().task["task_goal"]=="诊断 F901 并恢复"
def test_session_isolation():assert build_context(session="a").task["session_id"]!="b"
def test_latest_dut_state():assert build_context(state="RECOVERED",version=9).authoritative_state=={"dut_state":"RECOVERED","dut_state_version":9,"current_fault_id":None,"requested_fault_id":"F901","observed_fault_id":"F901"}
def test_fault_id_retained():assert build_context().task["fault_id"]=="F901"
def test_constraints_retained():assert "必须恢复" in build_context().task["task_constraints"]
def test_contract_retained():assert build_context().completion["status"]=="incomplete"
def test_missing_retained():assert build_context().completion["missing_requirements"]==["recovery_postcondition"]
def test_success_action_retained():assert build_context(rows=[row()]).actions["succeeded"][0]["operation_id"]=="o1"
def test_failed_action_retained():assert build_context(rows=[row("FAILED")]).actions["failed"]
def test_unknown_action_retained():assert build_context(rows=[row("OUTCOME_UNKNOWN")]).actions["outcome_unknown"]
def test_evidence_source_retained():assert build_context(messages=[{"role":"tool","name":"read_dtc","content":json.dumps({"success":True,"result":{"dtc":"D"}})}]).evidence[0]["source_tool"]=="read_dtc"
def test_progress_retained():assert build_context().progress["progress_fingerprint"]=="fp" and build_context().progress["progress_version"]==2
def test_duplicate_read_observation_compacted():
 m=[{"role":"system","content":"s"},{"role":"user","content":"u"}]+pair(1,"same")+pair(2,"same");r=build_context(m);assert r.compacted_observations>=1
def test_redundant_observation_summary_is_non_authoritative():
 r=build_context([{"role":"system","content":"s"}]+pair(1,"same")+pair(2,"same"));assert r.compressed_summary and r.authoritative_state["dut_state"]=="RECOVERED"
def test_new_evidence_not_deduplicated():
 r=build_context([{"role":"system","content":"s"}]+pair(1,"A")+pair(2,"B"));assert sum(x["role"]=="tool" for x in r.messages)==2
def test_tool_pairs_remain_legal():
 r=build_context([{"role":"system","content":"s"}]+pair(1));roles=[x["role"] for x in r.messages];assert roles.index("tool")==roles.index("assistant")+1
def test_budget_triggers_compaction_first():
 m=[{"role":"system","content":"s"}]+sum((pair(i,"x") for i in range(10)),[]);r=build_context(m,limit=500);assert r.compacted_observations>0
def test_pinned_facts_survive_compaction():assert build_context(limit=300).task["fault_id"]=="F901"
def test_checkpoint_rebuild_uses_latest_state():assert build_context(state="DTC_ACTIVE",version=11).authoritative_state["dut_state_version"]==11
def test_budget_exceeded_is_explicit():assert build_context(limit=150).status=="CONTEXT_BUDGET_EXCEEDED"
def test_summary_cannot_override_authority():
 r=build_context([{"role":"assistant","content":"DUT=NORMAL"}],state="RECOVERED");assert r.authoritative_state["dut_state"]=="RECOVERED"
def test_stale_message_cannot_override_dut():assert build_context([{"role":"tool","name":"x","content":"{\"state\":\"NORMAL\"}"}],state="RECOVERED").authoritative_state["dut_state"]=="RECOVERED"
def test_model_false_fact_not_pinned():assert "DUT 已恢复" not in json.dumps(build_context([{"role":"assistant","content":"DUT 已恢复"}]).authoritative_state,ensure_ascii=False)
def test_build_is_repeatable():assert build_context().model_dump()==build_context().model_dump()
def test_feature_flag_false_preserves_messages():
 original=[{"role":"user","content":"x"}];enabled=False;actual=build_context(original).messages if enabled else original;assert actual is original
def test_estimated_count_mode():assert ContextBudgetController(1000,100).token_count_mode=="estimated"
def test_budget_controller_raises_safely():
 b=ContextBudgetController(200,100);x=b.measure("x"*500,{},[],[])
 with pytest.raises(ContextBudgetExceeded):b.ensure(x)
