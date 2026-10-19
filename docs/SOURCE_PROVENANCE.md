# Source provenance

This public package is a deployment-oriented refactor of a private research prototype completed through Phase 5C. The extraction intentionally preserves concepts—not private experimental data:

- `environment.py`: in-memory DUT state transitions;
- `tools.py`: six-name allowlisted dispatcher and observation envelope;
- `verifier.py`: bounded, non-answer completion feedback;
- `engine.py`: model → tool → observation → model loop;
- `models.py`: public trace and API contracts.

The release audit compares these behaviors through regression fixtures rather than shipping private TaskSpecs or evaluation Oracle data. Public demo scenarios and replay traces were authored specifically for this repository and do not originate from the sealed evaluation set.

Private source hashes and the release extraction log are retained by the maintainer outside the distributable repository. This avoids publishing host paths or sensitive experiment inventory while preserving internal traceability.

Pre-extraction source hashes (repository-relative names only):

- `tools/dispatcher.py`: `5db464a0c3cf20304da0d464f4d1ee7628bdc76f418ac9b1ffb8d59b072dc7e9`
- `environment/simulated_dut.py`: `ae2b901636acf9ac5066e5ed0a5abd8e38e806b71bc970bd7e507411e52ac12d`
- `harness/completion_verifier.py`: `49c367888fde7c4d641d4ccc384505ed413f75cf72e13b62c494241bd8457ec6`
- `harness/context.py`: `4223ae09d64d5f58fb55458526e1fe2615ddb462c8aa4acbee7fb3c9481dbad3`
- `phase5_evaluation.py`: `e039318756d7e3cb6f2980052100296a97066ffaf8024c2564e1761d1feb2a1c`
- `schemas/models.py`: `0b0ae4fa657a9f01837f8878bd8a06e1c35d679b48ad497610200dd24fa71ca3`
