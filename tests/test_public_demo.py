import json,os,subprocess,sys
from pathlib import Path
from streamlit.testing.v1 import AppTest
from fastapi.testclient import TestClient
from api.main import app
from autofault_agent.data import get_scenario,scenarios
from autofault_agent.environment import SimulatedDUT,DUTState
from autofault_agent.live import LiveUnavailable,parse_action
from autofault_agent.models import RunRequest
from autofault_agent.replay import run_replay
from autofault_agent.tools import TOOL_SCHEMAS,ToolDispatcher
from autofault_agent.verifier import CompletionVerifier,audit_feedback
from ui.common import api_run,list_public_scenarios

def test_public_scenarios_have_no_oracle_fields():
    raw=json.dumps([x.model_dump() for x in scenarios()]).lower()
    assert all(x not in raw for x in ["ground_truth","oracle","expected_tools","reward"])
def test_six_tools_only():assert [x["name"] for x in TOOL_SCHEMAS]==["search_fault_knowledge","get_test_case","inject_fault","read_dtc","judge_test_result","recover_fault"]
def test_dut_happy_path():
    c=get_scenario("DEMO-001");d=SimulatedDUT(c);d.inject_fault(c.fault_id);assert d.read_dtc()["dtc"]==c.expected_dtc;assert d.judge(c.fault_id,c.expected_dtc)["result"]=="PASS";d.recover_fault(c.fault_id);assert d.state==DUTState.RECOVERED
def test_transient_error_is_real_observation():
    c=get_scenario("DEMO-003");d=ToolDispatcher(c);a=d.dispatch("inject_fault",{"fault_id":c.fault_id});b=d.dispatch("inject_fault",{"fault_id":c.fault_id});assert not a["success"] and b["success"]
def test_dispatcher_rejects_unknown_tool():assert not ToolDispatcher(get_scenario("DEMO-001")).dispatch("shell",{})["success"]
def test_replay_without_model(monkeypatch):
    monkeypatch.delenv("AUTOFAULT_MODEL_PATH",raising=False);r=run_replay(RunRequest(scenario_id="DEMO-001",goal="test",mode="replay"));assert r.task_success and r.mode=="replay" and len(r.trace)==6
def test_replay_trace_order_is_data_driven():assert len(run_replay(RunRequest(scenario_id="DEMO-003",goal="test")).trace)==7
def test_replay_disclosure():assert "没有执行模型推理" in run_replay(RunRequest(scenario_id="DEMO-001",goal="test")).disclosure
def test_verifier_feedback_has_no_hidden_keys():
    v=CompletionVerifier(True);fb=v.feedback({"status":"incomplete","missing":["recover_fault"]});assert audit_feedback(fb)==[]
def test_verifier_off_returns_no_feedback():assert CompletionVerifier(False).feedback({"status":"incomplete","missing":[]}) is None
def test_parse_tool_call():assert parse_action('<tool_call>{"name":"read_dtc","arguments":{}}</tool_call>').name=="read_dtc"
def test_live_disabled(monkeypatch):
    monkeypatch.setenv("AUTOFAULT_LIVE_ENABLED","false")
    from autofault_agent.live import live_preflight
    try:live_preflight("base");assert False
    except LiveUnavailable:pass
def test_api_health_and_scenarios():
    c=TestClient(app);assert c.get("/health").status_code==200;assert len(c.get("/api/v1/scenarios").json())==3
def test_api_replay():
    c=TestClient(app);r=c.post("/api/v1/run",json={"scenario_id":"DEMO-002","goal":"test mismatch","mode":"replay","model":"base","verifier_enabled":False});assert r.status_code==200 and r.json()["mode"]=="replay"
def test_streamlit_replay_needs_no_api(monkeypatch):
    monkeypatch.setenv("AUTOFAULT_API_URL","http://127.0.0.1:1")
    assert len(list_public_scenarios())==3
    result=api_run({"scenario_id":"DEMO-001","goal":"offline replay","mode":"replay","model":"base","verifier_enabled":False})
    assert result["task_success"] and result["mode"]=="replay"
def test_streamlit_entrypoint_resolves_ui_outside_repo(tmp_path):
    entrypoint=Path(__file__).resolve().parents[1]/"ui"/"streamlit_app.py"
    env=os.environ.copy();env.pop("PYTHONPATH",None);env["AUTOFAULT_API_URL"]="http://127.0.0.1:1"
    code=("from streamlit.testing.v1 import AppTest;"
          f"a=AppTest.from_file({str(entrypoint)!r});"
          "a.run(timeout=20);"
          "assert not a.exception, a.exception")
    completed=subprocess.run([sys.executable,"-c",code],cwd=tmp_path,env=env,capture_output=True,text=True,timeout=30)
    assert completed.returncode==0,completed.stdout+completed.stderr
def test_streamlit_default_page_is_chinese():
    entrypoint=Path(__file__).resolve().parents[1]/"ui"/"streamlit_app.py"
    app=AppTest.from_file(str(entrypoint)).run(timeout=20)
    assert not app.exception
    assert app.title[0].value=="🚗 AutoFault-Agent"
    assert app.selectbox[0].label=="公开合成故障场景"
    assert app.text_area[0].label=="测试目标"
    assert app.button[0].label=="开始执行"
def test_live_requires_token(monkeypatch):
    monkeypatch.setenv("AUTOFAULT_API_TOKEN","secret");c=TestClient(app);r=c.post("/api/v1/run",json={"scenario_id":"DEMO-001","goal":"test","mode":"live","model":"base","verifier_enabled":False});assert r.status_code==401
def test_live_requires_auth_configuration(monkeypatch):
    monkeypatch.delenv("AUTOFAULT_API_TOKEN",raising=False);c=TestClient(app);r=c.post("/api/v1/run",json={"scenario_id":"DEMO-001","goal":"test","mode":"live","model":"base","verifier_enabled":False});assert r.status_code==503
def test_no_path_parameters_in_api():assert all("{" not in r.path for r in app.routes)
def test_schema_rejects_path_like_scenario():
    c=TestClient(app);assert c.post("/api/v1/run",json={"scenario_id":"../../etc/passwd","goal":"test","mode":"replay","model":"base","verifier_enabled":False}).status_code in {404,500}
