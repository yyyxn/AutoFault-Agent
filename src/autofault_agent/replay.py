from __future__ import annotations
import json,time,uuid
from importlib.resources import files
from .data import get_scenario
from .environment import SimulatedDUT
from .models import RunRequest,RunResult,TraceStep

def _templates():return json.loads(files("autofault_agent").joinpath("public_data/replay_templates.json").read_text(encoding="utf-8"))

def run_replay(req:RunRequest)->RunResult:
    started=time.perf_counter();case=get_scenario(req.scenario_id);template=_templates()[case.id];dut=SimulatedDUT(case);trace=[]
    for i,item in enumerate(template["steps"],1):
        if item["tool"]=="inject_fault":dut.active=case.fault_id;dut.state=type(dut.state).FAULT_INJECTED
        elif item["tool"]=="read_dtc":dut.state=type(dut.state).DTC_ACTIVE
        elif item["tool"]=="recover_fault":dut.active=None;dut.state=type(dut.state).RECOVERED
        trace.append(TraceStep(index=i,kind="tool",label=item["label"],status=item["observation"]["success"] and "success" or "error",latency_ms=item["latency_ms"],tool_call={"name":item["tool"],"arguments":item["arguments"]},observation=item["observation"]))
    latency=(time.perf_counter()-started)*1000+sum(x.latency_ms for x in trace)
    return RunResult(run_id=f"replay_{uuid.uuid4().hex[:12]}",mode="replay",model=req.model,verifier_enabled=req.verifier_enabled,scenario_id=case.id,goal=req.goal,trace=trace,final_answer=template["final_answer"],dut_state=dut.snapshot(),task_success=True,latency_ms=round(latency,3),disclosure="回放演示：使用预生成的公开合成轨迹，本次没有执行模型推理。")
