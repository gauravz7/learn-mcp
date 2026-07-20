# Movie Studio — Code Walkthrough

Purpose-first documentation of the **movie-studio agent**: the two Python files that turn the
`movie-mcp` pipeline into a multi-user chat product. Each function is documented with *what it's for*
**and** *where it sits in the request flow*.

- **`movie_agent/agent.py`** — the **brain**. Defines `root_agent` (`movie_director`): a Gemini ADK
  agent that loads three Skills (know-how) and connects to the `movie-mcp` server (capability). It
  decides *what* to do; it does not serve HTTP.
- **`movie_studio/app.py`** — the **host**. A FastAPI web app that runs that same agent, streams a
  turn to the browser over SSE, persists sessions per user, and proxies generated media bytes. It
  turns the brain into a website.

```
Browser (SPA)                movie_studio/app.py                 movie_agent/agent.py        movie-mcp (:9100)
    │  GET /chat/stream ─────────► chat_stream ─► _run_turn ─────► runner.run_async(root_agent) ─► tools/call
    │  ◄──── SSE: tool/media/text ──────────────┘   (streams events, resolves movie:// → /asset URLs)
    │  <img src=/asset/..> ─────► get_asset ─────────────────────────────────────────► reads bytes off disk
    │  POST /upload ────────────► upload ─► _mcp_call ───────────────────────────────► import_character/prop
```

---

## Part A — The brain: `movie_agent/agent.py`

**File purpose.** Assemble the director agent once, so both the CLI (`run.py`), `adk web`, and the
Studio (`app.py`) import the *same* `root_agent`. This is "the missing piece" — an agent that drives
the pipeline instead of hand-written scripts.

### Startup wiring (module level) — *fits: run once at import*
- **`skills = [load_skill_from_dir(...) x3]`** — loads the `script-developer`, `film-director`, and
  `film-editor` Skills from `movie/skills/`. This is the *know-how* layer (clarify/approve, shot &
  continuity guidance, QC review), loaded into the agent's own runtime by progressive disclosure.
- **`movie_tools = McpToolset(StreamableHTTPConnectionParams(url=MCP_URL, timeout=180, headers=…))`**
  — the *capability* layer: connects to `movie-mcp` over Streamable HTTP. The 180s timeout exists
  because image/video generation is slow (well past ADK's 5s default).
- **`root_agent = Agent(name="movie_director", model="gemini-3.5-flash", instruction=_instruction,
  tools=[SkillToolset(skills), movie_tools])`** — the exported agent. Skills + MCP tools compose in
  one agent: Skills say *how*, MCP tools do the credentialed *what*.

### `_mcp_headers() -> dict` — *fits: called during toolset construction (and by the Studio's direct MCP calls)*
Returns a Bearer `Authorization` header so the agent can reach an IAM-protected `movie-mcp` on Cloud
Run. It uses `MCP_BEARER_TOKEN` if set, else mints a Google ID token (audience = `MCP_AUDIENCE`) from
the GCP metadata server; returns `{}` for local dev so nothing changes locally. *Caveat noted in the
code:* the token is minted once at import (~1h lifetime).

### `_BASE_INSTRUCTION` (str constant) — *fits: the agent's operating manual, read every turn*
The long system prompt that encodes the entire product behavior: recognize `/help`, `/status`,
`/redo` etc.; **always ask AUTO vs INTERACTIVE mode first**; the casting/upload flow; the ≤10s video
/ frame-count pacing rules; the `generate_microshot` call rules; per-mode pipelines; QC-check
expectations; wardrobe-change rules; and the hard rules (always pass `user_id`, no IP names, call
tools rather than inventing URIs). This is where most of the "director" behavior actually lives.

### `_instruction(ctx) -> str` — *fits: called by ADK at the start of every turn*
Dynamic instruction provider. Injects the runtime user's id (`ctx.user_id`, their LDAP; falls back to
`director1`) into `_BASE_INSTRUCTION`, replacing `user_id='director1'` so every tool call the agent
makes is scoped to *that* user's private workspace. This is the single hook that makes the shared
agent multi-tenant.

