# Final Publication Audit

Date: 2026-10-19
Status: **BLOCKED_CLEAN_INSTALL_VERIFICATION**

## Executive decision

The repository is technically substantive and its current public content is safe to review, but it should **not yet be made public**. The only release-blocking item is completion of a clean, network-independent installation/build followed by tests and Replay smoke. The Docker audit reached dependency download with a 94.72 KB context and no dependency conflict, but the host network sustained roughly 20 KB/s; the build was stopped while downloading Streamlit and therefore did not produce a finished image.

## PASS

1. **Real implementation, not UI-only.** `engine.py` contains an async model → tool → Observation → model loop. `live.py` lazily loads local Qwen Base/SFT-B, applies the chat template and parses model-generated tool calls. `tools.py` implements an exact six-name allowlist. `environment.py` implements an in-memory DUT. Replay is separate in `replay.py`.
2. **Honest capability boundary.** Live is real local inference code, Replay is pre-generated public synthetic trace playback, and historical Phase 5C metrics are static research results. The UI labels Replay explicitly. README now states that the public verifier is a reduced three-scenario full-workflow checker and that the repository does not ship a LangGraph runtime or MCP server.
3. **Original-project comparison.** The public tool names and DUT transitions preserve the private prototype's concepts. The private verifier is richer: task-type contracts, evidence-aware BLOCKED handling, overcontinue detection and evaluation-only semantic scoring are not public Demo capabilities. README/architecture now disclose this difference.
4. **Phase 5C accuracy.** Values match the frozen formal report: Base OFF 62/144 (43.1%), Old SFT OFF 44/144 (30.6%), SFT-A OFF 46/144 (31.9%), SFT-B OFF 124/144 (86.1%), Base ON 72/144 (50.0%), SFT-B ON 143/144 (99.3%). They are labeled independent sealed **synthetic** evaluation results over only eight fault groups, not real-vehicle performance.
5. **Licensing boundary.** Maintainer-authored code and newly authored public synthetic examples are declared Apache-2.0. The official local Qwen3-4B model card declares `apache-2.0` and ships an Apache-2.0 license; no Qwen file is included. Direct dependency metadata was audited and no dependency source is vendored. Authorship/legal authority remains a human attestation, not something static analysis can prove.
6. **Git and secret hygiene.** No remote is configured. Files are staged but not committed. `.venv`, outputs, caches, secrets, weights and checkpoint patterns are ignored. Static scans found no key marker, credential token, known server address, private absolute research path, sealed filename, tracked weight or tracked file over 5 MB.
7. **API safety.** Live defaults off; it requires a configured bearer token, exact single-GPU preflight, local model files and 18,000 MiB free CUDA memory. API adds per-IP rate limiting, one-request default concurrency and timeout. User input cannot select a filesystem path, shell command or arbitrary tool name; tool dispatch is a six-name mapping to an in-memory DUT.
8. **Runtime checks in the audited environment.** 25 tests pass. CPU Replay now loads public scenarios and traces locally and does not require FastAPI. With `AUTOFAULT_API_URL` deliberately pointed at an unused port, Streamlit still returned HTTP 200. The entrypoint also passed from outside the repository with `PYTHONPATH` removed, preventing cwd-dependent `ui` imports. The three-page navigation and all user-facing labels are Chinese, with an AppTest assertion covering the default page. FastAPI remains available for API integrations and is required by the UI only for Live mode.
9. **Docker/Compose/CI static checks.** Compose configuration parses. Docker copies only declared public source/API/UI files. `.dockerignore` reduced the build context from 71.44 MB to 94.72 KB. GitHub Actions installs from the repository and does not reference private services.

## BLOCKED

- **Clean installation/build completion:** the isolated Docker build did not finish because external downloads ran at about 20 KB/s. It successfully used a clean Python 3.12 image, parsed all declared dependencies and began downloading wheels, but was stopped at Streamlit. Publication requires one complete clean build, container Replay smoke and container test run. Do not interpret the existing linked local `.venv` as this proof.

## Optional improvements

- Add reviewed screenshots/GIFs to `docs/assets/`; the README currently provides only the intended location.
- Generate a pinned lockfile and SBOM in the target release environment.
- Add end-to-end Live testing on a private GPU host. Live code exists, but this audit did not load model weights.
- Add a full public task-type Completion Contract only if it can be released without Oracle leakage; do not imply the reduced verifier is identical to the private evaluator.
- Consider splitting API and UI dependency extras to make headless Replay installs smaller.

No commit, push, repository creation, remote configuration or public deployment was performed.
