.PHONY: install test api ui
install:
	python -m pip install -e ".[test]"
test:
	python -m pytest -q
api:
	AUTOFAULT_LIVE_ENABLED=false uvicorn api.main:app --host 127.0.0.1 --port 8000
ui:
	AUTOFAULT_API_URL=http://127.0.0.1:8000 streamlit run ui/streamlit_app.py
