from __future__ import annotations
import csv,json
from collections import Counter
from pathlib import Path
from ..data import faults
from .task_env import TaskSpec

PLANS={
 "fault_retrieval":["search_fault_knowledge","get_test_case"],
 "full_fault_test":["search_fault_knowledge","get_test_case","inject_fault","read_dtc","judge_test_result","recover_fault"],
 "dtc_reverse_diagnosis":["read_dtc","search_fault_knowledge","get_test_case"],
 "exception_recovery":["search_fault_knowledge","get_test_case","inject_fault","read_dtc","judge_test_result","recover_fault"],
 "multi_turn":["search_fault_knowledge","get_test_case","inject_fault","read_dtc","judge_test_result","recover_fault"],
}
def instruction(case,kind,difficulty):
    ref=case.fault_id if difficulty=="easy" else f"{case.component}出现{case.symptom}"
    if kind=="fault_retrieval": return f"请检索{ref}的故障信息，并找到对应测试用例。"
    if kind=="full_fault_test": return f"请对{ref}完成一次完整故障测试，判断结果并恢复系统。"
    if kind=="dtc_reverse_diagnosis": return f"当前系统已检测到一个模拟 DTC，请读取它并反向诊断{ref}对应的故障与测试用例。"
    if kind=="exception_recovery": return f"执行{ref}测试；如果工具出现异常，按规则重试，核对 DTC 后恢复系统。"
    return f"分多轮完成：先查询{ref}，再找测试用例、执行测试、读取 DTC、判断是否通过，最后恢复故障。"
def generate_tasks(count=100,seed=42):
    cases=faults(); kinds=list(PLANS); result=[]
    for i in range(count):
        case=cases[i%len(cases)]; difficulty="easy" if i<round(count*.2) else "medium" if i<round(count*.6) else "hard"; kind=kinds[i%5]
        scenario="normal"
        if kind=="exception_recovery": scenario=["transient_tool_error","transient_timeout","dtc_mismatch"][i%3]
        observed="SIM_DTC_999" if scenario=="dtc_mismatch" else case.expected_dtc
        gt={"fault_id":case.fault_id,"expected_dtc":case.expected_dtc,"observed_dtc":observed,"expected_judge":"FAIL" if scenario=="dtc_mismatch" else ("PASS" if "judge_test_result" in PLANS[kind] else None),"expected_outcome":"success"}
        result.append(TaskSpec(task_id=f"T{i+1:03}",task_type=kind,instruction=instruction(case,kind,difficulty),fault_id=case.fault_id,initial_state="DTC_ACTIVE" if kind=="dtc_reverse_diagnosis" else "NORMAL",scenario=scenario,expected_tools=PLANS[kind],ground_truth=gt,difficulty=difficulty,metadata={"data_source":"synthetic_demo","seed":seed,"expected_steps":len(PLANS[kind])}))
    return result
def write_tasks(tasks,output_dir):
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"tasks.jsonl").write_text("".join(x.model_dump_json()+"\n" for x in tasks),encoding="utf-8")
    fields=["task_id","task_type","difficulty","fault_id","scenario","expected_steps"]
    with (out/"tasks.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows([{**{k:getattr(x,k) for k in fields[:-1]},"expected_steps":len(x.expected_tools)} for x in tasks])
    summary={"total":len(tasks),"by_type":dict(Counter(x.task_type for x in tasks)),"by_difficulty":dict(Counter(x.difficulty for x in tasks)),"by_scenario":dict(Counter(x.scenario for x in tasks)),"data_source":"synthetic_demo"}
    (out/"tasks_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8"); return summary
