from dataclasses import dataclass,field
from typing import Any

REQUIRED=("search_fault_knowledge","get_test_case","inject_fault","read_dtc","judge_test_result","recover_fault")
FORBIDDEN={"ground_truth","expected_tools","expected_dtc","oracle","reward","next_tool"}

@dataclass
class CompletionVerifier:
    enabled:bool=False;max_corrections:int=2;corrections:int=0;events:list[dict[str,Any]]=field(default_factory=list)
    def assess(self,trace,dut_state):
        completed={s.tool_call.name for s in trace if s.kind=="tool" and s.observation and s.observation.get("success")}
        missing=[x for x in REQUIRED if x not in completed]
        if dut_state.get("state")=="RECOVERED" and not dut_state.get("active") and not missing:return {"status":"complete","missing":[]}
        return {"status":"incomplete","missing":missing}
    def feedback(self,assessment):
        if not self.enabled or assessment["status"]=="complete":return None
        if self.corrections>=self.max_corrections:return {"type":"completion_feedback","status":"blocked","reason":"Correction limit reached","remaining_attempts":0}
        self.corrections+=1
        value={"type":"completion_feedback","status":"incomplete","reason":"Required execution postconditions are not yet satisfied","remaining_attempts":self.max_corrections-self.corrections}
        self.events.append(value);return value

def audit_feedback(value):
    keys=set()
    def walk(x):
        if isinstance(x,dict):
            for k,v in x.items():keys.add(str(k).lower());walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(value);return sorted(keys & FORBIDDEN)
