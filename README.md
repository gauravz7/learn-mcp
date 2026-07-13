# learn-mcp — an end-to-end MCP tutorial project

A hands-on Model Context Protocol project: an MCP server wrapping Google's **nano-banana**
image model (`gemini-3.1-flash-image`), proven on the raw wire protocol, driven by a **Gemini
ADK agent**, and composed with **Agent Skills**. See `THEORY.md` for the full explanation and
`blog/` for the write-ups.

## Layout
```
server/            FastMCP server (nano-banana tools + every MCP primitive)
client/            raw_client.py (stdio, proves the protocol) · remote_client.py (hosted, HTTP)
adk_agent/         Gemini ADK agent over MCP; skills/ used by the demos
creative_studio/   ADK agent = 4 Skills (know-how) + MCP tools (capability)
blog/              mcp-deep-dive.md, mcp-for-execs.md (+ .html renders, images/)
THEORY.md          complete MCP reference
transcripts/       captured runs
```

## Prerequisites
- **[uv](https://docs.astral.sh/uv/)** (Python package manager) and Python 3.11+
- **Google Cloud auth for Vertex** (nano-banana): `gcloud auth application-default login`, and a
  project with Vertex AI enabled. Configure via env vars — set your own values:
  `GOOGLE_CLOUD_PROJECT=<your-project>`, `GOOGLE_CLOUD_LOCATION=global` (default),
  `NANO_BANANA_MODEL=gemini-3.1-flash-image` (default).
- (Each subproject has its own `pyproject.toml`; `uv` creates the venv automatically on first run.)

## Run it

**1. The server (stdio) + raw protocol client**
```bash
cd client && uv run --project ../server python raw_client.py
```
Launches the server as a subprocess and exercises every feature (tools, resources, prompts,
elicitation, sampling). Output also saved to `transcripts/`.

**2. The server over HTTP (Streamable HTTP)**
```bash
cd server && uv run python learn_mcp_server.py --http --port 9000
# then, in another shell, hit it with the hosted client:
cd client && uv run --project ../server python remote_client.py   # set MCP_URL for a remote server
```

**3. Gemini ADK agent → MCP (scripted)**
```bash
# start the HTTP server on :9000 first (step 2), then:
cd adk_agent && uv run python run_test.py
```

**4. Skills + MCP composed (scripted)**
```bash
# HTTP server on :9000 running, then:
cd adk_agent && uv run python skill_mcp_demo.py
```

**5. Chat UI (adk web) with both agents**
```bash
# HTTP server on :9000 running, then from the project root:
uv run --project adk_agent adk web --host 0.0.0.0 --port 8080 --allow_origins="*" .
# open http://localhost:8080  → pick `adk_agent` or `creative_studio`
```

## Notes
- Image generation takes ~12s; MCP clients must allow enough timeout (ADK's default is 5s — the
  code sets `timeout=120`).
- Generated images land in `server/generated/`.
- Tools return a `resource_uri` (a link), not inline image bytes, to keep model context small.
