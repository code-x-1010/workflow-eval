FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv pip install --system --no-cache fastapi uvicorn[standard] pydantic httpx pyyaml jinja2
COPY . .
ENV PYTHONPATH=/app/packages/wfeval-core/src:/app/packages/wfeval-adapters/src:/app
