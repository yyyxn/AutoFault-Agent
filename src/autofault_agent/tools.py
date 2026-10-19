from __future__ import annotations
import time,uuid
from typing import Any,Callable
from .environment import SimulatedDUT
from .models import Scenario

TOOL_SCHEMAS=[
 {"name":"search_fault_knowledge","description":"Search public synthetic fault knowledge","parameters":{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","minimum":1,"maximum":5}},"required":["query"]}},
 {"name":"get_test_case","description":"Get a public synthetic test case","parameters":{"type":"object","properties":{"fault_id":{"type":"string"}},"required":["fault_id"]}},
 {"name":"inject_fault","description":"Inject a fault into the in-memory synthetic DUT","parameters":{"type":"object","properties":{"fault_id":{"type":"string"}},"required":["fault_id"]}},
 {"name":"read_dtc","description":"Read DTC from the synthetic DUT","parameters":{"type":"object","properties":{}}},
 {"name":"judge_test_result","description":"Judge the synthetic test result","parameters":{"type":"object","properties":{"fault_id":{"type":"string"},"dtc":{"type":"string"}},"required":["fault_id","dtc"]}},
 {"name":"recover_fault","description":"Recover the in-memory synthetic DUT","parameters":{"type":"object","properties":{"fault_id":{"type":"string"}},"required":["fault_id"]}},
]

class ToolDispatcher:
    def __init__(self,case:Scenario):
        self.case=case;self.dut=SimulatedDUT(case)
        self.tools:dict[str,Callable[...,Any]]={"search_fault_knowledge":self.search,"get_test_case":self.get_case,"inject_fault":self.dut.inject_fault,"read_dtc":self.dut.read_dtc,"judge_test_result":self.dut.judge,"recover_fault":self.dut.recover_fault}
    def search(self,query:str,top_k:int=5):
        return {"documents":[{"title":self.case.title,"content":self.case.description,"fault_id":self.case.fault_id,"source":"public_synthetic_demo"}][:top_k],"query":query}
    def get_case(self,fault_id:str):
        if fault_id!=self.case.fault_id:raise ValueError("Unknown public fault_id")
        return {"test_case_id":self.case.id,"fault_id":fault_id,"title":self.case.title,"steps":self.case.test_case,"source":"public_synthetic_demo"}
    def dispatch(self,name:str,arguments:dict[str,Any]):
        started=time.perf_counter();call_id=f"call_{uuid.uuid4().hex[:10]}"
        try:
            if name not in self.tools:raise ValueError("Unknown tool")
            value=self.tools[name](**arguments)
            return {"tool_call_id":call_id,"tool_name":name,"success":True,"result":value,"latency_ms":round((time.perf_counter()-started)*1000,3)}
        except Exception as exc:
            return {"tool_call_id":call_id,"tool_name":name,"success":False,"error":{"type":type(exc).__name__,"message":str(exc)},"latency_ms":round((time.perf_counter()-started)*1000,3)}
