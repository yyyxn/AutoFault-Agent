# Dependency and model license audit

Checked for the release candidate on 2026-10-19.

- Project code and newly authored public synthetic examples: Apache-2.0.
- Qwen3-4B: the locally retained official model card declares `apache-2.0`, and the accompanying `LICENSE` is Apache License 2.0. No model or tokenizer file is redistributed here.
- FastAPI, Uvicorn, Streamlit, Pydantic and HTTPX are installed from their upstream Python packages rather than vendored. Release-environment metadata reported: FastAPI 0.141.1 MIT; Uvicorn 0.53.0 BSD-3-Clause; Streamlit 1.66.0 Apache-2.0; Pydantic 2.13.4 MIT; HTTPX 0.28.1 BSD-3-Clause. Downstream redistributors should repeat the check for their exact lock set.
- Optional Live dependencies—PyTorch, Transformers, PEFT and Accelerate—are not bundled. Users install them independently and remain responsible for their upstream terms.
- The repository contains no copied third-party documentation, dataset or model artifact.

The public `requirements*.txt` files intentionally specify compatible ranges rather than reproducing the private research environment. A production release should add a reviewed lockfile and software-bill-of-materials generated in its target container.

This is an engineering audit and not legal advice.
