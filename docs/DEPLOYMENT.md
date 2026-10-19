# Deployment

## CPU Replay

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
streamlit run ui/streamlit_app.py
```

Replay runs in-process and needs no API. Start FastAPI separately only for Live mode or API integration.

Or use `docker compose up --build`. The published container defaults to Replay and contains no model weights.

## GPU Live (private deployment only)

Install `requirements-live.txt`, expose exactly one GPU before Python starts, then configure:

```bash
export CUDA_VISIBLE_DEVICES=<physical-gpu-id>
export AUTOFAULT_LIVE_ENABLED=true
export AUTOFAULT_API_TOKEN='<long-random-secret>'
export AUTOFAULT_MODEL_PATH='/local/path/to/Qwen3-4B'
export AUTOFAULT_SFT_ADAPTER_PATH='/local/path/to/sft-b-checkpoint-90'
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Keep the API behind TLS and an authenticating reverse proxy. Do not mount host roots, Docker sockets or vehicle interfaces. Live mode is not suitable for an unauthenticated public deployment.
