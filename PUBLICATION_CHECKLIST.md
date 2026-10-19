# Publication Checklist

## Required before publication

- [x] Real Live Agent loop is present.
- [x] Six tools use a strict allowlist and an in-memory synthetic DUT.
- [x] Replay and Live are visibly distinguished.
- [x] Historical Phase 5C results match the frozen report and are labeled synthetic.
- [x] Public/private verifier capability difference is disclosed.
- [x] No model weights, adapters, optimizer state, sealed tasks or Oracle records are tracked.
- [x] No known credential, server address or private absolute path is tracked.
- [x] Live defaults off and requires server-side authentication configuration.
- [x] Rate limit, timeout and concurrency bound exist.
- [x] Docker build context excludes local environments, outputs and secrets.
- [x] Compose configuration parses without a private service.
- [x] Local automated suite passes: 22 tests.
- [x] Local API, Replay and three Streamlit pages pass smoke tests.
- [ ] **Complete a clean Docker build with normal network access.**
- [ ] **Run tests inside the clean image or a fresh isolated venv.**
- [ ] **Run API/Replay smoke from the clean image.**

## Human/legal review

- [ ] Confirm the maintainer owns or may license every authored source file as Apache-2.0.
- [ ] Review exact dependency lock and notices for the release tag.
- [ ] Review all public synthetic text for trademark/company-policy concerns.
- [ ] Confirm no screenshot contains hostnames, filesystem paths, tokens or private traces.

## Optional polish

- [ ] Add screenshots/GIFs to `docs/assets/`.
- [ ] Add repository topics, description and social preview.
- [ ] Add `CITATION.cff`, changelog and SBOM.
- [ ] Create an issue template explaining synthetic-only scope.

Release only after all three clean-environment items and applicable human/legal items are checked.
