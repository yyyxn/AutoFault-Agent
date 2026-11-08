"""MCP 1.2 server exposing six synthetic automotive diagnostic tools."""
from mcp.server.fastmcp import FastMCP
from ..tools import ToolDispatcher
dispatcher=ToolDispatcher(); mcp=FastMCP("auto-fault-diagnosis")
def out(name,args): return dispatcher.dispatch(name,args).model_dump(mode="json")
@mcp.tool()
def search_fault_knowledge(query:str,top_k:int=5)->dict:
    """Search synthetic fault knowledge and return ranked evidence."""
    return out("search_fault_knowledge",{"query":query,"top_k":top_k})
@mcp.tool()
def get_test_case(fault_id:str)->dict:
    """Get one synthetic test case by fault ID."""
    return out("get_test_case",{"fault_id":fault_id})
@mcp.tool()
def inject_fault(fault_id:str)->dict:
    """Inject one fault into the simulated DUT only."""
    return out("inject_fault",{"fault_id":fault_id})
@mcp.tool()
def read_dtc()->dict:
    """Read the currently active synthetic DTC from simulated DUT."""
    return out("read_dtc",{})
@mcp.tool()
def judge_test_result(fault_id:str,dtc:str)->dict:
    """Compare synthetic expected and actual DTC values."""
    return out("judge_test_result",{"fault_id":fault_id,"dtc":dtc})
@mcp.tool()
def recover_fault(fault_id:str)->dict:
    """Recover the active synthetic fault in simulated DUT."""
    return out("recover_fault",{"fault_id":fault_id})
if __name__=="__main__": mcp.run()
