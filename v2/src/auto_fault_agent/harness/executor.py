from __future__ import annotations
import hashlib,json,re,time,uuid
from concurrent.futures import ThreadPoolExecutor,TimeoutError as FutureTimeout
from datetime import datetime,timezone
from pathlib import Path
from ..schemas import ToolResult
from .action_ledger import ActionLedger,canonical_json
from .checkpoint import CheckpointStore
from .config import HarnessConfig
from .context import ExecutionContext
from .recovery import RecoveryManager

SCHEMAS={
 "search_fault_knowledge":{"required":{"query":str},"optional":{"top_k":int}},
 "get_test_case":{"required":{"fault_id":str}},"inject_fault":{"required":{"fault_id":str}},
 "read_dtc":{"required":{}},"judge_test_result":{"required":{"fault_id":str,"dtc":str}},
 "recover_fault":{"required":{"fault_id":str}},
}

class AgentHarness:
    def __init__(self,dispatcher,output_dir,config=None):
        self.dispatcher=dispatcher;self.config=config or HarnessConfig();self.output_dir=Path(output_dir)
        self.store=CheckpointStore(self.output_dir/"checkpoints");self.trace_dir=self.output_dir/"traces";self.trace_dir.mkdir(parents=True,exist_ok=True)
        self.ledger=ActionLedger(self.output_dir/self.config.ledger_filename);self.recovery=RecoveryManager();self.last_attempts=[];self.last_checkpoint=None
        self.metrics={"logical_actions":0,"tool_attempts":0,"timeouts":0,"outcome_unknown":0,"reconciliation_successes":0,"idempotency_intercepts":0}
    def new_context(self,session_id,task_id=None):
        snapshot=self.dispatcher.dut.snapshot()
        return ExecutionContext(session_id=session_id,task_id=task_id or f"task_{uuid.uuid4().hex[:8]}",current_fault_id=snapshot.get("active"),dut_state=snapshot.get("state"),dut_state_version=int(snapshot.get("version",0)))
    def validate(self,name,args):
        if name not in SCHEMAS:return {"type":"ValidationError","message":f"Unknown tool: {name}"}
        schema=SCHEMAS[name]
        for key,kind in schema["required"].items():
            if key not in args:return {"type":"ValidationError","message":f"Missing required argument: {key}"}
            if not isinstance(args[key],kind):return {"type":"ValidationError","message":f"Invalid type for {key}: expected {kind.__name__}"}
        allowed=set(schema["required"])|set(schema.get("optional",{}));extra=set(args)-allowed
        if extra:return {"type":"ValidationError","message":f"Unknown arguments: {sorted(extra)}"}
        for key,kind in schema.get("optional",{}).items():
            if key in args and not isinstance(args[key],kind):return {"type":"ValidationError","message":f"Invalid type for {key}: expected {kind.__name__}"}
        if "fault_id" in args and not re.fullmatch(r"F\d{3}",args["fault_id"],re.I):return {"type":"ValidationError","message":"fault_id must match F###"}
        return None
    def _call_dispatcher(self,action,args):
        method=getattr(self.dispatcher,"dispatch_operation",None)
        return method(action["tool_name"],args,action["operation_id"],action["idempotency_key"]) if method else self.dispatcher.dispatch(action["tool_name"],args)
    def _run_attempt(self,action,attempt,args):
        result=self._call_dispatcher(action,args);status="SUCCEEDED" if result.success else "FAILED"
        was_unknown=(self.ledger.get_action(action["logical_action_id"])["action_status"]=="OUTCOME_UNKNOWN")
        self.ledger.finish(action["logical_action_id"],attempt["attempt_id"],status,result=result.result,error=result.error)
        if was_unknown:self.metrics["reconciliation_successes"]+=1
        return result
    def _dispatch(self,action,attempt,args):
        if not self.config.enable_timeout:return self._run_attempt(action,attempt,args)
        pool=ThreadPoolExecutor(max_workers=1);future=pool.submit(self._run_attempt,action,attempt,args)
        try:return future.result(timeout=self.config.timeout_seconds)
        except FutureTimeout:
            error={"type":"OutcomeUnknown","message":f"Tool exceeded {self.config.timeout_seconds}s; external outcome is unknown","operation_id":action["operation_id"]}
            self.ledger.mark_timeout(action["logical_action_id"],attempt["attempt_id"],error);self.metrics["timeouts"]+=1;self.metrics["outcome_unknown"]+=1
            return ToolResult(tool_call_id=action["operation_id"],tool_name=action["tool_name"],success=False,error=error,latency_ms=self.config.timeout_seconds*1000)
        finally:pool.shutdown(wait=False,cancel_futures=True)
    @staticmethod
    def _stored_result(action,error_type=None):
        result=json.loads(action["result_json"]) if action.get("result_json") else None;error=json.loads(action["error_json"]) if action.get("error_json") else None
        if error_type:error={"type":error_type,"message":"Logical action is not safe to execute again","operation_id":action["operation_id"]}
        return ToolResult(tool_call_id=action["operation_id"],tool_name=action["tool_name"],success=action["action_status"]=="SUCCEEDED",result=result,error=error,latency_ms=0)
    def execute(self,name,args,context,*,logical_action_id=None,idempotency_key=None):
        context.requested_fault_id=args.get("fault_id")
        if self.config.enable_step_limit and context.step_count>=self.config.max_steps:return self._failure(name,{"type":"StepLimitExceeded","message":f"Maximum {self.config.max_steps} steps exceeded"},context,args)
        validation=self.validate(name,args)
        if validation:return self._failure(name,validation,context,args)
        if logical_action_id is None:
            current=self.ledger.get_action(context.current_logical_action_id) if context.current_logical_action_id else None
            same_unknown=bool(current and current["action_status"] in {"EXECUTING","OUTCOME_UNKNOWN","FAILED"} and current["tool_name"]==name and current["arguments_json"]==canonical_json(args))
            if same_unknown:logical_action_id=current["logical_action_id"]
            else:
                raw=f"{context.session_id}\0{context.task_id}\0{context.step_count+1}\0{name}\0{canonical_json(args)}"
                logical_action_id="act_"+hashlib.sha256(raw.encode()).hexdigest()[:24]
        action=self.ledger.get_or_create_action(context.session_id,context.task_id,name,args,logical_action_id=logical_action_id,idempotency_key=idempotency_key)
        context.current_logical_action_id=action["logical_action_id"];context.current_operation_id=action["operation_id"];context.current_idempotency_key=action["idempotency_key"]
        self.metrics["logical_actions"]=len(self.ledger.list_actions(context.session_id,context.task_id))
        if action["action_status"]=="SUCCEEDED":
            self.metrics["idempotency_intercepts"]+=1;result=self._stored_result(action);self._sync_authoritative_state(name,result,context);return result
        if action["action_status"]=="FAILED":self.metrics["idempotency_intercepts"]+=1;return self._stored_result(action)
        if action["action_status"]=="OUTCOME_UNKNOWN":
            result=self.reconcile(action["logical_action_id"],context)
            if result.error and result.error.get("type")=="OutcomeUnknown":self.metrics["idempotency_intercepts"]+=1
            return result
        if action["action_status"]=="EXECUTING":self.metrics["idempotency_intercepts"]+=1;return self._stored_result(action,"ActionInProgress")
        context.step_count+=1;attempts=[];max_attempts=1+self.config.max_retries if self.config.enable_retry else 1;result=None
        for attempt_number in range(1,max_attempts+1):
            attempt=self.ledger.claim(action["logical_action_id"])
            if attempt is None:return self._stored_result(self.ledger.get_action(action["logical_action_id"]),"ActionInProgress")
            context.current_attempt_id=attempt["attempt_id"];self.metrics["tool_attempts"]+=1;started=time.perf_counter();result=self._dispatch(action,attempt,args)
            row=self._attempt_row(context,name,args,attempt_number,result,started,action,attempt);attempts.append(row);context.trajectory.append(row);self._trace(context,row)
            if result.success or (result.error or {}).get("type")=="OutcomeUnknown":break
            if attempt_number>=max_attempts or not self.recovery.retryable(result.error):break
            self.ledger.force_status(action["logical_action_id"],"PENDING");context.retry_count+=1
        self.last_attempts=attempts;self._update_context_result(name,args,result,context);current=self.ledger.get_action(action["logical_action_id"])
        if self.config.enable_checkpoint:self.last_checkpoint=self.store.save(context,self.dispatcher.dut,current)
        return result
    def reconcile(self,logical_action_id,context):
        action=self.ledger.get_action(logical_action_id)
        if not action:raise KeyError(logical_action_id)
        query=getattr(self.dispatcher,"query_operation",None);observed=query(action["operation_id"]) if query else None
        if observed is not None:
            attempts=self.ledger.attempts(logical_action_id)
            if attempts:self.ledger.finish(logical_action_id,attempts[-1]["attempt_id"],"SUCCEEDED" if observed.success else "FAILED",result=observed.result,error=observed.error)
            if observed.success:self._sync_authoritative_state(action["tool_name"],observed,context);context.last_reliable_observation=observed.model_dump();self.metrics["reconciliation_successes"]+=1
            return observed
        snapshot=self.dispatcher.dut.snapshot();args=json.loads(action["arguments_json"]);inferred=None
        if action["tool_name"]=="inject_fault" and snapshot.get("active")==args.get("fault_id"):inferred={"fault_id":args.get("fault_id"),"state":snapshot.get("state"),"reconciled_from":"dut_snapshot"}
        elif action["tool_name"]=="recover_fault" and snapshot.get("active") is None and snapshot.get("state")=="RECOVERED":inferred={"fault_id":args.get("fault_id"),"state":snapshot.get("state"),"recovered":True,"reconciled_from":"dut_snapshot"}
        if inferred is not None:
            attempts=self.ledger.attempts(logical_action_id)
            if attempts:self.ledger.finish(logical_action_id,attempts[-1]["attempt_id"],"SUCCEEDED",result=inferred)
            result=ToolResult(tool_call_id=action["operation_id"],tool_name=action["tool_name"],success=True,result=inferred,latency_ms=0);self._sync_authoritative_state(action["tool_name"],result,context);context.last_reliable_observation=result.model_dump();self.metrics["reconciliation_successes"]+=1;return result
        return self._stored_result(action,"OutcomeUnknown")
    def _attempt_row(self,context,name,args,attempt_number,result,started,action,attempt):
        return {"timestamp":datetime.now(timezone.utc).isoformat(),"session_id":context.session_id,"task_id":context.task_id,"step":context.step_count,"attempt":attempt_number,"attempt_id":attempt["attempt_id"],"logical_action_id":action["logical_action_id"],"operation_id":action["operation_id"],"idempotency_key":action["idempotency_key"],"tool":name,"input":args,"output":result.result,"success":result.success,"status":"success" if result.success else "failed","error":result.error,"latency_ms":round((time.perf_counter()-started)*1000,3)}
    def _update_context_result(self,name,args,result,context):
        context.last_tool=name;context.last_input=args;context.last_output=result.result;context.last_status="success" if result.success else "failed";context.last_error=None if result.success else result.error.get("message");context.last_error_type=None if result.success else result.error.get("type")
        if result.success:self._sync_authoritative_state(name,result,context);context.last_reliable_observation=result.model_dump()
        if result.success and name=="read_dtc":context.last_dtc=result.result.get("dtc")
    def _sync_authoritative_state(self,name,result,context):
        snapshot=self.dispatcher.dut.snapshot();version=int(snapshot.get("version",0));value=result.result or {}
        if version<context.dut_state_version:raise RuntimeError(f"DUT state version regressed: {version} < {context.dut_state_version}")
        if name=="inject_fault" and (value.get("fault_id")!=snapshot.get("active") or not snapshot.get("active")):raise RuntimeError("inject_fault result does not match authoritative DUT state")
        if name=="recover_fault" and (value.get("recovered") is not True or snapshot.get("active") is not None):raise RuntimeError("recover_fault result does not match authoritative DUT state")
        context.observed_fault_id=value.get("fault_id");context.current_fault_id=snapshot.get("active");context.dut_state=snapshot.get("state");context.dut_state_version=version
    def _failure(self,name,error,context,args):
        result=ToolResult(tool_call_id=f"call_{uuid.uuid4().hex[:10]}",tool_name=name,success=False,error=error,latency_ms=0);row={"timestamp":datetime.now(timezone.utc).isoformat(),"session_id":context.session_id,"task_id":context.task_id,"step":context.step_count,"attempt":1,"tool":name,"input":args,"output":None,"success":False,"status":"failed","error":error,"latency_ms":0}
        context.trajectory.append(row);self._trace(context,row);self.last_attempts=[row];context.last_tool=name;context.last_input=args;context.last_status="failed";context.last_error=error["message"];context.last_error_type=error["type"];return result
    def _trace(self,context,row):
        path=self.trace_dir/f"{context.session_id}.jsonl"
        with path.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False,default=str)+"\n")
    def resume(self,session_id):
        path=self.store.latest(session_id)
        if not path:raise FileNotFoundError(f"No checkpoint for {session_id}")
        payload=self.store.read(path);checkpoint_action=(payload.get("ledger") or {}).get("logical_action")
        if checkpoint_action:
            current=self.ledger.get_action(checkpoint_action["logical_action_id"])
            if current and current["action_status"]!=checkpoint_action["action_status"]:raise RuntimeError("checkpoint and ledger action status mismatch")
        self.ledger.recover_incomplete(session_id);self.last_checkpoint=path;context=self.store.load(path,self.dispatcher.dut)
        if context.current_logical_action_id:
            action=self.ledger.get_action(context.current_logical_action_id)
            if action and action["action_status"]=="OUTCOME_UNKNOWN":self.reconcile(action["logical_action_id"],context)
        return context
