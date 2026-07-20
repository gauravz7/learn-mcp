# learn-mcp — a hands-on Model Context Protocol project

An end-to-end MCP tutorial you can run. It contains **two independent MCP servers**, several MCP
clients/agents, **Agent Skills**, and a 3D chat UI — all wrapping Google Gemini image/video/music
models on Vertex AI (nano-banana, Veo/Omni, Lyria). The teaching goal is the **context economics**
of MCP: tools return a small `resource_uri`, never image bytes, so pixels enter the model's context
only if the host explicitly feeds them (see `THEORY.md`).

- **`THEORY.md`** — a complete, plain-English MCP reference (REST vs MCP vs Skills, context
  economics, transports, auth, scaling).
- **`SEQUENCE.md`** — the end-to-end sequence diagram (Mermaid).
- **`CLAUDE.md`** — architecture notes for working in this repo.

Key idea: only a small `resource_uri` crosses back in a tool result — the bytes travel to the
client **only on demand** (`resources/read`), and enter the LLM context **only if the host feeds
them to the model**. That's what keeps the agent's context small.

![learn-mcp end-to-end sequence diagram](assets/sequence-diagram.png)

---

## 1. Skills (know-how)

Skills are `SKILL.md` files that run **inside the ADK agent's own runtime** (`SkillToolset` +
`load_skill_from_dir`). They decide *how* to do something; MCP tools supply the credentialed *what*.
Progressive disclosure: only ~L1 metadata is resident until a skill is triggered (`SKILL.md` is an
open cross-runtime spec — Claude and Google ADK both consume it).

**Creative Studio skills** (`adk_agent/skills`, `creative_studio/skills`):

| Skill | What it does |
|---|---|
| `poster-designer` | Rough idea → polished poster / flyer / album-cover prompt |
| `social-post` | Square social image + platform captions |
| `logo-maker` | Iconic logo mark / app icon |
| `photo-editor` | Iteratively edit an existing generated image |

**Movie-production skills** (`movie/skills`):

| Skill | What it does |
|---|---|
| `script-developer` | Vague idea / uploaded script → approved cast + scene breakdown (human-in-the-loop) |
| `film-director` | Story beat → validated, continuity-safe shot plan → render |
| `film-editor` | Reviews rendered frames for quality/continuity; decides regenerate-with-feedback → accept → escalate |

---

## 2. MCP servers we built

### `learn-mcp` (`server/learn_mcp_server.py`) — every MCP primitive
A single-file teaching server. **Tools:** `generate_image`, `edit_image`, `add`,
`list_image_models`, `get_weather`, `divide`, `long_task`, `list_generated_images`,
`commission_art` (elicitation demo), `caption_last_image` (sampling demo). **Resources:**
`config://app`, templated `image://{name}`. **Prompt:** `art_brief`. Per-call image-model selection
via a `Literal` enum; tool errors surface as `isError`; progress notifications; structured output.

### `movie-mcp` (`movie/movie_server.py`) — a realistic AI film pipeline
Composes `movie_store` (per-user story "bible"), `film_grammar` (continuity validator), `imagegen`
(nano-banana + vision QC critic), `videogen` (Veo/Omni async jobs), `musicgen` (Lyria).

| Group | Tools |
|---|---|
| Project / bible | `create_project`, `list_projects`, `get_project` |
| Assets | `generate_style_ref`, `add_character`, `establish_scene` |
| Shots | `plan_scene` (film-grammar gate), `generate_shot`, `generate_microshot` |
| Video | `start_shot_video`, `get_shot_video`, `start_scene_video`, `get_scene_video` |
| Audio | `generate_music` |
| Editor / meta | `review_asset` (vision critic), `list_project_assets`, `get_help` |

