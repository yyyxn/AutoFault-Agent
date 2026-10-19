from enum import Enum
from .models import Scenario

class DUTState(str,Enum):
    NORMAL="NORMAL"; FAULT_INJECTED="FAULT_INJECTED"; DTC_ACTIVE="DTC_ACTIVE"; RECOVERED="RECOVERED"

class SimulatedDUT:
    """In-memory synthetic DUT; never connects to vehicles or host devices."""
    def __init__(self, scenario: Scenario):
        self.case=scenario;self.state=DUTState.NORMAL;self.active=None;self.failures={}
    def inject_fault(self,fault_id:str):
        if fault_id!=self.case.fault_id:raise ValueError("Unknown public fault_id")
        if self.case.scenario=="transient_tool_error" and not self.failures.get("inject"):
            self.failures["inject"]=1;raise RuntimeError("Simulated transient tool error")
        if self.state not in {DUTState.NORMAL,DUTState.RECOVERED}:raise RuntimeError("DUT is not ready")
        self.active=fault_id;self.state=DUTState.FAULT_INJECTED
        return {"fault_id":fault_id,"state":self.state.value,"data_source":"public_synthetic_demo"}
    def read_dtc(self):
        if not self.active:raise RuntimeError("No active synthetic fault")
        self.state=DUTState.DTC_ACTIVE
        dtc="DEMO_DTC_MISMATCH" if self.case.scenario=="dtc_mismatch" else self.case.expected_dtc
        return {"fault_id":self.active,"dtc":dtc,"status":"DETECTED","state":self.state.value,"data_source":"public_synthetic_demo"}
    def judge(self,fault_id:str,dtc:str):
        if fault_id!=self.case.fault_id:raise ValueError("Unknown public fault_id")
        passed=dtc==self.case.expected_dtc
        return {"fault_id":fault_id,"actual_dtc":dtc,"result":"PASS" if passed else "FAIL","reason":"DTC matched" if passed else "DTC mismatch","data_source":"public_synthetic_demo"}
    def recover_fault(self,fault_id:str):
        if self.active!=fault_id:raise RuntimeError("No matching active fault")
        self.state=DUTState.RECOVERED;self.active=None
        return {"fault_id":fault_id,"state":self.state.value,"recovered":True,"data_source":"public_synthetic_demo"}
    def snapshot(self):return {"state":self.state.value,"active":self.active,"failures":dict(self.failures),"scenario":self.case.scenario}
