# Local release readiness report

Date: 2026-10-19

Status: **BLOCKED_CLEAN_INSTALL_VERIFICATION**

## Verification

- 25 automated tests passed.
- FastAPI process smoke: `/health` returned 200.
- CPU Replay smoke: DEMO-003 returned seven trace steps, `task_success=true`, Verifier state matched the request, and final DUT state was `RECOVERED`.
- Standalone Streamlit Replay smoke with an unreachable API URL: HTTP 200.
- Streamlit launched from outside the repository with no `PYTHONPATH`: HTTP 200 and no import exception.
- Three-page Streamlit navigation and user-facing labels were localized to Chinese; the default page has automated UI assertions.
- Streamlit AppTest: Agent Playground, Execution Trace and Benchmark Dashboard rendered with zero exceptions.
- Live without server-side authentication configuration: blocked.
- Live without explicit enablement/model/GPU preflight: blocked.
- Tracked repository payload: under 100 KB at audit time; no tracked file exceeded 5 MB.
- No weight, Adapter, optimizer, checkpoint or training-cache extension was tracked.
- No private-key marker, known server address or private absolute research path was found in distributable content.

## Start commands

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

For CPU Replay, the API process above is optional. Start the UI directly:

```bash
source .venv/bin/activate
streamlit run ui/streamlit_app.py
```

Live mode still requires the API process, authentication, explicit Live enablement,
local model weights and a passing GPU preflight.

## Publication gate

The repository is initialized locally on branch `main` with no remote. It has not been pushed and has not been made public. An isolated Docker build parsed the declared dependencies but could not finish downloading them because the host network sustained roughly 20 KB/s. Publication remains blocked until a complete clean build, clean test run and container Replay smoke pass. See `FINAL_PUBLICATION_AUDIT.md`.
