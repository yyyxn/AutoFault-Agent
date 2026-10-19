import os,httpx,streamlit as st
from autofault_agent.data import scenarios
from autofault_agent.models import RunRequest
from autofault_agent.replay import run_replay
API=os.getenv("AUTOFAULT_API_URL","http://127.0.0.1:8000")
TOOL_NAMES={"search_fault_knowledge":"检索故障知识","get_test_case":"获取测试用例","inject_fault":"注入故障","read_dtc":"读取 DTC","judge_test_result":"判定测试结果","recover_fault":"恢复故障"}
DISPLAY_KEYS={"tool":"工具","arguments":"参数","observation":"工具返回","verifier_feedback":"完成验证器反馈","success":"成功","result":"结果","error":"错误","type":"类型","message":"消息","state":"状态","documents":"文档","title":"标题","source":"来源","reason":"原因","recovered":"已恢复","data_source":"数据来源","test_case_id":"测试用例 ID","dtc":"DTC","fault_id":"故障 ID","query":"查询","top_k":"返回数量"}
DISPLAY_VALUES={"success":"成功","error":"错误","incomplete":"未完成","complete":"已完成","FAULT_INJECTED":"故障已注入","DTC_ACTIVE":"DTC 已激活","RECOVERED":"已恢复","DTC mismatch":"DTC 不匹配","Simulated transient tool error":"模拟瞬态工具错误","public_synthetic_demo":"公开合成演示"}
def localize(value):
    if isinstance(value,dict):return {DISPLAY_KEYS.get(k,k):localize(v) for k,v in value.items()}
    if isinstance(value,list):return [localize(v) for v in value]
    return DISPLAY_VALUES.get(value,value)
def list_public_scenarios():
    """Replay is deliberately self-contained and does not require FastAPI."""
    return [{"id":x.id,"title":x.title,"description":x.description,"component":x.component,"scenario":x.scenario} for x in scenarios()]
def api_run(payload):
    if payload.get("mode")=="replay":
        return run_replay(RunRequest.model_validate(payload)).model_dump(mode="json")
    token=st.session_state.get("api_token","");headers={"Authorization":f"Bearer {token}"} if token else {}
    with httpx.Client(timeout=150) as c:return c.post(API+"/api/v1/run",json=payload,headers=headers).raise_for_status().json()
def show_trace(trace):
    for step in trace:
        icon={"success":"✅","error":"❌","incomplete":"⚠️","complete":"✅"}.get(step["status"],"•")
        with st.expander(f'{icon} 第 {step["index"]} 步：{step["label"]}',expanded=True):
            if step.get("tool_call"):st.json({"工具":TOOL_NAMES.get(step["tool_call"]["name"],step["tool_call"]["name"]),"参数":localize(step["tool_call"]["arguments"])})
            if step.get("observation"):st.json({"工具返回":localize(step["observation"])})
            if step.get("model_output"):st.code(step["model_output"])
            if step.get("verifier_feedback"):st.json({"完成验证器反馈":localize(step["verifier_feedback"])})
            st.caption(f'{step.get("latency_ms",0):.1f} 毫秒 · {DISPLAY_VALUES.get(step["status"],step["status"])}')
