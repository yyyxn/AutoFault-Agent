from __future__ import annotations
import uuid
from typing import Any,Literal
from pydantic import BaseModel,Field
from .lifecycle import TaskLifecycle,TaskLifecycleState

class TaskSpec(BaseModel):
    task_id:str; task_type:str; instruction:str; fault_id:str
    initial_state:str="NORMAL"; scenario:str="normal"
    expected_tools:list[str]; ground_truth:dict[str,Any]
    difficulty:Literal["easy","medium","hard"]
    metadata:dict[str,Any]=Field(default_factory=lambda:{"data_source":"synthetic_demo"})

class TaskEnvironment:
    def __init__(self,task:TaskSpec,mode="baseline",output_dir="outputs/phase3"):
        from ..tools import ToolDispatcher
        self.task=task; self.mode=mode; self.output_dir=output_dir; self.dispatcher=ToolDispatcher(); self.harness=None; self.context=None; self.seed=0; self.actions=[]; self.last_observation=None; self.lifecycle=TaskLifecycle()
    def reset(self,seed=42):
        self.seed=seed; self.dispatcher.dut.reset(); self.dispatcher.dut.set_scenario(self.task.scenario); self.actions=[]; self.last_observation=None; self.lifecycle=TaskLifecycle(); self.lifecycle.transition(TaskLifecycleState.RUNNING,"task_reset")
        if self.task.initial_state=="DTC_ACTIVE":
            from .simulated_dut import DUTState
            saved=self.dispatcher.dut.scenario; self.dispatcher.dut.scenario="normal"; self.dispatcher.dut.active=self.task.fault_id; self.dispatcher.dut.state=DUTState.FAULT_INJECTED; self.dispatcher.dut.read_dtc(); self.dispatcher.dut.scenario=saved
        if self.mode=="harness":
            from ..harness import AgentHarness
            self.harness=AgentHarness(self.dispatcher,self.output_dir); self.context=self.harness.new_context(f"env_{self.task.task_id}_{seed}",self.task.task_id); self.context.task_lifecycle_state=self.lifecycle.state.value
        return self.get_state()
    def step(self,action):
        if self.done: raise RuntimeError("Task environment is already done")
        if self.lifecycle.state!=TaskLifecycleState.RUNNING: raise RuntimeError(f"Task is not ready for a tool call: {self.lifecycle.state.value}")
        name=action.get("tool_name"); args=dict(action.get("arguments",{}))
        logical_action_id=action.get("logical_action_id") or f"act_{uuid.uuid4().hex}"
        if not isinstance(logical_action_id,str) or not logical_action_id:raise ValueError("logical_action_id must be a non-empty string")
        self.lifecycle.transition(TaskLifecycleState.WAITING_TOOL,f"tool_requested:{name}")
        if self.context:self.context.task_lifecycle_state=self.lifecycle.state.value
        try: result=self.harness.execute(name,args,self.context,logical_action_id=logical_action_id) if self.harness else self.dispatcher.dispatch(name,args)
        except Exception:
            self.lifecycle.transition(TaskLifecycleState.FAILED_INTERNAL,f"tool_dispatch_exception:{name}")
            raise
        observation=result.model_dump();observation["logical_action_id"]=logical_action_id
        if self.context:observation["operation_id"]=self.context.current_operation_id
        self.actions.append({"logical_action_id":logical_action_id,"operation_id":observation.get("operation_id"),"tool_name":name,"arguments":args,"observation":observation}); self.last_observation=observation
        self.lifecycle.transition(TaskLifecycleState.RUNNING,f"tool_observed:{name}:{'success' if result.success else 'failure'}")
        if self.context:self.context.task_lifecycle_state=self.lifecycle.state.value
        return observation
    @property
    def done(self): return self.lifecycle.done
    def begin_verification(self):
        if self.lifecycle.state!=TaskLifecycleState.RUNNING: raise RuntimeError(f"Task is not ready for verification: {self.lifecycle.state.value}")
        self.lifecycle.transition(TaskLifecycleState.VERIFYING,"final_proposed")
        if self.context:self.context.task_lifecycle_state=self.lifecycle.state.value
    def resolve_verification(self,status,reason,*,continue_allowed=True):
        if self.lifecycle.state!=TaskLifecycleState.VERIFYING: raise RuntimeError(f"Task is not being verified: {self.lifecycle.state.value}")
        value=getattr(status,"value",status)
        if value=="complete": target=TaskLifecycleState.COMPLETED
        elif value=="blocked": target=TaskLifecycleState.BLOCKED
        elif continue_allowed: target=TaskLifecycleState.RUNNING
        else: target=TaskLifecycleState.CANCELLED
        self.lifecycle.transition(target,f"completion_contract:{value}:{reason}")
        if self.context:self.context.task_lifecycle_state=self.lifecycle.state.value
    def exhaust_budget(self,reason="budget_exhausted"):
        if self.lifecycle.state not in {TaskLifecycleState.RUNNING,TaskLifecycleState.VERIFYING,TaskLifecycleState.WAITING_TOOL}: raise RuntimeError(f"Cannot exhaust budget from {self.lifecycle.state.value}")
        self.lifecycle.transition(TaskLifecycleState.BUDGET_EXHAUSTED,reason)
    def cancel(self,reason="cancelled"):
        if not self.done:self.lifecycle.transition(TaskLifecycleState.CANCELLED,reason)
    def fail_internal(self,reason):
        if not self.done:self.lifecycle.transition(TaskLifecycleState.FAILED_INTERNAL,reason)
    def get_state(self):
        public_last=None if not self.actions else {"tool_name":self.actions[-1]["tool_name"],"success":self.actions[-1]["observation"]["success"]}
        return {"task_id":self.task.task_id,"state":self.dispatcher.dut.state.value,"scenario":self.task.scenario,"step":len(self.actions),"last_observation":public_last,"done":self.done,"lifecycle_state":self.lifecycle.state.value,"lifecycle_revision":self.lifecycle.revision,"data_source":"synthetic_demo"}
    def is_done(self): return self.done
    def get_ground_truth(self): return self.task.ground_truth.copy()
    def evaluate(self):
        names=[x["tool_name"] for x in self.actions]; gt=self.task.ground_truth; actual_dtc=None; judge=None
        for x in self.actions:
            value=x["observation"].get("result") or {}
            if x["tool_name"]=="read_dtc" and x["observation"]["success"]: actual_dtc=value.get("dtc")
            if x["tool_name"]=="judge_test_result" and x["observation"]["success"]: judge=value.get("result")
        tools_ok=names==self.task.expected_tools; dtc_ok=actual_dtc in {None,gt.get("expected_dtc")} if "read_dtc" not in names else actual_dtc==gt.get("observed_dtc",gt.get("expected_dtc"))
        expected_judge=gt.get("expected_judge"); judge_ok=expected_judge is None or judge==expected_judge
        recovered=self.dispatcher.dut.state.value=="RECOVERED" if "recover_fault" in self.task.expected_tools else True
        success=tools_ok and dtc_ok and judge_ok and recovered and all(x["observation"]["success"] for x in self.actions)
        return {"success":success,"expected":{"tools":self.task.expected_tools,"dtc":gt.get("observed_dtc",gt.get("expected_dtc")),"judge":expected_judge,"recovered":True if "recover_fault" in self.task.expected_tools else None},"actual":{"tools":names,"dtc":actual_dtc,"judge":judge,"recovered":self.dispatcher.dut.state.value=="RECOVERED"},"data_source":"synthetic_demo"}
