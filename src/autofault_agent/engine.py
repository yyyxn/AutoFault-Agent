from __future__ import annotations
import asyncio,json,time,uuid
from .data import get_scenario
from .live import ModelToolPolicy,parse_action
from .models import RunRequest,RunResult,TraceStep
from .tools import ToolDispatcher
from .verifier import CompletionVerifier

async def run_live(req:RunRequest)->RunResult:
    case=get_scenario(req.scenario_id);dispatcher=ToolDispatcher(case);verifier=CompletionVerifier(req.verifier_enabled);policy=ModelToolPolicy(req.model)
    messages=[{"role":"system","content":"Use only provided synthetic tools. Never claim access to a real vehicle. Return a tool call or a concise final answer."},{"role":"user","content":req.goal}]
    trace=[];started=time.perf_counter();final="";success=False
    for turn in range(9):
        raw,latency=await asyncio.to_thread(policy.generate,messages,160);call=parse_action(raw)
        if call:
            obs=dispatcher.dispatch(call.name,call.arguments);trace.append(TraceStep(index=len(trace)+1,kind="tool",label=call.name,status="success" if obs["success"] else "error",latency_ms=latency+obs["latency_ms"],tool_call=call,observation=obs));messages += [{"role":"assistant","content":raw},{"role":"tool","content":json.dumps(obs,ensure_ascii=False)}];continue
        assessment=verifier.assess(trace,dispatcher.dut.snapshot());feedback=verifier.feedback(assessment)
        trace.append(TraceStep(index=len(trace)+1,kind="model",label="final_attempt",status=assessment["status"],latency_ms=latency,model_output=raw))
        if feedback:
            trace.append(TraceStep(index=len(trace)+1,kind="verifier",label="completion_feedback",status=feedback["status"],verifier_feedback=feedback));messages += [{"role":"assistant","content":raw},{"role":"user","content":json.dumps(feedback)}];continue
        final=raw;success=assessment["status"]=="complete";break
    return RunResult(run_id=f"live_{uuid.uuid4().hex[:12]}",mode="live",model=req.model,verifier_enabled=req.verifier_enabled,scenario_id=case.id,goal=req.goal,trace=trace,final_answer=final or "Execution stopped before an accepted final answer.",dut_state=dispatcher.dut.snapshot(),task_success=success,latency_ms=round((time.perf_counter()-started)*1000,3),disclosure="Live Demo: local Qwen inference against an in-memory synthetic DUT; no real vehicle connection.")
