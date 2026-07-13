# learn-mcp server for Cloud Run (Streamable HTTP transport).
FROM python:3.12-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml ./
COPY learn_mcp_server.py ./

# Install deps into the system env (no venv needed in a container)
RUN uv pip install --system "mcp[cli]>=1.2.0" "google-genai>=0.3.0" "pydantic>=2.0"

# Cloud Run sets $PORT (default 8080). The server reads it and binds 0.0.0.0.
ENV PORT=8080
EXPOSE 8080

# No key file baked in — the container authenticates to Vertex via the Cloud Run
# service account (Workload Identity / ADC from the metadata server).
CMD ["python", "learn_mcp_server.py"]
