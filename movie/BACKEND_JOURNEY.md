# Prompt → Video: the full backend journey (skills · MCP · GCP)

## The stack (components)

```
Browser (adk web UI)
      │  HTTP
┌─────▼──────────────────────────────────────────────────────────────────────┐
│ ADK HARNESS  (movie_agent)                                                   │
│   • Runner (the loop)                                                        │
│   • Gemini LLM  ── reasoning ──▶  GCP Vertex AI  (model: gemini-2.5-flash)   │  ← GCP call #1
│   • SkillToolset → loads SKILL.md from local FS: script-developer, film-director │
│   • McpToolset  → speaks MCP (JSON-RPC over Streamable HTTP)                 │
└─────┬───────────────────────────────────────────────────────────────────────┘
      │  MCP  (localhost:9100  →  Cloud Run in prod)
┌─────▼──────────────────────────────────────────────────────────────────────┐
│ MOVIE MCP SERVER  (movie/movie_server.py)  — stateless tools                 │
│   ├─ movie_store.py   → Bible (JSON in movie/data/  →  Firestore in prod)     │
│   ├─ film_grammar.py  → validate_plan() (pure logic, no I/O)                 │
│   ├─ imagegen.py      → google.genai ─▶ GCP Vertex AI  nano-banana image     │  ← GCP call #2
│   └─ videogen.py      → google.genai ─▶ GCP Vertex AI  Veo video (LRO)       │  ← GCP call #3
└─────┬───────────────────────────────────────────────────────────────────────┘
      │  files
   Storage:  movie/generated/<user>/<project>/   (→ GCS in prod)
   Auth to GCP: Application Default Credentials (service account) · project vital-octagon-19612
```

**Only three things actually hit GCP:** (1) the agent's Gemini reasoning, (2) nano-banana image
generation, (3) Veo video generation. Skills load from the local filesystem; MCP is just the wire;
the Bible and media are local files (Firestore + GCS in production).

---

## Stage-by-stage backend trace

### 0. Setup (once)
- `adk web` imports `movie_agent/agent.py` → `SkillToolset` reads `movie/skills/{script-developer,
  film-director}/SKILL.md` from disk; `McpToolset` opens a Streamable-HTTP session to the movie
  MCP server (`initialize` handshake, tool discovery). No GCP yet.

### 1. Prompt in / clarify
- Browser POSTs the message → **ADK Runner** → **Gemini** (Vertex AI, GCP #1) with the skills'
  L1 metadata + tool schemas in context.
- Gemini calls `load_skill("script-developer")` (an in-agent tool) → its L2 workflow says
  "clarify + ask visual style". Gemini replies with questions. **No MCP, no image GCP.**

### 2. Treatment + approvals (cast, scenes)
- Pure Gemini reasoning turns (GCP #1 each). The agent proposes cast/scenes and waits.
  **No tools fire until you approve** — nothing written, nothing generated.

### 3. Build cast → GCP image
- On approval, Gemini calls MCP tools over Streamable HTTP:
  - `create_project` → MCP server → `movie_store.create_project` → writes `movie/data/<user>/<pid>.json`.
  - `generate_style_ref` → `imagegen.generate_image` → `google.genai.Client(vertexai=True)` →
    **Vertex AI nano-banana** (GCP #2) → PNG bytes → saved to `generated/…/style_ref.png` →
    `movie_store.set_style_ref` records the URI in the Bible.
  - `add_character` ×N → same path (image → file → Bible.characters[refs]).
- Result URIs (not bytes) return through MCP → Gemini → shown to you.

### 4. Render a scene → validate + GCP image (iterative)
- `establish_scene` → `imagegen` (GCP #2) → people-free set **plate** → Bible.scenes.
- `plan_scene` → MCP server builds a `film_grammar.ShotPlan` → **`validate_plan()`** (180°,
  eyeline, 30°, establish-first, anchors — pure logic, no GCP). Persists shots only if valid.
- `generate_shot` → **iterative insertion**: base plate, then one `imagegen.compose_image` call
  **per character** (each = plate + one sheet, GCP #2 each) → final keyframe saved → Bible.shot.

### 5. Animate → GCP video (async job)
- `start_shot_video` → `videogen.start_video` → `google.genai` → **Vertex AI Veo**
  (`veo-3.1-fast-generate-001`, region us-central1) → returns a **long-running operation name**
  (GCP #3 start). Bible records `video_job` + status `video_running`. Turn returns fast.
- `get_shot_video` (poll) → `videogen.poll_video` → `operations.get(name)` (GCP #3 poll) →
  when done, video bytes → `generated/…/vid_<shot>.mp4` → Bible `video_uri`, status `video_done`.
- The video URI returns through MCP → Gemini → you.

---

## Who holds what (state backends)
| Data | Backend (dev) | Backend (prod) |
|---|---|---|
| Conversation / session | ADK InMemory (or DatabaseSessionService) | VertexAiSessionService / Cloud SQL |
| Bible (project/characters/scenes/shots) | `movie/data/*.json` | Firestore keyed by (user, project) |
| Media (sheets, plates, keyframes, mp4) | `movie/generated/` | Cloud Storage (GCS) |
| Video job | Vertex AI (upstream) | Vertex AI |
| Auth | ADC service account | Workload Identity |

## GCP touchpoints, summarized
1. **Gemini** (agent reasoning) — Vertex AI, model `gemini-2.5-flash`, region global.
2. **nano-banana** (images) — Vertex AI, `gemini-3.1-flash-lite-image`, region global.
3. **Veo** (video) — Vertex AI, `veo-3.1-fast-generate-001`, region us-central1, long-running.
All authenticated by Application Default Credentials on project `vital-octagon-19612`. Skills,
MCP transport, film-grammar, and the Bible never call GCP.
```
