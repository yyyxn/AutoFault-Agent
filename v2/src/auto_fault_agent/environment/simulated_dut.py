from enum import Enum
from ..data import faults
class DUTState(str,Enum): NORMAL="NORMAL"; FAULT_INJECTED="FAULT_INJECTED"; DTC_ACTIVE="DTC_ACTIVE"; RECOVERED="RECOVERED"
class SimulatedDUT:
    def __init__(self): self.cases={x.fault_id:x for x in faults()}; self.state=DUTState.NORMAL; self.active=None; self.failures={}; self.scenario="normal"; self.version=0
    def reset(self): self.state=DUTState.NORMAL; self.active=None; self.failures={}; self.scenario="normal"; self.version+=1
    def set_scenario(self,scenario):
        if scenario not in {"normal","tool_error","timeout","transient_tool_error","transient_timeout","dtc_mismatch","unknown_fault"}: raise ValueError(f"Unknown scenario: {scenario}")
        if self.scenario!=scenario:self.scenario=scenario
    def inject_fault(self,fault_id):
        if fault_id not in self.cases: raise ValueError(f"Unknown fault_id: {fault_id}")
        if self.state not in {DUTState.NORMAL,DUTState.RECOVERED}: raise RuntimeError("DUT is not ready for fault injection")
        if self.scenario=="tool_error": raise RuntimeError("Simulated tool_error")
        if self.scenario=="timeout": raise TimeoutError("Simulated timeout")
        if self.scenario=="transient_tool_error" and not self.failures.get("transient_tool_error"):
            self.failures["transient_tool_error"]=1; raise RuntimeError("Simulated transient_tool_error")
        if self.scenario=="transient_timeout" and not self.failures.get("transient_timeout"):
            self.failures["transient_timeout"]=1; raise TimeoutError("Simulated transient_timeout")
        if self.scenario=="unknown_fault": raise ValueError(f"Unknown fault_id: {fault_id}")
        mode=self.cases[fault_id].failure_mode
        if mode in {"timeout","communication_error"}: raise RuntimeError(f"Simulated {mode}")
        if mode=="temporary_tool_failure" and not self.failures.get(fault_id): self.failures[fault_id]=1; raise RuntimeError("Simulated temporary_tool_failure")
        self.active=fault_id; self.state=DUTState.FAULT_INJECTED; self.version+=1
        return {"fault_id":fault_id,"state":self.state,"data_source":"synthetic_demo"}
    def read_dtc(self):
        if not self.active or self.state not in {DUTState.FAULT_INJECTED,DUTState.DTC_ACTIVE}: raise RuntimeError("No active synthetic fault")
        if self.state!=DUTState.DTC_ACTIVE:self.state=DUTState.DTC_ACTIVE;self.version+=1
        c=self.cases[self.active]
        dtc="SIM_DTC_999" if self.scenario=="dtc_mismatch" else c.expected_dtc
        return {"fault_id":self.active,"dtc":dtc,"status":"DETECTED","state":self.state,"data_source":"synthetic_demo"}
    def judge(self,fault_id,dtc):
        if fault_id not in self.cases: raise ValueError(f"Unknown fault_id: {fault_id}")
        expected=self.cases[fault_id].expected_dtc; passed=dtc==expected
        return {"fault_id":fault_id,"expected_dtc":expected,"actual_dtc":dtc,"result":"PASS" if passed else "FAIL","reason":"模拟 DTC 与预期一致" if passed else "模拟 DTC 不匹配","data_source":"synthetic_demo"}
    def recover_fault(self,fault_id):
        if self.active!=fault_id: raise RuntimeError(f"No active fault for {fault_id}")
        self.state=DUTState.RECOVERED; self.active=None; self.version+=1
        return {"fault_id":fault_id,"state":self.state,"recovered":True,"data_source":"synthetic_demo"}
    def snapshot(self):
        return {"state":self.state.value,"active":self.active,"failures":dict(self.failures),"scenario":self.scenario,"version":self.version}
    def restore(self,data):
        self.state=DUTState(data["state"]); self.active=data.get("active"); self.failures=dict(data.get("failures",{})); self.scenario=data.get("scenario","normal"); self.version=int(data.get("version",self.version))
