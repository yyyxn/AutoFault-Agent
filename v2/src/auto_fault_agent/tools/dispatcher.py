import threading,time,uuid
from ..schemas import ToolResult
from ..data import tests
from ..rag import HybridRetriever
from ..environment import SimulatedDUT
class ToolDispatcher:
    def __init__(self,dut=None,retriever=None):
        self.dut=dut or SimulatedDUT(); self.retriever=retriever or HybridRetriever(); self.cases={x.fault_id:x for x in tests()}
        self._operation_results={}; self._operation_locks={}; self._operations_guard=threading.Lock()
        self.tools={"search_fault_knowledge":self.search,"get_test_case":self.get_case,"inject_fault":lambda fault_id:self.dut.inject_fault(fault_id),"read_dtc":lambda:self.dut.read_dtc(),"judge_test_result":lambda fault_id,dtc:self.dut.judge(fault_id,dtc),"recover_fault":lambda fault_id:self.dut.recover_fault(fault_id)}
    def search(self,query,top_k=5): return self.retriever.search(query,top_k)
    def get_case(self,fault_id):
        if fault_id not in self.cases: raise ValueError(f"Unknown fault_id: {fault_id}")
        return self.cases[fault_id].model_dump()
    def dispatch(self,name,arguments):
        started=time.perf_counter(); call_id=f"call_{uuid.uuid4().hex[:10]}"
        try:
            if name not in self.tools: raise ValueError(f"Unknown tool: {name}")
            value=self.tools[name](**arguments)
            return ToolResult(tool_call_id=call_id,tool_name=name,success=True,result=value,latency_ms=round((time.perf_counter()-started)*1000,3))
        except Exception as exc:
            return ToolResult(tool_call_id=call_id,tool_name=name,success=False,error={"type":type(exc).__name__,"message":str(exc)},latency_ms=round((time.perf_counter()-started)*1000,3))
    def dispatch_operation(self,name,arguments,operation_id,idempotency_key):
        with self._operations_guard:
            lock=self._operation_locks.setdefault(operation_id,threading.Lock())
        with lock:
            cached=self._operation_results.get(operation_id)
            if cached is not None:return cached
            result=self.dispatch(name,arguments)
            if result.success:self._operation_results[operation_id]=result
            return result
    def query_operation(self,operation_id):
        return self._operation_results.get(operation_id)
