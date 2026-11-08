# AutoFault-Agent Runtime v2 / MVP-2.1

这是 AutoFault-Agent 的公开 Runtime 演示版本。它展示显式任务生命周期、Completion Contract、Action Ledger、超时结果核对、重复 Final 检测、上下文压缩，以及 SQLite 会话恢复。

> 本项目只操作内存中的公开合成 DUT，不连接真实车辆或物理测试设备。默认策略是确定性的 MockPolicy；它用于复现 Runtime 行为，不代表实时大模型推理或真实汽车诊断能力。

## 可复现 Demo

- `Normal`：完整六工具合成诊断链路。
- `Timeout`：副作用工具超时后进入 `OUTCOME_UNKNOWN`，再按 operation ID 核对；副作用仅发生一次。
- `Repeated Final`：Completion Contract 未满足时拒绝 Final，并由真实 Progress Guard 识别语义重复。
- `Long Context`：展示 Context Inspector 和 `EXACT` / `ESTIMATED` token 统计模式。
- 公开场景：`F001`、`F323`。二者均为随仓库发布的合成数据，不读取历史封存评测集。

## 本地启动

要求 Python 3.11+、Node.js 20+。

```bash
cd v2
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e '.[test]'
export MVP2_STATE_DIR=./runtime_state
uvicorn web.backend.app:app --host 127.0.0.1 --port 38081
```

另开终端：

```bash
cd v2/web/frontend
npm ci
VITE_API_URL=http://127.0.0.1:38081 npm run dev -- --host 127.0.0.1 --port 35174
```

访问 `http://127.0.0.1:35174`。后端 API 说明见 [web/API.md](web/API.md)。

也可仅启动后端：

```bash
docker compose up --build
```

## 测试

```bash
cd v2
pytest -q tests/mvp21 tests/context_v2 tests/api_v2 tests/runtime_v2
cd web/frontend && npm ci && npm test -- --run && npm run build
```

## 边界与许可

- 本目录不包含模型权重、Adapter、训练缓存、私有凭据、服务器配置或封存测试任务。
- token 精确计数是可选能力；配置本地 tokenizer 后显示 `EXACT`，否则显示 `ESTIMATED`。
- 根目录 Apache-2.0 许可证仅覆盖仓库中作者有权发布的代码；第三方依赖与模型遵循各自许可证。
- 历史研究指标与 MVP-2.1 Runtime Demo 是不同层次，不能把脚本化 Demo 结果描述为模型能力提升。
