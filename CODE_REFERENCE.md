# Code Reference

A per-function reference for every Python file in this repository, grouped by subsystem. Each file
lists a one-line purpose followed by one line per function / method / MCP primitive.

**Contents**
- [1. learn-mcp server & clients](#1-learn-mcp-server--clients)
- [2. movie-mcp — the film-production pipeline](#2-movie-mcp--the-film-production-pipeline)
- [3. ADK agents & studios](#3-adk-agents--studios)
- [4. Ad-hoc scripts & tooling](#4-ad-hoc-scripts--tooling)
- [5. Package markers](#5-package-markers)

> The two servers, in one line each: **`server/learn_mcp_server.py`** (`learn-mcp`) is a single-file
> teaching server that exercises *every* MCP primitive; **`movie/movie_server.py`** (`movie-mcp`) is a
> realistic multi-module app that composes a story bible, a continuity validator, image/video/music
> generators, and a vision QC critic into a film-production pipeline.

---

## 1. learn-mcp server & clients

### `server/learn_mcp_server.py`
_A single-file FastMCP teaching server that wraps nano-banana image generation on Vertex AI and exercises every MCP primitive (tools, resources, prompt, progress, elicitation, sampling)._

- **`_client()`** — Lazily constructs and caches a singleton Vertex `genai.Client` so the server can start and list tools without credentials.
- **`_save_image_bytes(data, mime, stem)`** — Writes image bytes to `generated/` under a collision-free monotonic-suffix filename and returns the `Path`.
- **`_extract_image(resp)`** — Pulls the first inline image (bytes + mime) plus any text out of a genai response, raising `ValueError` if none is present.
- **`GeneratedImage`** — Pydantic model used as the image tools' `outputSchema`, carrying a `resource_uri`, path, mime, size, model, and prompt instead of raw base64.
- **`WeatherReport`** — Pydantic model serving as a second structured `outputSchema` (city, temperature, condition, humidity).
- **`generate_image(prompt, ctx, aspect_ratio, model)`** — `@mcp.tool` that generates a new image from text via a Gemini model, emitting progress/log notifications and returning a `GeneratedImage` with a saved file and resource URI.
- **`edit_image(source, edit_prompt, ctx, model)`** — `@mcp.tool` that resolves a source image (resource URI, filename, or path), edits it with a Gemini instruction, and returns a `GeneratedImage`, raising `ValueError` (surfaced as `isError`) if the source is missing.
- **`add(a, b)`** — `@mcp.tool` returning the sum of two floats; simplest typed-in/scalar-out tool.
- **`list_image_models()`** — `@mcp.tool` returning the available `ImageModel` enum values with the default model listed first.
- **`get_weather(city)`** — `@mcp.tool` returning a deterministic mock `WeatherReport` to demonstrate structured output.
- **`divide(a, b)`** — `@mcp.tool` dividing two floats, raising `ValueError` on divide-by-zero to demonstrate a tool error (`isError=true`).
- **`long_task(steps, ctx)`** — `@mcp.tool` simulating a long job that emits per-step progress and debug-log notifications, returning a completion string.
- **`list_generated_images()`** — `@mcp.tool` listing existing PNGs in `generated/` as MCP `ResourceLink` content blocks.
- **`ArtCommission`** — Pydantic schema (subject, style, aspect_ratio) used as the elicitation request schema for `commission_art`.
- **`commission_art(ctx)`** — `@mcp.tool` elicitation demo that asks the user (via the client) for structured art details then generates an image, degrading gracefully if the client lacks the elicitation capability.
- **`caption_last_image(ctx)`** — `@mcp.tool` sampling demo that asks the host's LLM (via `ctx.session.create_message`) to caption the latest image, degrading gracefully if the client lacks the sampling capability.
- **`app_config()`** — `@mcp.resource("config://app")` static resource returning server configuration as a JSON string.
- **`read_image(name)`** — `@mcp.resource("image://{name}")` templated resource returning a generated image's bytes as a blob, raising `ValueError` if absent.
- **`art_brief(subject, style)`** — `@mcp.prompt` user-invoked prompt that expands a rough idea into a polished one-paragraph image-generation brief.
- **`main()`** — Entrypoint that parses `--http`/`--port` args and runs the server over Streamable HTTP (binding `0.0.0.0`, also triggered by a `$PORT` env var) or stdio by default.
- Module-level: lazy singleton `_genai_client`; `ImageModel` `Literal` (drives the tool schema enum) and `DEFAULT_IMAGE_MODEL`/`NANO_BANANA_MODEL`, `GOOGLE_CLOUD_PROJECT`/`GOOGLE_CLOUD_LOCATION` env config; `mcp = FastMCP(...)` with DNS-rebinding protection disabled for Cloud Run.

### `client/raw_client.py`
_A minimal LLM-free MCP client that launches learn-mcp over stdio and advertises sampling, elicitation, roots, and logging client capabilities so every server feature round-trips._

- **`out(*a)`** — Prints a line and appends it to the in-memory `_lines` buffer for later transcript saving.
- **`sampling_cb(ctx, params)`** — Sampling callback that fakes an LLM completion (a stub caption) so the server's sampling demo works offline.
- **`elicitation_cb(ctx, params)`** — Elicitation callback that auto-accepts with canned structured art details to demo the elicitation round-trip.
- **`roots_cb(ctx)`** — Roots callback advertising the server directory as a single filesystem `Root`.
- **`logging_cb(params)`** — Logging callback that prints server log-message notifications with their level.
- **`main()`** — Opens a stdio `ClientSession` wired with all four callbacks, then walks the full protocol (initialize, list tools/resources/templates/prompts, call `add`/`get_weather`/`divide`, generate/read-back/edit an image, list resource links, read a static resource, get a prompt, and run the elicitation and sampling demos), finally writing a transcript file.

### `client/remote_client.py`
_An MCP client that connects to the deployed learn-mcp server on Cloud Run over Streamable HTTP, authenticating with a Google identity token._

- **`get_token()`** — Returns a Google identity token whose audience is the service URL, using `MCP_BEARER_TOKEN` if set otherwise minting one from the GCP metadata server, exiting on failure.
- **`main()`** — Opens an authenticated Streamable HTTP `ClientSession`, initializes it (printing server info and `Mcp-Session-Id`), lists tools, and calls `add`, `get_weather`, and `generate_image` against the hosted server.
- Module-level: `DEFAULT_URL`/`MCP_URL` and derived `MCP_ENDPOINT` (`/mcp`) configure the target; `MCP_BEARER_TOKEN` overrides token minting.

---

## 2. movie-mcp — the film-production pipeline

### `movie/movie_server.py`
_The `movie-mcp` FastMCP server: an AI film-production pipeline that composes the story bible, film-grammar validator, image/video/music generators, and a vision QC critic into MCP tools and a templated resource._

**Helpers — refs, paths, safety**
- **`_qc_refs(bible, scene, cast)`** — internal helper returning the capped (≤5) list of canonical reference image paths (style ref, scene establish plate, each cast sheet) the vision critic compares an asset against.
- **`_gen_dir(user_id, project_id)`** — internal helper that creates (if needed) and returns the per-user/per-project `generated/` output directory as a `Path`.
- **`_safe_component(value)`** — internal helper reducing a `user_id`/`project_id` to safe path chars (alnum/`-`/`_`), raising `ValueError` on an empty result to block traversal.
- **`_safe_name(name)`** — internal helper stripping any directory/traversal from an asset name down to a bare filename, raising `ValueError` on empty or dotfile names.
- **`_asset_uri(user_id, project_id, path)`** — internal helper mapping a generated file path to its `movie://<user>/<project>/<name>` MCP resource URI.

**Helpers — anchors & cast resolution**
- **`_known_anchors(bible, scene_id)`** — internal helper listing anchor ids that actually exist in the bible for a scene (establish/char/loc/frame), used by plan validation.
- **`_resolve_anchor_paths(bible, shot)`** — internal helper mapping a shot's anchor ids to real on-disk image paths for keyframe composition, filtering out missing files.
- **`_match_char(bible, token)`** — internal helper resolving a character token (exact id, `char:` prefix, case-insensitive name, or id-prefix) to a real char_id or `None`.
- **`_resolve_cast(bible, shot)`** — internal helper building the `(ref_path, name)` cast for a shot from its `char:` anchors and `subject`, returning `(cast, warnings)` where unresolved names or missing sheets become warnings.

**Core pipeline — project/style (plain importable funcs driven by `test_local.py`)**
- **`mv_create_project(user_id, title, style_guide)`** — internal core func creating a project in the bible and returning its `project_id`/title/style.
- **`mv_list_projects(user_id)`** — internal core func returning the user's own projects from the store.
- **`mv_get_project(user_id, project_id)`** — internal core func returning the full story bible for a project.
- **`mv_set_style(user_id, project_id, style_guide)`** — internal core func updating the project's style guide in the bible.
- **`mv_generate_style_ref(user_id, project_id, description, prompt)`** — internal core func generating the global 16:9 style anchor image, saving it, and recording `style_ref` in the bible.
- **`mv_add_character(user_id, project_id, name, description, prompt)`** — internal core func generating a canonical character reference sheet with a QC render→review→corrective-retry loop (up to `QC_MAX_TRIES`), persisting the character with its sheet and `qc_*` fields.
- **`mv_establish_scene(user_id, project_id, scene_id, description, lighting, blocking, prompt)`** — internal core func generating a people-free set plate (composed against the style ref when present) and persisting the scene's lighting/blocking/establish URI.
- **`mv_plan_scene(user_id, project_id, scene_id, shots)`** — internal core func validating a structured shot plan via `film_grammar.validate_plan` and persisting the shots to the bible only if there are zero error-severity violations.
- **`mv_generate_shot(user_id, project_id, shot_id, prompt, qc)`** — internal core func composing a keyframe by iterative one-character-at-a-time insertion (HiFi model when cast≥2), running a vision QC loop that re-renders with critic feedback, persisting the keyframe and `qc_*` fields plus returning cast warnings.

**Video — per-shot**
- **`mv_start_shot_video(user_id, project_id, shot_id, model, duration_seconds)`** — internal core func starting an async keyframe→video job (Omni, falling back to Veo on failure), persisting the job name/backend to the bible; requires an existing keyframe.
- **`mv_get_shot_video(user_id, project_id, shot_id)`** — internal core func polling a shot's async video job by its stateless upstream name, saving the mp4 and recording `video_uri` on success or `video_error` (logged) on failure.

**Micro-shot → scene-video helpers**
- **`_scene_cast(bible, scene_id, subjects, beats, limit)`** — internal helper resolving the `(ref, name)` cast actually present in a scene, prioritizing explicit subjects, then persisted cast/blocking/shot anchors/beat speakers, falling back to all characters only if none named; capped at `limit`.
- **`_screen_direction(cast)`** — internal helper producing a 180-degree-rule prompt clause pinning each character to a fixed screen side for cross-panel/time consistency.
- **`Beat` (BaseModel)** — Pydantic model for one storyboard beat with `action`/`emotion`/`dialogue`/`speaker` fields.
- **`_beat_fields(beat)`** — internal helper normalizing a beat (Beat model, string, or dict with alias keys) to a `(action, emotion, dialogue, speaker)` tuple.
- **`_scene_beats(bible, scene_id, beats, panels)`** — internal helper returning exactly `panels` beat entries from explicit beats, else scene shot intents, else a generic establishing/action/reaction arc.
- **`mv_generate_microshot(user_id, project_id, scene_id, beats, subjects, panels, prompt)`** — internal core func rendering an N-panel storyboard strip in ONE image call (conditioned on establish plate + character/prop sheets) with a QC loop, persisting `microshot_uri`, the resolved cast ids, and `qc_*` to the scene.
- **`mv_start_scene_video(user_id, project_id, scene_id, beats, duration_seconds, audio, wait)`** — internal core func animating a scene's micro-shot into one continuous Omni reference-to-video clip (per-window beats, animal-speech muting via `imagegen.non_speaking_characters`, screen-direction, audio/silent handling), persisting job+prompt+refs for auto-retry and optionally blocking (≤150s) until done.
- **`mv_get_scene_video(user_id, project_id, scene_id)`** — internal core func polling a scene's stateless reference-to-video job, saving the mp4 and recording `video_uri` on success, or auto-restarting the job (same inputs) up to `SCENE_VIDEO_MAX_RETRIES` on a transient upstream error.
- **`mv_generate_music(user_id, project_id, prompt, mood)`** — internal core func generating an instrumental-only Lyria 3 score themed to the project, saving it and recording `music_uri` in the bible.

**Character/prop import helpers**
- **`mv_import_character(user_id, project_id, name, description, image_name)`** — internal core func registering an already-uploaded image as a character reference sheet (no generation), replacing an existing same-name character's sheet if present.
- **`mv_update_character(user_id, project_id, character, change, prompt)`** — internal core func re-styling a character's reference sheet to change wardrobe/appearance while keeping identity, updating the character to point at the new sheet.
- **`mv_import_prop(user_id, project_id, name, description, image_name)`** — internal core func registering an uploaded prop image (no generation) as an extra scene reference, replacing an existing same-name prop if present.
- **`_prop_refs(bible)`** — internal helper returning `(ref_path, name)` for every uploaded prop with an on-disk reference image.

**MCP tool wrappers (thin `@mcp.tool()` exposing the core funcs, adding `resource_uri`/progress)**
- **`create_project(user_id, title, style_guide)`** — `@mcp.tool()` wrapper over `mv_create_project`.
- **`list_projects(user_id)`** — `@mcp.tool()` wrapper over `mv_list_projects`.
- **`get_project(user_id, project_id)`** — `@mcp.tool()` wrapper returning the full bible.
- **`generate_style_ref(user_id, project_id, ctx, prompt, description)`** — async `@mcp.tool()` wrapper over `mv_generate_style_ref` that emits `ctx.info` and adds a `resource_uri`.
- **`add_character(user_id, project_id, name, description, ctx, prompt)`** — async `@mcp.tool()` wrapper over `mv_add_character` (QC'd sheet) adding a `resource_uri`.
- **`establish_scene(user_id, project_id, scene_id, description, ctx, lighting, blocking, prompt)`** — async `@mcp.tool()` wrapper over `mv_establish_scene` adding a `resource_uri`.
- **`plan_scene(user_id, project_id, scene_id, shots)`** — `@mcp.tool()` wrapper over `mv_plan_scene` (film-grammar validation gate).
- **`generate_shot(user_id, project_id, shot_id, ctx, prompt)`** — async `@mcp.tool()` wrapper over `mv_generate_shot` reporting progress and adding a `resource_uri`.
- **`start_shot_video(user_id, project_id, shot_id, model, duration_seconds)`** — `@mcp.tool()` wrapper over `mv_start_shot_video`.
- **`get_shot_video(user_id, project_id, shot_id)`** — `@mcp.tool()` wrapper over `mv_get_shot_video`.
- **`generate_microshot(user_id, project_id, scene_id, ctx, beats, subjects, panels, prompt)`** — async `@mcp.tool()` wrapper over `mv_generate_microshot` reporting progress and adding a `resource_uri`.
- **`start_scene_video(user_id, project_id, scene_id, beats, duration_seconds, audio, wait)`** — `@mcp.tool()` wrapper over `mv_start_scene_video` (blocks by default until the clip renders).
- **`get_scene_video(user_id, project_id, scene_id)`** — `@mcp.tool()` wrapper over `mv_get_scene_video`.
- **`generate_music(user_id, project_id, ctx, prompt, mood)`** — async `@mcp.tool()` wrapper over `mv_generate_music` reporting progress and adding a `resource_uri`.
- **`review_asset(user_id, project_id, name, expects)`** — `@mcp.tool()` exposing the vision critic on demand: runs `imagegen.review_image` on a saved asset against the project's canonical refs (style ref + character sheets) and returns `{ok, score, issues, dims, resource_uri}`.
- **`import_character(user_id, project_id, name, description, image_name)`** — `@mcp.tool()` wrapper over `mv_import_character`.
- **`update_character(user_id, project_id, character, change, ctx, prompt)`** — async `@mcp.tool()` wrapper over `mv_update_character` emitting `ctx.info`.
- **`import_prop(user_id, project_id, name, description, image_name)`** — `@mcp.tool()` wrapper over `mv_import_prop`.
- **`list_project_assets(user_id, project_id)`** — `@mcp.tool()` enumerating a project's generated media as MCP `ResourceLink` blocks (movie:// URIs) so a client can fetch bytes without leaking file paths.
- **`get_help(topic)`** — `@mcp.tool()` returning the canonical in-chat help/slash-command guidance from `HELP_TOPICS`/`HELP_COMMANDS` (single source of truth for all clients).

**Resource & entrypoint**
- **`read_asset(user_id, project_id, name)`** — `@mcp.resource("movie://{user_id}/{project_id}/{name}")` templated resource returning a generated image's bytes on demand (path-sanitized), the "links, not bytes" read path.
- **`main()`** — entrypoint configuring logging and parsing `--http`/`--port`; runs Streamable HTTP on `0.0.0.0` when `--http` or `$PORT` is set, else stdio.

**Key module-level constants / env vars**
- `GEN_ROOT` — `generated/` directory root under the module dir.
- `HIFI_IMAGE_MODEL` (env `$HIFI_IMAGE_MODEL`, default `gemini-3.1-flash-lite-image`) — image model used for per-character insertions once cast ≥ 2.
- `QC_MAX_TRIES` (env `$QC_MAX_TRIES`, default 2, floored at 1) — total render+corrective attempts in every QC loop.
- `SCENE_VIDEO_MAX_RETRIES` (= 1) — auto-restart attempts for a transient scene-video failure at poll time.
- `mcp` — `FastMCP("movie-mcp", stateless_http=True, json_response=True, …)` with DNS-rebinding protection disabled (Cloud Run + IAM is the boundary).
- `LOG_LEVEL` (env, default `INFO`) — server log level for video-failure/retry warnings.
- `PORT` (env, default 9100) — HTTP port; presence forces HTTP transport bound to `0.0.0.0`.
- `HELP_COMMANDS` / `HELP_TOPICS` — canonical help/slash-command content served by `get_help`.

### `movie/movie_store.py`
_JSON-file-backed, strictly user-partitioned "story bible" store for the movie-generation pipeline, with atomic writes under a module lock._

- **`_sanitize(value, kind)`** — Reduces a string to safe filename characters (alnum/dash/underscore), raising TypeError if not a str and ValueError if nothing safe remains, blocking path traversal.
- **`_user_dir(user_id)`** — Returns the sanitized per-user data directory `DATA_ROOT/<user_id>`.
- **`_bible_path(user_id, project_id)`** — Returns the sanitized JSON path `DATA_ROOT/<user_id>/<project_id>.json` for a project.
- **`_new_id(length)`** — Returns a truncated `uuid.uuid4().hex[:length]` id.
- **`_atomic_write(path, bible)`** — Writes the bible JSON to a same-directory temp file (with flush + fsync) then `os.replace`s it into place, cleaning up the temp file in a finally block (side effect: creates parent dirs).
- **`_load(user_id, project_id)`** — Reads and returns a user's bible from disk, raising KeyError if the file doesn't exist for that user.
- **`_persist(bible)`** — Stamps `updated` with the current epoch time and atomically writes the bible to its user/project path, returning the bible.
- **`create_project(user_id, title, style_guide)`** — Under the lock, generates a collision-checked project_id and creates + persists a fresh empty bible owned by that user, returning the full bible.
- **`get_project(user_id, project_id)`** — Under the lock, loads and returns the full bible, raising KeyError if not found for that user.
- **`list_projects(user_id)`** — Under the lock, returns summaries (`project_id`, `title`, `shots` count, `updated`) for the user's projects (empty list if the user dir is missing), skipping unreadable/corrupt files.
- **`update_style(user_id, project_id, style_guide)`** — Under the lock, sets the bible's `style_guide` and persists, returning the bible.
- **`set_style_ref(user_id, project_id, uri)`** — Under the lock, sets the global `style_ref` image URI (art-style/palette anchor) and persists, returning the bible.
- **`set_music(user_id, project_id, uri)`** — Under the lock, sets the project's `music_uri` (instrumental score) and persists, returning the bible.
- **`add_character(user_id, project_id, name, desc, refs, seed)`** — Under the lock, adds a character under a collision-checked 6-char char_id (with name/desc/refs/seed) and persists, returning the char_id.
- **`update_character(user_id, project_id, char_id, patch)`** — Under the lock, merges `patch` into an existing character and persists, returning the character, raising KeyError if the char_id is absent.
- **`add_location(user_id, project_id, name, desc, refs)`** — Under the lock, adds a location under a collision-checked 6-char loc_id and persists, returning the loc_id.
- **`update_prop(user_id, project_id, prop_id, patch)`** — Under the lock, merges `patch` into an existing prop and persists, returning the prop, raising KeyError if the prop_id is absent.
- **`add_prop(user_id, project_id, name, desc, refs)`** — Under the lock, adds a prop under a lazily-created `props` map (for backward compatibility) with a collision-checked 6-char prop_id and persists, returning the prop_id.
- **`set_scene(user_id, project_id, scene_id, location_id, lighting, blocking, establish_uri)`** — Under the lock, upserts (fully overwrites) a scene record (blocking defaults to `{}`) and persists, returning the bible.
- **`add_shot(user_id, project_id, shot)`** — Under the lock, appends a shot (assigning a collision-checked 6-char shot_id if missing) and persists, returning the shot_id.
- **`update_shot(user_id, project_id, shot_id, patch)`** — Under the lock, merges `patch` into the matching shot (guarding its id against clobbering) and persists, returning the shot, raising KeyError if not found.
- **`update_scene(user_id, project_id, scene_id, patch)`** — Under the lock, merges `patch` into an existing scene (creating a bare one if missing) preserving untouched fields, and persists, returning the scene.
- **`set_final_movie(user_id, project_id, uri)`** — Under the lock, sets the bible's `final_movie` URI and persists, returning the bible.
- **`check(label, condition)`** — Test helper (in `__main__`) that prints PASS/FAIL and flips the module `passed` flag on failure.

### `movie/film_grammar.py`
_Pure-logic (no I/O) film-grammar / continuity validator that checks a ShotPlan against classical cinematography rules and returns a list of Violations._

- **`Camera`** (BaseModel) — Fields: `type` (shot type str), `over` (char_id shot over, for OTS), `height` (low/eye/high), `lens` (default "50mm"), `angle_deg` (0-359 bearing), `move`, `vertical` (up/level/down).
- **`Shot`** (BaseModel) — Fields: `id`, `scene`, `subject` (char_id), `camera` (Camera), `anchors` (list), `side` (left/center/right screen side), `faces` (left/right/center), `movement` (left/right/none), `intent`.
- **`ShotPlan`** (BaseModel) — Fields: `scene`, `shots` (list[Shot]), `known_anchors` (anchors that exist in the bible).
- **`Violation`** (BaseModel) — Fields: `rule`, `severity` (error/warn), `shot_ids` (list), `message`.
- **`_circular_diff(a, b)`** — Returns the smallest absolute difference between two bearings on a 360° circle.
- **`validate_plan(plan)`** — Returns all continuity violations found in the plan (empty if no shots), running every rule below:
  - **R7 establish-first (error)** — Flags if the first shot's camera type is not an establishing/wide type (`establishing`/`wide`/`ls`/`ews`).
  - **R1 180° line / screen-side (error)** — Flags a subject flipping left↔right screen side without a preceding neutral/cutaway shot (`center` exempt), re-baselining on the new side afterward.
  - **R3 eyeline (error)** — Flags a screen-left subject not facing right, or a screen-right subject not facing left.
  - **R4 30° rule / jump cut (error)** — Flags consecutive same-subject shots whose camera bearing differs by <30° while keeping the same shot type.
  - **R14 reciprocal eyeline height (error)** — For mutual OTS shot pairs (each shooting over the other's subject), flags vertical angles that aren't opposite (up/down) or both level.
  - **R5 screen-direction (warn)** — Warns when a subject's movement direction reverses without an intervening neutral/cutaway.
  - **R19 lens consistency (warn)** — Warns (across all shots) when more than one distinct lens is used within the scene.
  - **anchors (error)** — Flags any shot referencing anchors not in `plan.known_anchors`.
- **`_valid_plan()`** — Demo helper returning a rule-compliant three-shot kitchen ShotPlan (establishing + reciprocal OTS pair).
- **`_invalid_plan()`** — Demo helper returning a diner ShotPlan that deliberately triggers R7, R1, R4, R19, and an anchors error.
- **`_summarize(name, plan)`** — Demo helper that validates a plan, prints each violation plus error/warn counts, and returns `(errors, warns)`.

### `movie/imagegen.py`
_Nano-banana (Gemini image) helper providing text-to-image and reference-conditioned image composition plus a vision-critic QC loop for the film pipeline._

- **`_client()`** — lazily creates and caches a singleton Vertex AI `genai.Client` bound to the configured project/location so the module can import without credentials.
- **`_extract(resp)`** — walks a GenAI response's candidates/parts, returns the first inline image `(bytes, mime_type)`, or raises `ValueError` with the `finish_reason` and any text when no image is present.
- **`save_bytes(data, out_dir, stem, mime)`** — writes image bytes to `out_dir` with a mime-derived extension and a monotonic `_1`, `_2` suffix to avoid overwriting, returning the `Path`.
- **`_call(contents, model, attempts)`** — invokes `generate_content` on the image model (default `NANO_BANANA_MODEL`/`gemini-3.1-flash-lite-image`) with one transient retry on empty/blocked responses, returning extracted `(bytes, mime)`.
- **`generate_image(prompt, aspect_ratio, model)`** — text-to-image call (character sheets, establishing frames) that appends the aspect ratio to the prompt and delegates to `_call`, returning `(bytes, mime)`.
- **`review_image(image_path, expects, refs)`** — the vision film-editor critic calling `QC_MODEL` (default `gemini-3.5-flash`) that judges the render against optional reference images across dimensions (prompt adherence, character identity, style, framing, anatomy, extra/missing, text, lighting) and returns `{ok, score, issues, dims}`, failing open (ok=true) on any error so it never crashes generation.
- **`qc_check(image_path, expects)`** — back-compat shim wrapping `review_image` to return just `(ok, issues)`.
- **`non_speaking_characters(cast, style_guide)`** — uses the QC/critic model to determine which cast members are realistic non-anthropomorphic animals that cannot speak human dialogue, returning `[]` (fail-open) if the style is a talking-animal cartoon or on any error.
- **`compose_image(prompt, ref_paths, model)`** — reference-images-plus-text composition (keyframes conditioned on establishing frame + character sheets + sibling frame) that loads each ref as an image `Part`, appends the prompt, and delegates to `_call`, returning `(bytes, mime)`.

### `movie/videogen.py`
_Async video generation helper for two verified backends — Omni (global, default) and Veo (us-central1) — using a stateless start/poll job pattern with upstream error extraction._

- **`_omni_duration(duration_seconds)`** — clamps a requested duration to 1–10s since Omni rejects durations over 10s.
- **`_client(location)`** — lazily creates and caches a Vertex AI `genai.Client` per location (Veo uses us-central1, Omni uses global).
- **`_veo_start(prompt, model, image_path, aspect_ratio, duration_seconds)`** — starts a Veo `generate_videos` long-running op (720p, audio on, optional image-to-video), returning `{job_name, backend:"veo", status:"running"}`.
- **`_veo_poll(job_name, save_path)`** — re-queries the Veo operation by name and, when done, returns the video URI (or writes bytes to `save_path`), extracting the failure `message`/no-video reason into an `error` field and logging a warning on failure.
- **`_img_part(path)`** — builds a base64-encoded image content dict (with png/jpeg mime) for an Omni interactions input list.
- **`_omni_start(prompt, image_path, aspect_ratio, duration_seconds)`** — starts a background Omni `interactions.create` job, routing to `text_to_video` or (with an image) `image_to_video` via `VideoConfig.task`, returning `{job_name, backend:"omni", status:"running", task}`.
- **`_omni_start_refs(prompt, ref_image_paths, aspect_ratio, duration_seconds)`** — starts a background Omni `reference_to_video` job where multiple images act as creative guides (storyboard, character sheets, plate), returning the job handle plus the ref count.
- **`_omni_reason(it)`** — best-effort extraction of an Omni failure reason from several possible SDK attributes or a text content part (content/safety blocks), returning `''` if none found.
- **`_omni_poll(job_name, save_path)`** — re-queries the Omni interaction by id, saves the returned video part to disk on completion, and otherwise reports `running` or extracts an `error` reason (failed status, or "completed but no video" = likely safety/content filter) with a warning log.
- **`start_video(prompt, model, image_path, aspect_ratio, duration_seconds)`** — dispatch entry point that starts a Veo job if the model name begins with `veo`, otherwise an Omni job.
- **`start_reference_video(prompt, ref_image_paths, aspect_ratio, duration_seconds)`** — Omni-only entry point that starts a reference-to-video job from guiding images (Veo has no reference-to-video mode).
- **`poll_video(job_name, backend, save_path)`** — dispatch poller that calls `_veo_poll` or `_omni_poll` by backend to rehydrate the job by name.

### `movie/musicgen.py`
_Lyria 3 (Gemini music) helper that generates an instrumental score from a text prompt, mirroring the image model's shape._

- **`_client()`** — lazily creates and caches a singleton Vertex AI `genai.Client` (global location) so the module imports without credentials.
- **`generate_music(prompt, model)`** — calls `generate_content` on `LYRIA_MODEL` (default `lyria-3-pro-preview`) with `response_modalities=["AUDIO","TEXT"]`, returning the first inline audio `(bytes, mime_type)` or raising `ValueError` if none.
- **`save_music(data, out_dir, stem, mime)`** — writes audio bytes to `out_dir` with a mime-derived extension (mp3/wav/audio) and a monotonic suffix to avoid overwriting, returning the `Path`.
- **`__main__`** — smoke test (needs creds) that generates a warm cinematic piano/strings clip, saves it under `generated/samples`, and prints `PASS`.

---

## 3. ADK agents & studios

### `adk_agent/agent.py`
_Defines an ADK Gemini agent that reaches the learn-mcp server's image tools over Streamable HTTP._

- **`module-level setup`** — builds `root_agent` as an `Agent(name="mcp_image_agent", model="gemini-2.5-flash")` with a creative-assistant instruction, whose only tools come from an `McpToolset` connected via `StreamableHTTPConnectionParams` to `MCP_URL` (default `http://localhost:9000/mcp`) with a 120s timeout, forcing Vertex mode (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`, location `global`) and no auth headers.

### `adk_agent/run_test.py`
_Drives the learn-mcp ADK agent end-to-end with two prompts and saves the streamed transcript as blog evidence._

- **`out(*a)`** — prints a line (flushed) and appends it to the in-memory `_log` list.
- **`ask(runner, session_id, text)`** — sends one user message and streams the run, printing each event's function calls, function responses (trimmed to 400 chars), and agent text.
- **`main()`** — creates an `InMemoryRunner` + session, asks an add-tool question then the banana-astronaut image request, and writes the collected log to `transcripts/adk_run.txt`.
- **`module-level setup`** — imports `root_agent` from `adk_agent/agent.py`; sets `APP="mcp_demo"`, `USER="learner"`, and runs `main()` under `asyncio.run` when executed as a script.

### `adk_agent/skill_mcp_demo.py`
_Demonstrates composing four filesystem Skills (know-how) with the learn-mcp image MCP tools (capability) in one ADK agent._

- **`ask(runner, session_id, text)`** — sends one user message and streams the run, printing tool calls, tool responses (trimmed to 300 chars), and agent text.
- **`main()`** — creates an `InMemoryRunner` + session and issues two requests (a coffee-brand logo, a sneaker Instagram post) so two different skills fire via progressive disclosure.
- **`module-level setup`** — loads four skills (`poster-designer`, `social-post`, `logo-maker`, `photo-editor`) via `load_skill_from_dir`, builds an `McpToolset` over `StreamableHTTPConnectionParams` to `MCP_URL` (default `http://localhost:9000/mcp`, 120s timeout), and wires `root_agent` as `Agent(name="creative_agent", model="gemini-2.5-flash")` with tools `[SkillToolset(skills=...), mcp_tools]` under Vertex mode.

### `creative_studio/agent.py`
_A hosted (selectable in `adk web`) ADK agent that pairs four self-contained Skills with the learn-mcp image tools._

- **`module-level setup`** — loads the four skills (`poster-designer`, `social-post`, `logo-maker`, `photo-editor`) from this package's own `skills/` dir, builds an `McpToolset` over `StreamableHTTPConnectionParams` to `MCP_URL` (default `http://localhost:9000/mcp`, 120s timeout), and defines `root_agent` as `Agent(name="creative_studio", model="gemini-2.5-flash")` with tools `[SkillToolset(skills=...), mcp_tools]` under Vertex mode (location `global`), no auth headers.

### `movie_agent/agent.py`
_Defines the `movie_director` ADK agent that drives the movie-mcp film-production pipeline using three Skills plus the movie MCP tools._

- **`_mcp_headers()`** — returns a Bearer `Authorization` header for IAM-protected Cloud Run by using `MCP_BEARER_TOKEN` or minting a Google ID token from the metadata server for `MCP_AUDIENCE`, else `{}` for local dev.
- **`_instruction(ctx)`** — dynamic instruction provider that injects the runtime user's LDAP id (falling back to `director1`) into the base instruction so every tool call is scoped to that user's workspace.
- **`module-level setup`** — loads three skills (`script-developer`, `film-director`, `film-editor`) from `../movie/skills`, builds an `McpToolset` over `StreamableHTTPConnectionParams` to `MCP_URL` (default `http://localhost:9100/mcp`, 180s timeout, headers from `_mcp_headers()`), and defines `root_agent` as `Agent(name="movie_director", model="gemini-3.5-flash", instruction=_instruction)` with tools `[SkillToolset(skills=...), movie_tools]` under Vertex mode.

### `movie_agent/run.py`
_CLI driver that sends one natural-language prompt to the `movie_director` agent and streams its tool calls/responses._

- **`main(prompt)`** — creates an `InMemoryRunner` + session and streams the run, printing each function call (with args truncated to 60 chars), response (160 chars), and agent text (400 chars).
- **`module-level setup`** — imports `root_agent` from `movie_agent/agent.py`, sets `APP/USER="movie_director"/"director1"`, and runs `main()` with `sys.argv[1]` (or a default witch-and-cat prompt) under `asyncio.run`.

### `movie_studio/app.py`
_FastAPI web app that hosts the `movie_director` agent with persisted per-user sessions, streams turns over SSE, and proxies generated media bytes to the browser._

- **`_clean_user(user)`** — sanitizes an LDAP into a safe alnum/`-`/`_` workspace id used as both the ADK session user_id and the movie_store user_id.
- **`_session_meta(s)`** — builds a compact session dict (`id`, `title` from state, `created` timestamp) for the sessions list.
- **`_list_metas(user_id)`** — lists all persisted sessions for a user and returns their metas sorted oldest-first.
- **`_safe_component(value)`** — strips a path component to alnum/`-`/`_`, raising `ValueError` if empty (path-traversal guard).
- **`_safe_name(name)`** — reduces a filename to its basename and rejects empty or dotfile names.
- **`_to_asset_url(value)`** — resolves a `movie://` URI or a raw `.../generated/<user>/<project>/<name>` path into `(/asset/... url, filename)`, or `None` if not a local media reference.
- **`_collect_media(result)`** — scans known media-URI keys in a tool-result dict and returns deduped renderable media entries (`kind`, `url`, `name`).
- **`_parse_tool_result(response)`** — decodes ADK's `{'content':[{'text':'<json>'}]}` MCP wrapper into a merged dict payload (or returns the dict/`{}`).
- **`_sse(event)`** — formats a dict as a Server-Sent Events `data:` line.
- **`_short(v, n)`** — stringifies (JSON if needed) and truncates a value to `n` chars for compact display.
- **`_arg_preview(args)`** — produces a compact, trimmed view of tool arguments for the activity panel.
- **`_result_summary(result)`** — builds a one-line summary of selected result keys (ids, status, qc, errors) for the activity panel.
- **`_run_turn(user_id, adk_sid, message)`** — async generator that ensures/creates the session, runs the agent turn, and yields SSE events for tool chips, activity steps, media, text, and errors, ending with `done`.
- **`chat_stream(session, message, user)`** — GET `/chat/stream` route returning a `StreamingResponse` of `_run_turn` as an SSE (`text/event-stream`) chat stream.
- **`_mcp_call(tool, args)`** — opens a direct Streamable HTTP MCP client session (with the same Bearer auth) to invoke a movie-mcp tool without going through the LLM, returning its structured/parsed result.
- **`upload(request, project, name, user, kind, description)`** — POST `/upload` route that saves a raw-body character/prop image to the project's media dir and registers it via `import_character`/`import_prop`, with size/type validation and error handling.
- **`get_asset(user, project, name, download)`** — GET `/asset/{user}/{project}/{name}` media-proxy route serving a generated file (inline or as attachment) with a no-cache header, guarding path safety and 400/404.
- **`list_assets(user, project)`** — GET `/assets/{user}/{project}` route listing a project's media files as `{kind, name, url}` entries.
- **`list_sessions(user)`** — GET `/sessions` route returning all persisted sessions for a user (oldest first).
- **`create_session(user, title)`** — POST `/sessions` route creating a new titled session (auto-numbered) for the user and returning its meta.
- **`delete_session(sid, user)`** — DELETE `/sessions/{sid}` route removing a session and its transcript from the persistent store.
- **`session_history(sid, user)`** — GET `/sessions/{sid}/history` route replaying a session's transcript into text + media events so a reload restores it.
- **`index()`** — GET `/` route returning the SPA's `static/index.html`.
- **`module-level setup`** — sets Vertex/MCP env defaults, imports the shared `root_agent` and `_mcp_headers` from `movie_agent/agent.py`, wires a FastAPI `app` with a `DatabaseSessionService` (SQLite `sessions.db` via `SESSION_DB_URL`) and a persistent `Runner(app_name="movie_director")`, mounts `/static`, and on `__main__` serves via uvicorn on `PORT` (default 8090).

---

## 4. Ad-hoc scripts & tooling

### `movie/test_local.py`
_Local end-to-end smoke test driving the movie pipeline's core functions directly (using real nano-banana) to prove user scoping, reference sheets, blocking, the film-grammar validation gate, keyframe composition, and cross-user isolation._

- **`check(label, cond)`** — prints `PASS`/`FAIL` for a labeled condition and asserts it, halting the test on failure.
- **`__main__` flow** — exercises `mv_create_project`, two `mv_add_character` reference sheets, `mv_establish_scene`, a VALID `mv_plan_scene` (asserts 0 errors and persistence) and an INVALID plan (asserts errors>0 and rejection), two `mv_generate_shot` keyframes composed from anchors, cross-user isolation (empty project list and a `KeyError` on foreign `store.get_project`), and prints the final bible snapshot.

### `movie/test_video.py`
_End-to-end smoke test of the real async Veo video integration via the movie server, starting an image-to-video job from an existing keyframe and polling it statelessly by name._

- **`__main__` flow** — loads the most recent `creator1` project that has a keyframed shot (requires `test_local.py` first), calls `mv_start_shot_video` (Veo, 6s) to get an upstream job name, polls `mv_get_shot_video` by name up to ~6 minutes until `done`/`error`, asserts completion with a `video_uri`, and confirms the bible durably recorded `status=="video_done"` with a `video_uri`.

### `movie/cinderella.py`
_Ad-hoc pipeline driver script that generates an 8-scene "Ella" (Cinderella) story through the movie pipeline with a deterministic director, locking Ella/Fairy Godmother/Prince as character sheets for identity consistency._

- **`render_scene(i, scene, setting, chars, action)`** — Establishes a people-free set plate, builds a wide center shot with establish+character anchors, validates it via `mv_plan_scene`, and renders the keyframe, raising `RuntimeError` if validation fails.
- **`render_with_retry(i, scene, setting, chars, action)`** — Wraps `render_scene` in a retry-once loop, returning `(scene, uri, refs, err)` and swallowing exceptions so a flaky scene is skipped rather than crashing the run.
- **`__main__ flow`** — Creates the "Ella" project, casts three character sheets, generates a global style reference, then fans out the 8 `BEATS` across a 4-worker `ThreadPoolExecutor` (via `as_completed`) with retry, and prints the successfully rendered keyframes in story order.

### `movie/witch_broom.py`
_Ad-hoc pipeline driver script that generates an original 10-frame witch-and-friends broomstick story through the movie pipeline, casting six generic (no-IP) character sheets so only descriptions reach the image model._

- **`render_scene(scene, setting, chars, action)`** — Establishes the set plate, builds a wide center shot anchored on the establish plate plus all present characters, validates via `mv_plan_scene`, and renders the keyframe, raising `RuntimeError` on validation failure.
- **`render_with_retry(beat)`** — Unpacks a `beat` tuple and retries `render_scene` once, returning `(scene, uri, refs, err)` and capturing any exception so failed frames are skipped.
- **`__main__ flow`** — Creates "The Crowded Broom" project, casts witch/cat/dog/bird/frog/dragon character sheets, generates a global style reference, then renders the 10 `BEATS` in parallel via `ThreadPoolExecutor.map` with retry, and prints the rendered frames in story order.

### `blog/build_docs.py`
_Renders the blog markdown files to self-contained `docs/*.html` pages that match the GitHub Pages styling, share a brand nav, and support Mermaid.js diagram rendering._

- **`PAGES` config** — An ordered dict mapping each page slug to its `(source markdown, <title>, short nav label, sub-label)`, where the ordering also defines the nav order.
- **`nav(active)`** — Builds the shared "The Agentic Studio" header HTML, emitting a nav link per page in `PAGES` and marking the given `active` slug as the current (non-clickable) item.
- **`render(slug)`** — Reads the page's source markdown, converts it to HTML (tables/fenced-code/sane-lists extensions), rewrites fenced `mermaid` code blocks into `<pre class="mermaid">`, and writes the styled, nav-prefixed page (appending the Mermaid script only if diagrams exist) to `docs/<slug>.html`.
- **`_mermaid(m)`** — Inner regex-substitution handler in `render` that HTML-unescapes a captured mermaid code block and strips `<br/>` line-breaks so the browser gets raw single-line diagram source.
- **`__main__ flow`** — Iterates over every slug in `PAGES` and calls `render` to build all the HTML pages.

---

## 5. Package markers

These are one-line files that mark a directory as a Python package (they contain only a module
docstring or are empty): `adk_agent/__init__.py`, `creative_studio/__init__.py`,
`movie_agent/__init__.py`. They define no functions.

---

_Generated by reviewing every `.py` file in the repository. To regenerate after code changes, re-read
the changed file and update its section._
