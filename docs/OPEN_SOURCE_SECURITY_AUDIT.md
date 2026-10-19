# Open-source Security Audit

## Decision

Only the independently implemented execution concepts and newly authored public synthetic examples are included. The source research directory remains unchanged.

Excluded:

- all model weights, LoRA adapters, optimizer states, caches and checkpoints;
- all Phase 5A sealed tasks, TaskSpecs, Oracle fields, ground truth and full evaluation traces;
- internal absolute paths, server IP/ports, service configuration and historical `.env.example`;
- generated training data and unpublished experiment outputs;
- third-party model/tokenizer files and any material without redistribution permission.

The source tree contained multiple 66 MB adapter files and 132 MB optimizer files. None are present here. Static tests reject weight extensions, files larger than 5 MB, private-key headers and the known server address.

## API threat review

- No endpoint accepts filesystem paths or shell commands.
- Scenario IDs map only to an in-package allowlist.
- Replay performs no model import or host access.
- Live requires explicit enablement, local model preflight, bearer authentication, rate limiting, timeout and a concurrency semaphore.
- CORS is restricted to local Streamlit origins.
- Tool dispatch is an exact six-name allowlist and targets only an in-memory DUT.
- UI and API responses omit Oracle, expected tool sequence, expected DTC and reward metadata.

## Provenance

Core concepts were extracted from the private research tree after Phase 5C. The public implementation is a clean deployment-oriented refactor. Semantics for the six tools, transient failure, DUT recovery, completion feedback and verifier disablement are covered by regression tests. No original history or experimental artifact was modified. A private provenance manifest, kept outside the public repository, records source hashes.

## License review

Project code and newly authored public synthetic data are offered under Apache-2.0. Qwen weights are not redistributed. Users must separately obtain the model and comply with its upstream model card and license. Python dependencies remain under their respective upstream licenses; no dependency source is vendored.

This audit is a technical release review, not legal advice. Confirm authorship and organizational policy before publication.
