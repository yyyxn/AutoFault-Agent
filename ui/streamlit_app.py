import sys
from pathlib import Path

# Streamlit may start from any working directory. Make the repository package
# importable without relying on PYTHONPATH or the caller's cwd.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st
from ui.common import api_run, list_public_scenarios, localize, show_trace

st.set_page_config(page_title="AutoFault-Agent", page_icon="🚗", layout="wide")


def playground():
    st.title("🚗 AutoFault-Agent")
    st.caption("合成汽车故障测试智能体 · 以回放模式为主的公开演示")
    st.info("本演示仅操作内存中的合成 DUT，不连接真实车辆，也不代表真实汽车诊断性能。")
    scenarios = list_public_scenarios()
    labels = {f'{item["title"]}（{item["id"]}）': item for item in scenarios}
    chosen = labels[st.selectbox("公开合成故障场景", labels)]
    goal = st.text_area("测试目标", f'验证“{chosen["title"]}”，判定测试结果，并恢复合成 DUT。')
    c1, c2, c3 = st.columns(3)
    mode = c1.radio("执行模式", ["replay", "live"], format_func=lambda value: "回放演示（CPU）" if value == "replay" else "实时 Qwen（GPU）")
    model = c2.selectbox("模型", ["base", "sft-b"], disabled=mode == "replay", help="模型选择仅对实时模式生效。")
    verifier = c3.toggle("完成验证器", value=False)
    if mode == "live":
        st.warning("实时模式会调用单独启动的 FastAPI 服务；回放模式在本地运行，无需该服务。")
        st.session_state.api_token = st.text_input("实时 API 令牌", type="password")
    if st.button("开始执行", type="primary"):
        try:
            result = api_run({"scenario_id": chosen["id"], "goal": goal, "mode": mode, "model": model, "verifier_enabled": verifier})
            st.session_state.last_result = result
        except Exception as exc:
            st.error(f"执行已安全终止：{exc}")
    if result := st.session_state.get("last_result"):
        st.warning(result["disclosure"])
        a, b, c = st.columns(3)
        a.metric("任务结果", "通过" if result["task_success"] else "失败")
        b.metric("耗时", f'{result["latency_ms"]:.1f} 毫秒')
        c.metric("完成验证器", "开启" if result["verifier_enabled"] else "关闭")
        st.subheader("执行轨迹")
        show_trace(result["trace"])
        st.subheader("智能体结论")
        st.write(result["final_answer"])
        st.subheader("合成 DUT 状态")
        st.json(localize(result["dut_state"]))


def trace_page():
    st.title("执行轨迹")
    st.caption("下方标签表示工具类型；实际调用顺序与重复次数始终来自保存的真实轨迹。")
    if result := st.session_state.get("last_result"):
        st.write({"运行 ID": result["run_id"], "执行模式": "回放" if result["mode"] == "replay" else "实时", "模型": result["model"], "完成验证器": "开启" if result["verifier_enabled"] else "关闭"})
        show_trace(result["trace"])
    else:
        st.info("请先在“智能体演示”页面运行一个场景。")


def benchmark_page():
    st.title("基准评测")
    st.caption("第五阶段 C：合成环境预注册独立评测，每组 144 个任务，共 8 个故障组。")
    data = {"Base（关闭）": 43.1, "旧 SFT（关闭）": 30.6, "SFT-A（关闭）": 31.9, "SFT-B（关闭）": 86.1, "Base（开启）": 50.0, "SFT-B（开启）": 99.3}
    st.bar_chart(data, x_label="实验条件", y_label="严格任务成功率（%）", horizontal=True)
    cols = st.columns(3)
    for index, (name, value) in enumerate(data.items()):
        cols[index % 3].metric(name, f"{value:.1f}%")
    st.warning("这些结果仅衡量同一合成领域和工具体系内的泛化能力。144 个任务仅对应 8 个独立故障组，不能代表真实车辆测试效果。")
    st.markdown("**主要比较：** SFT-B 关闭验证器 − SFT-A 关闭验证器 = +54.2 个百分点；任务级配对 Bootstrap 95% 置信区间为 [45.8, 62.5]。")


navigation = st.navigation([
    st.Page(playground, title="智能体演示", icon="🚗", default=True),
    st.Page(trace_page, title="执行轨迹", icon="🧭"),
    st.Page(benchmark_page, title="基准评测", icon="📊"),
])
navigation.run()
