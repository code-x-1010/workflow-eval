FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
# Base deps + every service's optional extras. This list must be kept in
# sync with pyproject.toml by hand -- there's no [build-system] section, so
# `uv pip install .`/`uv sync` (which CI uses instead, see ci.yml) can't
# install this project as a package. Found out of sync (missing lxml,
# xmlschema, networkx, arq, sqlalchemy from base, and every extra) while
# wiring L4 soundness in: services/validation/src/main.py now imports
# l4_soundness.py unconditionally, which needs pm4py -- previously nothing
# in main.py's import chain needed anything outside the old hardcoded list,
# so this had never actually been exercised. See docs/decisions/0015.
RUN uv pip install --system --no-cache \
    fastapi "uvicorn[standard]" pydantic httpx lxml xmlschema networkx pyyaml jinja2 arq sqlalchemy \
    pm4py SpiffWorkflow lark hypothesis tiktoken
COPY . .
ENV PYTHONPATH=/app/packages/wfeval-core/src:/app/packages/wfeval-adapters/src:/app