---

## Part B — The host: `movie_studio/app.py`

**File purpose.** A FastAPI backend that (1) hosts `root_agent` with **persisted per-user sessions**
(ADK `DatabaseSessionService` → SQLite), (2) **streams** a turn to the browser over SSE, and (3)
**proxies** generated media so the browser can render/download it. The agent's results only carry
`movie://` links or raw paths — this app resolves them to real bytes ("links, not bytes: the host
fetches").

### B0. Startup wiring (module level) — *fits: run once at boot*
- Sets Vertex/MCP env defaults; computes `GEN_ROOT` (`movie/generated/`, where the pipeline writes
  all media) and `STATIC` (the SPA).
- **Imports the SAME `root_agent` and `_mcp_headers`** from `movie_agent/agent.py` (via `sys.path`) —
  the Studio and the CLI share one brain.
- **`_session_service = DatabaseSessionService(SESSION_DB_URL)`** and
  **`runner = Runner(agent=root_agent, app_name="movie_director", session_service=…)`** — the runner
  that executes turns with durable sessions. (Point `SESSION_DB_URL` at Postgres for multi-instance.)
- **`app.mount("/static", …)`** + `uvicorn.run(..., port=$PORT|8090)` in `__main__`.
- **`MEDIA_EXT` / `_UPLOAD_EXT`** — suffix→kind maps used when classifying/serving media.

### B1. The chat turn (the main flow: SSE streaming)

**`chat_stream(session, message, user)` — GET `/chat/stream`** — *fits: entry point of a chat turn.*
The browser opens an EventSource here. It sanitizes the user, then returns a `StreamingResponse` that
runs `_run_turn` as `text/event-stream` (with no-cache / no-buffering headers so events flush live).

**`_run_turn(user_id, adk_sid, message)` (async generator)** — *fits: the heart of a turn.*
1. Ensures the session exists (`_session_service.get_session`); if the id is unknown/stale (restart,
   new client), it creates a fresh one and emits a `session` event so the client adopts the new id.
2. Wraps the message as `genai_types.Content` and drives `runner.run_async(...)` — i.e. runs
   `root_agent`, which calls Skills + `movie-mcp` tools.
3. For every streamed event part it emits SSE events: a `tool` chip + an `activity` step on each
   **function_call**; on each **function_response** it parses the result, **paints media the instant
   it's ready**, and emits a result `activity`; on **text** it emits `text` + a `thought` activity.
4. Catches exceptions and surfaces them as `error` events (so the stream never dies silently), then
   emits `done`.

These helpers are called *inside* `_run_turn` to shape each SSE event:
- **`_sse(event) -> str`** — formats a dict as an SSE `data: …\n\n` line. *The wire format.*
- **`_parse_tool_result(response) -> dict`** — decodes ADK's `{'content':[{'text':'<json>'}]}` MCP
  wrapper into a merged dict. *Turns a raw tool response into usable fields (ids, uris, qc, status).*
- **`_collect_media(result) -> list[dict]`** — scans known URI keys (`resource_uri`, `video_uri`,
  `music_uri`, `microshot_uri`, …), resolves each to an asset URL, dedups, and tags kind
  (image/video/audio). *This is what makes an image appear in chat the moment its tool returns.*
- **`_to_asset_url(value) -> (url, name) | None`** — resolves a `movie://user/project/name` URI **or**
  a raw `.../generated/user/project/name` path into a servable `/asset/...` URL. *The bridge from the
  agent's link to the host's media proxy.*
- **`_arg_preview(args)`** / **`_result_summary(result)`** / **`_short(v, n)`** — build the compact
  text shown in the "activity" side panel (trimmed tool args, a one-line result summary of
  ids/status/qc/errors, and a generic truncator). *Observability for the UI, not core logic.*
- **`_SKILL_TOOLS`** (set) — the four SkillToolset tool names, used to label an activity step as a
  **skill** vs an **MCP tool** in the panel.

### B2. The media proxy (links → bytes)

**`get_asset(user, project, name, download)` — GET `/asset/{user}/{project}/{name}`** — *fits: fires
when the browser renders `<img>/<video>/<audio>` produced by B1.*
Resolves the file under `GEN_ROOT/user/project/name` (path-safety via `_safe_component`/`_safe_name`),
returns 400/404 on bad/missing paths, and serves it inline or as an attachment. Sends
`Cache-Control: no-cache` because generated files are **mutable** — a regenerated shot reuses the same
filename, so the browser must revalidate to avoid a stale image.

**`list_assets(user, project)` — GET `/assets/{user}/{project}`** — *fits: gallery/refresh.*
Lists all media files in a project dir as `{kind, name, url}` for the UI to display.

Path-safety helpers used by both (and by uploads):
- **`_safe_component(value)`** — reduces a user/project id to alnum/`-`/`_`, raising on empty (blocks
  `..` traversal).
- **`_safe_name(name)`** — reduces a filename to its basename and rejects empty/dotfiles.

### B3. Sessions (per-user persistence)

- **`_clean_user(user)`** — *fits: called by every route.* Sanitizes the LDAP into one id used as
  **both** the ADK session `user_id` and the `movie_store` `user_id`, so a user's sessions and their
  generated files share one private namespace.
- **`_session_meta(s)`** / **`_list_metas(user_id)`** — build a compact `{id, title, created}` and the
  sorted list of a user's sessions. *Used by the sessions routes below.*
- **`list_sessions(user)` — GET `/sessions`** — all persisted sessions for a user (survives restart).
- **`create_session(user, title)` — POST `/sessions`** — starts a new independent build (auto-numbered
  title) with its own project.
- **`delete_session(sid, user)` — DELETE `/sessions/{sid}`** — removes a session + transcript.
- **`session_history(sid, user)` — GET `/sessions/{sid}/history`** — *fits: on reload / switching
  chats.* Replays a persisted session's events into `text` + `media` entries (reusing
  `_parse_tool_result` + `_collect_media`) so the whole conversation, images and all, comes back.

