# GitHub Release Guide

This guide is intentionally manual. Do not publish until `FINAL_PUBLICATION_AUDIT.md` is no longer blocked.

## 1. Clean verification

```bash
docker build -t autofault-agent:local .
docker run --rm -d --name autofault-api -p 8000:8000 autofault-agent:local
curl --fail http://127.0.0.1:8000/health
curl --fail -H 'Content-Type: application/json' \
  -d '{"scenario_id":"DEMO-003","goal":"Demonstrate safe recovery","mode":"replay","model":"base","verifier_enabled":true}' \
  http://127.0.0.1:8000/api/v1/run
docker stop autofault-api
```

For tests in a fresh environment:

```bash
python -m venv /tmp/autofault-release-venv
source /tmp/autofault-release-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
pytest -q
```

Standalone CPU Replay does not require FastAPI:

```bash
AUTOFAULT_API_URL=http://127.0.0.1:1 streamlit run ui/streamlit_app.py
```

Open the displayed Streamlit URL and verify the three public scenarios load without
an API warning. The intentionally unreachable URL proves Replay is local; Live mode
continues to require the authenticated API.

## 2. Review the exact Git payload

```bash
git status --short --ignored
git diff --cached --stat
git diff --cached
sha256sum -c RELEASE_SHA256SUMS.txt
git remote -v
```

Regenerate `RELEASE_SHA256SUMS.txt` after every change and rerun tests. Confirm `.venv`, `outputs`, models and secrets remain ignored.

## 3. Add media safely

Place manually reviewed screenshots/GIFs in `docs/assets/`. Use only public Replay scenarios. Crop terminals, hostnames, browser tokens and filesystem paths. Update README links, regenerate hashes and rerun the security scan.

## 4. Human-controlled GitHub publication

After the blocker is cleared, the maintainer may manually:

1. review authorship and license authority;
2. create a local commit;
3. create a private GitHub repository first;
4. configure the remote explicitly;
5. push and confirm Actions passes;
6. inspect the GitHub file browser for ignored-file mistakes;
7. only then change repository visibility to Public.

These operations are deliberately not automated by this project audit.

## 5. Release notes

State clearly that:

- Replay uses newly authored public synthetic traces and no inference;
- Live requires separately obtained local Qwen weights and is disabled by default;
- Phase 5C numbers are sealed synthetic evaluation results over eight fault groups;
- the project does not connect to or validate behavior on real vehicles;
- the public verifier is reduced relative to the private evaluation contracts.
