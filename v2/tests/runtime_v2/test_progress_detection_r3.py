from __future__ import annotations

from types import SimpleNamespace

from auto_fault_agent.harness.completion_verifier import (
    CompletionStatus, CompletionVerifier, CompletionVerifierConfig, ContractAssessment
)
from auto_fault_agent.harness.progress import (
    NoProgressGuard, ProgressSnapshot, ProgressState, ProgressStore, build_fingerprint
)


def assessment(status=CompletionStatus.INCOMPLETE, missing=("fault_injected",)):
    required=("knowledge_evidence","fault_injected")
    satisfied=tuple(x for x in required if x not in missing)
    return ContractAssessment(status,satisfied,required,missing,"test",(),"NORMAL")


def snap(**changes):
    value=dict(task_id="t",session_id="s",lifecycle_state="RUNNING",contract_status="incomplete",missing_requirements=("fault_injected",),dut_state="NORMAL",dut_version=1,succeeded_action_ids=("a1",),operation_ids=("o1",),evidence_ids=("e1",),context_version=1,failed_action_ids=(),allowed_next_actions=("inject_fault",))
    value.update(changes);return ProgressSnapshot(**value)


def verifier():return CompletionVerifier(CompletionVerifierConfig(enabled=True,max_corrections=3,max_no_progress=2))


def test_complete_final_is_accepted():
    assert verifier().handle_premature_final(assessment(CompletionStatus.COMPLETE,()),"done")["allow_final"]

def test_incomplete_final_is_rejected():
    assert not verifier().handle_premature_final(assessment(),"done",snap())["allow_final"]

def test_identical_final_is_repeated_without_progress():
    v=verifier();v.handle_premature_final(assessment(),"same",snap());r=v.handle_premature_final(assessment(),"same",snap());assert r["no_progress"] and r["repeated_final"]

def test_different_words_cannot_bypass_progress_detection():
    v=verifier();v.handle_premature_final(assessment(),"F323 未激活",snap());r=v.handle_premature_final(assessment(),"当前没有故障，无法完成",snap());assert r["repeated_final"]

def test_same_text_after_real_progress_is_not_repeated():
    v=verifier();v.handle_premature_final(assessment(),"same",snap());r=v.handle_premature_final(assessment(missing=()),"same",snap(missing_requirements=(),dut_version=2,dut_state="FAULT_INJECTED"));assert not r.get("repeated_final",False)

def test_dut_version_change_is_progress():
    assert build_fingerprint(snap()).compare(build_fingerprint(snap(dut_version=2)))[0]

def test_new_successful_action_is_progress():
    assert build_fingerprint(snap()).compare(build_fingerprint(snap(succeeded_action_ids=("a1","a2"))))[0]

def test_new_verified_evidence_is_progress():
    assert build_fingerprint(snap()).compare(build_fingerprint(snap(evidence_ids=("e1","e2"))))[0]

def test_same_readonly_evidence_is_not_progress():
    assert not build_fingerprint(snap()).compare(build_fingerprint(snap()))[0]

def test_new_readonly_evidence_is_progress():
    assert build_fingerprint(snap()).compare(build_fingerprint(snap(evidence_ids=("e1","knowledge-2"))))[0]

def test_timestamp_is_not_part_of_fingerprint():
    assert build_fingerprint(snap()).digest==build_fingerprint(snap()).digest

def test_attempt_count_is_not_part_of_snapshot():
    assert "attempt" not in build_fingerprint(snap()).components

def test_no_progress_limit_is_reached():
    g=NoProgressGuard(2);f=build_fingerprint(snap());g.record(f,"final");g.record(f,"final");assert g.record(f,"final").limit_reached

def test_progress_resets_no_progress_count():
    g=NoProgressGuard(2);f=build_fingerprint(snap());g.record(f,"final");g.record(f,"final");d=g.record(build_fingerprint(snap(dut_version=2)),"final");assert d.status=="PROGRESS" and g.state.consecutive_no_progress_count==0

def test_text_change_does_not_reset_count():
    v=verifier();v.handle_premature_final(assessment(),"one",snap());v.handle_premature_final(assessment(),"two",snap());assert v.progress_guard.state.consecutive_no_progress_count==1

def test_limit_never_marks_completed():
    g=NoProgressGuard(1);f=build_fingerprint(snap());g.record(f,"final");d=g.record(f,"final");assert d.terminal_recommendation=="BUDGET_EXHAUSTED"

def test_blocked_evidence_recommends_blocked():
    g=NoProgressGuard(1);f=build_fingerprint(snap());g.record(f,"final");d=g.record(f,"final",blocked_evidence=True);assert d.terminal_recommendation=="BLOCKED"

def test_without_blocked_evidence_recommends_budget_exhausted():
    g=NoProgressGuard(1);f=build_fingerprint(snap());g.record(f,"final");assert g.record(f,"final").terminal_recommendation=="BUDGET_EXHAUSTED"

def test_feedback_lists_missing_requirements():
    r=verifier().handle_premature_final(assessment(),"x",snap());assert r["feedback"]["missing_requirements"]==["fault_injected"]

def test_feedback_lists_completed_actions_without_reasking():
    r=verifier().handle_premature_final(assessment(),"x",snap());assert r["feedback"]["completed_actions"]==["a1"] and "inject_fault" in r["feedback"]["allowed_next_actions"]

def test_unverified_model_text_is_not_authoritative_state():
    r=verifier().handle_premature_final(assessment(),"DUT 已恢复",snap());assert r["feedback"]["current_authoritative_state"]["state"]=="NORMAL"

def test_replanning_feedback_allows_continuation():
    r=verifier().handle_premature_final(assessment(),"x",snap());assert not r["allow_final"] and not r.get("limit_exhausted",False)

def test_progress_store_survives_restart(tmp_path):
    store=ProgressStore(tmp_path/"progress.sqlite3");state=ProgressState(session_id="s",task_id="t",consecutive_no_progress_count=2);store.save(state);assert ProgressStore(tmp_path/"progress.sqlite3").load("s","t").consecutive_no_progress_count==2

def test_progress_store_isolates_sessions(tmp_path):
    store=ProgressStore(tmp_path/"p.sqlite3");store.save(ProgressState(session_id="a",task_id="t",repeated_final_count=1));store.save(ProgressState(session_id="b",task_id="t",repeated_final_count=3));assert store.load("a","t").repeated_final_count==1

def test_restore_same_state_does_not_double_count(tmp_path):
    store=ProgressStore(tmp_path/"p.sqlite3");state=ProgressState(session_id="s",task_id="t",consecutive_no_progress_count=1);store.save(state);loaded=store.load("s","t");store.save(loaded);assert store.load("s","t").consecutive_no_progress_count==1