### B4. Bring-your-own uploads (bypass the LLM)

**`upload(request, project, name, user, kind, description)` — POST `/upload`** — *fits: the ↑ Upload
button.* Saves a raw-body character/prop image into the project's media dir (with size/type checks),
then registers it on the project so the director reuses it in scenes. Registration goes through
`_mcp_call` — **not** the agent — because this is a deterministic action, not a creative decision.

**`_mcp_call(tool, args) -> dict`** — *fits: helper for `upload`.* Opens a direct Streamable HTTP MCP
client session (same Bearer auth as the agent via `_mcp_headers`) and invokes a `movie-mcp` tool
(`import_character`/`import_prop`) directly, returning its structured result. This is the one place
the Studio talks to `movie-mcp` without going through the LLM.

### B5. The SPA
- **`index()` — GET `/`** — returns `static/index.html` (the 3D chat UI). Everything above is the API
  that page calls.

---

## How it all fits together (one turn, end to end)

1. User types in the SPA → browser opens `GET /chat/stream` → **`chat_stream`** → **`_run_turn`**.
2. `_run_turn` runs **`root_agent`** via the runner. The agent reads **`_instruction`** (user-scoped),
   consults its Skills, and calls `movie-mcp` tools (e.g. `generate_microshot`).
3. Each tool result flows back through **`_parse_tool_result`** → **`_collect_media`** →
   **`_to_asset_url`**, and `_run_turn` streams `media`/`text`/`activity` SSE events.
4. The browser renders `<img src="/asset/...">`, which hits **`get_asset`**, which streams the real
   bytes off disk. (Links crossed the model's context; bytes never did — same "links, not bytes"
   principle as the MCP layer.)
5. Sessions persist via `DatabaseSessionService`, so **`session_history`** can replay the whole thing
   on the user's next visit.

**The clean separation to remember:** `agent.py` decides, `app.py` serves; the LLM path is
`/chat/stream`, the deterministic path is `/upload` + `_mcp_call`; and every media reference stays a
link until `get_asset` turns it into bytes.
