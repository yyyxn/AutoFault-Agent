# MVP-2.1 Public Release Manifest

- Release scope: `v2/` only
- Runtime mode: deterministic MockPolicy over an in-memory synthetic DUT
- Public scenarios: F001 and F323
- Python verification: 127 passed
- Frontend verification: 3 passed; production build succeeded
- Integrity list: `SHA256SUMS.txt`

Excluded from this release: model weights, adapters, training data, training logs, historical sealed evaluation tasks, private credentials, absolute server paths, and private experiment outputs.

The Runtime demo is not a live-model benchmark and must not be described as a model capability improvement.
