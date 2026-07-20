# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A hands-on Model Context Protocol (MCP) tutorial. It contains **two independent MCP servers**, several MCP clients/agents, and Agent Skills — all wrapping Google Gemini image/video models on Vertex AI (`nano-banana`, Veo). The teaching goal is the **context economics** of MCP (see `THEORY.md`): tools return a small `resource_uri`, never image bytes, so pixels enter the LLM context only if the host explicitly feeds them to the model.

Read `THEORY.md` (complete MCP reference), `README.md`, and `SEQUENCE.md` (Mermaid flow) before larger changes.

## Two servers, don't conflate them

- **`server/learn_mcp_server.py`** — `learn-mcp`. A single-file teaching server that exercises **every MCP primitive**: tools, resources (`config://app`, templated `image://{name}`), a prompt (`art_brief`), progress, structured output, plus capability-gated `elicitation` (`commission_art`) and `sampling` (`caption_last_image`) demos that degrade gracefully. Flagship tools: `generate_image`, `edit_image`.
- **`movie/movie_server.py`** — `movie-mcp`. A realistic multi-module app: an AI film-production pipeline. Composes `movie_store` (per-user story bible), `film_grammar` (continuity validator), `imagegen` (nano-banana), `videogen` (Veo/Omni async jobs).

## Commands

Each subproject has its own `pyproject.toml`; `uv` creates the venv on first run. `--project <dir>` runs a script against another subproject's deps.

```bash
# learn-mcp: raw protocol client over stdio (no LLM — watch the wire; exercises every feature)
cd client && uv run --project ../server python raw_client.py

# learn-mcp over Streamable HTTP + the hosted client
cd server && uv run python learn_mcp_server.py --http --port 9000
cd client && uv run --project ../server python remote_client.py        # honors MCP_URL

# ADK agent → learn-mcp (start the HTTP server first)
cd adk_agent && uv run python run_test.py
cd adk_agent && uv run python skill_mcp_demo.py                         # Skills + MCP composed

# adk web chat UI for both learn-mcp agents (adk_agent, creative_studio)
uv run --project adk_agent adk web --host 0.0.0.0 --port 8080 --allow_origins="*" .

# movie-mcp: end-to-end pipeline test (drives core funcs directly; uses real nano-banana)
cd movie && GOOGLE_CLOUD_PROJECT=<proj> uv run python test_local.py
# movie-mcp server + its ADK director agent
cd movie && GOOGLE_CLOUD_PROJECT=<proj> uv run python movie_server.py --http --port 9100
cd movie_agent && uv run python run.py "Make a 3-scene story about a witch and her cat"

# movie_studio: 3D chat UI (hosts the director agent + media proxy; renders images/video/audio inline)
# start the MCP server (9100) first, then:
GOOGLE_CLOUD_PROJECT=<proj> uv run --project movie_studio python app.py   # http://localhost:8090

# Pure-logic units (no cloud creds needed)
cd movie && uv run python film_grammar.py     # validator self-demo (valid + invalid plans)
cd movie && uv run python movie_store.py       # store smoke test incl. cross-user isolation
```

There is no lint/format config and no pytest suite. "Tests" are runnable `__main__` smoke tests / `test_local.py`-style scripts that print `PASS`/`FAIL` and `assert`.

## Auth / environment

Everything image/video calls **Vertex AI** via Application Default Credentials:
- `gcloud auth application-default login`, Vertex enabled on the project.
- `GOOGLE_CLOUD_PROJECT=<proj>` (or ADC default), `GOOGLE_CLOUD_LOCATION=global` (image model; video uses `VIDEO_LOCATION`, default `us-central1`).
- `NANO_BANANA_MODEL` default `gemini-3.1-flash-lite-image`. ADK agents set `GOOGLE_GENAI_USE_VERTEXAI=TRUE`.
- The `genai.Client` is always lazy/singleton so a server can start and list tools **without** creds.

## Architecture principles (the reason things are shaped this way)

- **Links, not bytes.** Image tools save the PNG server-side and return a `GeneratedImage` (Pydantic → `outputSchema`) with a `resource_uri` like `image://gen.png`. Bytes travel to the client only on `resources/read`. Keep this — inlining base64 in a tool result puts megabytes in the model's context on every call.
- **Skills (know-how) vs MCP tools (capability) are separate layers.** `SKILL.md` files (`adk_agent/skills`, `creative_studio/skills`, `movie/skills`) run inside the ADK agent's own runtime via `SkillToolset` + `load_skill_from_dir`; they decide *how*. MCP tools supply the credentialed *what*. `SKILL.md` is an open cross-runtime spec (progressive disclosure: L1 metadata resident, L2/L3 load on trigger) — not Claude-specific.
- **Per-call model selection.** `generate_image`/`edit_image` type `model` as a `Literal` (`ImageModel`) so it surfaces as an **enum** in the tool schema. Add a model = add one line to the `Literal`, nothing else.
- **Tool errors, not crashes.** Raise `ValueError` inside a tool (e.g. `divide` by zero, missing source image) — MCP surfaces it as `isError=true` the model can read and react to.
- **MCP timeouts.** Image gen is ~12s; ADK's default MCP tool timeout is 5s. Clients set `timeout=120` (movie: `180`). Don't lower these.
- **Transport dual-mode.** Both servers: `mcp.run()` = stdio (default, for a subprocess client); `--http` or presence of `$PORT` = Streamable HTTP bound to `0.0.0.0` (Cloud Run). `learn-mcp` disables FastMCP DNS-rebinding protection because Cloud Run is the security boundary; keep it enabled for a purely-local HTTP server.

