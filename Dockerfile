ARG PYTHON_BASE=python:3.11-slim
FROM ${PYTHON_BASE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AUTOFAULT_MODE=replay AUTOFAULT_LIVE_ENABLED=false
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY api ./api
COPY ui ./ui
RUN pip install --no-cache-dir .
EXPOSE 8000 8501
CMD ["uvicorn","api.main:app","--host","0.0.0.0","--port","8000"]
