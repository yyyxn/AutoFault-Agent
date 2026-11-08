# MVP-2.1 Public Release Manifest

- Release scope: `v2/` only
- Runtime mode: deterministic scripted runtime over an in-memory synthetic DUT
- Public scenarios: F001 and F323
- Python verification: 153 passed / 0 failed across three non-overlapping partitions (Runtime 93, MVP-2.1 24, API + Context 36)
- Frontend verification: 9 passed
- Vue/TypeScript production build: succeeded
- Integrity list: `SHA256SUMS.txt`

Excluded from this release: model weights, adapters, training data, training logs, historical sealed evaluation tasks, private credentials, absolute server paths, and private experiment outputs.

MVP-2.1 uses deterministic scripted synthetic diagnostic scenarios to exercise real Runtime/Harness components: Completion Verifier, Action Ledger, outcome reconciliation, session persistence, and restart recovery. It does not perform live-model inference, connect to a real ECU, or demonstrate a model capability improvement.