Resource: `movie://{user_id}/{project_id}/{name}` (read bytes on demand). Highlights: **strict
per-user partitioning**; a **film-grammar validation gate** (180°, eyeline, 30°, establish-first);
**iterative keyframe composition** (one character at a time); an **editor QC loop** (render →
vision critic → regenerate with the critic's feedback); stateless async video with recorded failure
reasons; in-chat `/help`.

---

## 3. Deploy to a NEW Google Cloud project (step by step)

Deploys 3 public Cloud Run services (`movie-mcp`, `learn-mcp`, `movie-studio`) with a shared GCS
bucket for media + bibles (plus an optional `adk web` harness). Dockerfiles ship for `server/`,
`movie/`, and `movie_studio/` (the last builds from the repo root via `cloudbuild.studio.yaml`).
Requires the `gcloud` CLI.

```bash
# ---- 0. pick your project + region ----
export PROJECT=your-new-project-id
export REGION=us-central1
export BUCKET=gs://${PROJECT}-movie-studio
gcloud auth login
gcloud config set project $PROJECT

# ---- 1. enable APIs ----
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com storage.googleapis.com aiplatform.googleapis.com

# ---- 2. media + bibles bucket, mounted into the services ----
gcloud storage buckets create $BUCKET --location=$REGION
# grant the Cloud Run runtime SA (default compute SA) access to the bucket + Vertex
PROJNUM=$(gcloud projects describe $PROJECT --format='value(projectNumber)')
RUNTIME_SA=${PROJNUM}-compute@developer.gserviceaccount.com
gcloud storage buckets add-iam-policy-binding $BUCKET \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/storage.objectAdmin
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:${RUNTIME_SA}" --role=roles/aiplatform.user

# ---- 3. movie-mcp (deploy first; capture its URL) ----
gcloud run deploy movie-mcp --source movie/ --region $REGION --allow-unauthenticated \
  --execution-environment=gen2 --memory=2Gi --cpu=2 --timeout=900 --max-instances=1 \
  --add-volume=name=state,type=cloud-storage,bucket=${PROJECT}-movie-studio \
  --add-volume-mount=volume=state,mount-path=/mnt/state \
  --set-env-vars=MOVIE_GEN_ROOT=/mnt/state/generated,MOVIE_DATA_ROOT=/mnt/state/data,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,LOG_LEVEL=INFO
export MCP=$(gcloud run services describe movie-mcp --region $REGION --format='value(status.url)')

# ---- 4. learn-mcp (standalone; server/Dockerfile) ----
gcloud run deploy learn-mcp --source server/ --region $REGION --allow-unauthenticated \
  --set-env-vars=GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global

# ---- 5. movie-studio (UI) — builds from the repo ROOT (Dockerfile copies movie_agent/ + movie/skills/) ----
gcloud artifacts repositories create mcp --repository-format=docker --location=$REGION 2>/dev/null || true
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT}/mcp/movie-studio:latest
gcloud builds submit --config cloudbuild.studio.yaml --substitutions _IMAGE=$IMAGE .
gcloud run deploy movie-studio --image $IMAGE --region $REGION --allow-unauthenticated \
  --execution-environment=gen2 --memory=2Gi --cpu=2 --timeout=900 --max-instances=1 \
  --add-volume=name=state,type=cloud-storage,bucket=${PROJECT}-movie-studio \
  --add-volume-mount=volume=state,mount-path=/mnt/state \
  --set-env-vars=MCP_URL=${MCP}/mcp,MOVIE_GEN_ROOT=/mnt/state/generated,GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_VERTEXAI=TRUE
# NOTE: for multi-instance, set SESSION_DB_URL to a Cloud SQL/Postgres URL (SQLite is single-instance).

# ---- (optional) adk web dev harness: no Dockerfile shipped — run it locally (see Usage),
#      or add a Dockerfile mirroring movie_studio/Dockerfile (CMD: adk web --port $PORT). ----

# ---- teardown when done (these bill Vertex + are public) ----
# gcloud run services delete movie-mcp learn-mcp movie-studio --region $REGION
```

> These services are **public and bill Vertex** (image + Veo video is pricey). `--max-instances`
> caps scale, not per-request cost. Delete them after a demo. See `CLAUDE.md` for the persistence
> and DNS-rebinding details baked into the servers for Cloud Run.

---

## 4. Usage

### Prerequisites (local)
- **[uv](https://docs.astral.sh/uv/)** and Python 3.11+.
- **Vertex auth:** `gcloud auth application-default login`, Vertex enabled. Set
  `GOOGLE_CLOUD_PROJECT=<proj>`, `GOOGLE_CLOUD_LOCATION=global`. Each subproject has its own
  `pyproject.toml`; `uv` creates the venv on first run.

### learn-mcp
```bash
# raw protocol client over stdio (no LLM — watch the wire; exercises every primitive)
cd client && uv run --project ../server python raw_client.py

# HTTP + hosted client
cd server && uv run python learn_mcp_server.py --http --port 9000
cd client && uv run --project ../server python remote_client.py

# ADK agent → learn-mcp, and Skills+MCP composed (start the HTTP server first)
cd adk_agent && uv run python run_test.py
cd adk_agent && uv run python skill_mcp_demo.py

# chat UI for both learn-mcp agents
uv run --project adk_agent adk web --host 0.0.0.0 --port 8080 --allow_origins="*" .
```

### movie-mcp + Movie Studio (the full app)
Start the MCP server first, then the UI:
```bash
# 1) MCP server (16+ tools)
cd movie && GOOGLE_CLOUD_PROJECT=<proj> uv run python movie_server.py --http --port 9100

# 2) Movie Studio 3D chat UI  →  http://localhost:8090
GOOGLE_CLOUD_PROJECT=<proj> uv run --project movie_studio python movie_studio/app.py

# (optional) the director agent in adk web
cd movie_agent && MCP_URL=http://localhost:9100/mcp uv run python run.py "Make a 3-scene story about a witch and her cat"
```

**In Movie Studio (http://localhost:8090):**
- **Sign in with your LDAP** (an identity/namespace key — no password). Your sessions and generated
  media are **persisted per user** (SQLite via ADK `DatabaseSessionService`) and reappear on return.
- **＋ New** starts a parallel session (each = its own project); the chip list switches between them.
- Pick a build **mode**: *AUTO* (director builds end-to-end) or *INTERACTIVE* (approve each stage).
- Type **`/help`** any time (also `/status`, `/modes`, `/redo`, `/restart`).
- **Gallery** tab = generated frames/clips/scores (download or Export all). **Activity** tab =
  a live timeline of the director's steps — skills loaded, tools called (with args), results, QC
  verdicts and errors — so you can see how it's thinking.
- **Editor loop:** `add_character` / `generate_shot` / `generate_microshot` self-review and
  regenerate with feedback; the director surfaces `qc_issues` and offers to regenerate.

### Pure-logic units (no cloud creds)
```bash
cd movie && uv run python film_grammar.py     # continuity validator self-demo
cd movie && uv run python movie_store.py       # store smoke test incl. cross-user isolation
```

## Configuration knobs
- `NANO_BANANA_MODEL` (default `gemini-3.1-flash-lite-image`), `HIFI_IMAGE_MODEL`, `QC_MODEL`
  (default `gemini-3.5-flash`), `QC_MAX_TRIES` (default 2).
- `VEO_MODEL`/`OMNI_MODEL`, `VEO_LOCATION` (default `us-central1`), `OMNI_LOCATION` (`global`).
- `MCP_URL` (agent → server), `SESSION_DB_URL` (studio session store), `MOVIE_GEN_ROOT` /
  `MOVIE_DATA_ROOT` (state paths, e.g. a GCS mount), `LOG_LEVEL`.

## Scaling notes
- Image gen is ~12s; MCP clients set generous timeouts (ADK default 5s → code uses 120–180s).
- For high concurrency run the MCP server **stateless** over Streamable HTTP and put artifacts in
  object storage (return links). The real bottleneck is usually **model quota**. See `THEORY.md` §11.