### movie-mcp specifics

- **Story "bible"** — JSON per project at `movie/data/<user_id>/<project_id>.json` (gitignored, regenerable). `movie_store` is **strictly user-partitioned**: every function takes `user_id` first and only touches that user's dir; `user_id`/`project_id` are sanitized (alnum/`-`/`_`) to block path traversal. Writes are atomic (temp + `os.replace`) under a module `threading.Lock`. Generated images live under `movie/generated/<user_id>/<project_id>/` (gitignored).
- **Pipeline order** (each step conditions on the previous): `create_project` → `generate_style_ref` (global look anchor) → `add_character` (canonical reference sheet) → `establish_scene` (people-free set plate + blocking) → `plan_scene` → `generate_shot` → `start_shot_video`/`get_shot_video`.
- **Validation gate.** `plan_scene` runs `film_grammar.validate_plan` and **persists shots only if there are zero `error`-severity violations** (warns are allowed). Rules: R7 establish-first, R1 180° line, R3 eyeline, R4 30° jump-cut, R14 reciprocal OTS height, R5 screen-direction (warn), R19 lens consistency (warn), anchor existence. `film_grammar` is pure logic — no I/O.
- **Keyframe composition is iterative.** `mv_generate_shot` starts from the styled empty set plate and edits in **one character at a time** (≤2 reference images per model call). This is deliberate — passing many refs at once makes the model drop/invent characters. Don't "optimize" it back to a single multi-ref call.
- **Editor / QC review loop (`film-editor` skill + `imagegen.review_image`).** After rendering, `add_character`, `generate_shot`, and `generate_microshot` run a vision critic (`imagegen.review_image`, model `$QC_MODEL`) that scores per dimension (prompt adherence, character identity & style *vs. the reference images*, framing, anatomy, extra/missing subjects, text, lighting) and, on failure, **regenerate with the critic's `issues` fed back into the prompt** — up to `$QC_MAX_TRIES` attempts (default 2). Results carry `qc_ok`/`qc_score`/`qc_issues` (also persisted to the bible). `review_asset` exposes the critic as an on-demand MCP tool. The `film-editor` `SKILL.md` is the agent-facing know-how (rubric + regenerate-with-feedback → escalate-to-user decision). The critic passes reference sheets so it judges *identity/style consistency*, not just a single image; `qc_check` remains as a `(ok, issues)` back-compat shim.
- **Video is a stateless async job.** `start_video` returns an upstream job *name*; `poll_video` rehydrates by name. The server holds no job state — only the name stored in the bible. Video models are region-scoped (not `global`).
- **In-chat help / slash commands.** `get_help(topic)` is an MCP tool whose content (`HELP_TOPICS`, `HELP_COMMANDS`) is the single source of truth for how to use the system, so every client gets the same guidance. The `movie_director` agent recognizes `/help [topic]`, `/commands`, `/status`, `/modes`, `/redo`, `/restart` (a leading `/` = command, not story input) and calls `get_help` / summarizes project state accordingly; it proactively points a stuck user to `/help` and mentions it at chat start.
- **Video failures are recorded, not swallowed.** `_omni_poll`/`_veo_poll` extract the upstream failure reason (interaction error, or "completed but no video part" = safety/content filter) into an `error` field. The scene/shot tools persist it to the bible as `video_error`, return it in the tool result, and `logging.warning` it to the server console (`LOG_LEVEL` env). The `movie_director` agent is instructed to quote that reason to the user (so it shows in the `adk web` chat). There is no separate log *file* — failures surface via the tool result, the bible's `video_error`, and stderr.
- **Resource indirection (links, not bytes), same as learn-mcp.** The bible stores absolute filesystem paths (the pipeline chains files internally), but the image tools' MCP results also carry a `resource_uri` of the form `movie://<user>/<project>/<name>`. The templated `@mcp.resource("movie://{user_id}/{project_id}/{name}")` (`read_asset`) returns the bytes on demand, and `list_project_assets` enumerates a project's images as `ResourceLink` blocks. This is what lets a remote client display/save a keyframe without paths or inline bytes crossing into the model's context. The `mv_*` core functions still return raw paths (used by `test_local.py` and internal chaining); the `resource_uri` is added in the thin `@mcp.tool()` wrappers.
- **Image-model content filter.** Character/scene prompts deliberately use ILLUSTRATION framing, clearly-adult **generic** descriptions, and **no copyrighted/IP names** (the model blocks realistic people and named IP; animals are fine). The bible stores real names; the model only ever sees descriptions. Preserve this when editing prompts.

## Conventions

- `from __future__ import annotations` at the top of every module.
- `uuid.uuid4().hex[:N]` for ids; monotonic-suffix filenames (`gen.png`, `gen_1.png`) — no `random`/timestamps in names.
- Standalone `movie/*.py` scripts (`cinderella.py`, `witch_broom.py`, `test_video.py`) are ad-hoc pipeline drivers; the intended driver is the **`movie_agent`** ADK agent, not hand-written scripts.
- `.gitignore` excludes `generated/`, `movie/data/`, `transcripts/`, `.adk/`, `*.evalset.json`, and anything credential-shaped — regenerable or secret; don't commit it.
