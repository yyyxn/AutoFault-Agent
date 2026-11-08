FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY src ./src
COPY data ./data
COPY web ./web
RUN pip install --no-cache-dir -r requirements.txt
ENV PYTHONPATH=/app/src:/app MVP2_STATE_DIR=/app/runtime_state
EXPOSE 38081
CMD ["uvicorn", "web.backend.app:app", "--host", "0.0.0.0", "--port", "38081"]
