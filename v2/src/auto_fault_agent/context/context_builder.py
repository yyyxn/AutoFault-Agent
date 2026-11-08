from __future__ import annotations
import hashlib,json,time
from .context_schema import ContextBuildResult

class ContextBuilder:
    def __init__(self,budget_controller,compactor):self.budget=budget_controller;self.compactor=compactor
    def build(self,*,task,context,dut_snapshot,ledger,progress_state,assessment,messages,system_prompt=""):
        started=time.perf_counter();rows=ledger.list_actions(context.session_id,context.task_id) if ledger else []
        actions={"succeeded":[],"failed":[],"outcome_unknown":[],"executing":[]}
        for row in rows:
            item={k:row.get(k) for k in ("logical_action_id","tool_name","operation_id","idempotency_key","action_status")}
            bucket={"SUCCEEDED":"succeeded","FAILED":"failed","OUTCOME_UNKNOWN":"outcome_unknown","EXECUTING":"executing"}.get(row.get("action_status"))
            if bucket:actions[bucket].append(item)
        evidence=[];seen_evidence=set()
        for index,m in enumerate(messages):
            if m.get("role")!="tool":continue
            try:value=json.loads(m.get("content") or "{}")
            except Exception:value={"summary":str(m.get("content",""))[:300]}
            if value.get("success"):
                summary=str(value.get("result"))[:300]
                digest=hashlib.sha256(json.dumps({"tool":m.get("name"),"summary":summary},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                if digest in seen_evidence:continue
                seen_evidence.add(digest)
                evidence.append({"evidence_id":f"msg-{index}","source_tool":m.get("name"),"evidence_summary":summary,"verified_status":True,"source_reference":f"message:{index}","timestamp":None})
        evidence=evidence[-12:]
        compacted,summary,count=self.compactor.compact_messages(messages)
        task_info={"task_id":context.task_id,"session_id":context.session_id,"task_goal":task.instruction,"task_constraints":task.metadata.get("constraints",[]),"fault_id":task.fault_id,"task_type":task.task_type}
        auth={"dut_state":dut_snapshot.get("state"),"dut_state_version":dut_snapshot.get("version"),"current_fault_id":context.current_fault_id,"requested_fault_id":context.requested_fault_id,"observed_fault_id":context.observed_fault_id}
        completion={"status":getattr(assessment.status,"value",assessment.status),"missing_requirements":list(assessment.missing),"completed_requirements":list(assessment.satisfied),"reason_code":assessment.reason_code}
        progress={"progress_fingerprint":getattr(progress_state,"progress_fingerprint",None),"progress_version":getattr(progress_state,"version",0),"consecutive_no_progress_count":getattr(progress_state,"consecutive_no_progress_count",0),"repeated_final_count":getattr(progress_state,"repeated_final_count",0)}
        pinned={"task":task_info,"authoritative_state":auth,"completion":completion,"actions":actions,"evidence":evidence,"progress":progress}
        budget=self.budget.measure(system_prompt,pinned,evidence,compacted);status="READY" if budget["available_context_tokens"]>=0 else "CONTEXT_BUDGET_EXCEEDED"
        return ContextBuildResult(task_info,auth,completion,actions,evidence,progress,compacted,summary,count,budget,status)
