# How a Cinderella movie comes together — sequence diagram (with inputs/outputs)

Every step annotated with the concrete **IN** (arguments) and **OUT** (returned data), and what
gets written where. Renders on GitHub / mermaid.live.

```mermaid
sequenceDiagram
    autonumber
    actor D as Director (agent/human)
    participant S as Movie MCP Server
    participant B as Bible (movie_store, per-user JSON)
    participant G as FilmGrammar
    participant NB as nano-banana (image)
    participant V as Veo (video, async)
    participant FS as Storage (files/GCS)

    %% ---------- create project ----------
    D->>S: create_project(user_id, title="Cinderella", style_guide)
    S->>B: write bible {user_id, project_id, style, characters:{}, scenes:{}, shots:[]}
    B-->>S: project_id
    S-->>D: {project_id}

    %% ---------- cast: character sheets (identity anchors) ----------
    rect rgb(245,244,252)
    Note over D,FS: CAST — one sheet per character, reused in every scene
    loop for name in [Cinderella, Fairy Godmother, Prince]
        D->>S: add_character(user_id, project_id, name, description)
        S->>NB: IN prompt="character sheet: {name}. {description}. front+3/4, neutral bg, style"
        NB-->>S: OUT PNG bytes (~1 MB)
        S->>FS: write generated/{user}/{project}/char_{name}.png
        S->>B: characters[char_id] = {name, desc, refs:[path]}
        S-->>D: {char_id, ref_uri}
    end
    end

    %% ---------- per-scene loop ----------
    rect rgb(244,247,252)
    Note over D,FS: PER SCENE (hearth, mockery, letter, garden, fairy, transform, ball, midnight)
    loop each of 8 beats
        D->>S: establish_scene(user_id, project_id, scene_id, description=setting, lighting)
        S->>NB: IN prompt="establishing wide of SET only, EMPTY (no people): {setting}"
        NB-->>S: OUT plate PNG (people-free)
        S->>FS: write establish_{scene}.png
        S->>B: scenes[scene] = {establish_uri, lighting, blocking}
        S-->>D: {establish_uri}

        D->>S: plan_scene(user_id, project_id, scene, shots=[{id,subject,camera,anchors,side,faces,intent}])
        S->>B: read known_anchors = [establish:{scene}, char:{ids}, frame:{done shots}]
        S->>G: IN ShotPlan{scene, shots, known_anchors}
        G-->>S: OUT violations[] = [{rule,severity,shot_ids,message}]
        alt any severity=="error"
            S-->>D: {errors>0, persisted:false, violations}   %% nothing rendered
        else no errors
            S->>B: append shots (status:"planned")
            S-->>D: {errors:0, persisted:true, violations:[warns]}
        end

        D->>S: generate_shot(user_id, project_id, shot_id)
        S->>B: read shot + resolve anchors → char_paths[] (sheets) + set_paths[] (plate)
        S->>NB: IN refs=[char sheets… , plate] + prompt="identity from sheets; set from plate; camera …; intent …"
        NB-->>S: OUT keyframe PNG
        S->>FS: write kf_{shot}.png
        S->>B: shots[shot].keyframe_uri, status:"keyframed"
        S-->>D: {keyframe_uri, refs_used}

        D->>S: start_shot_video(user_id, project_id, shot_id, model, duration_seconds)
        S->>B: read shot.keyframe_uri
        S->>V: IN generate_videos(model="veo-3.1-fast-generate-001", image=keyframe, prompt, config{aspect,duration,720p,audio})
        V-->>S: OUT operation.name  (the job handle)
        S->>B: shots[shot].video_job=name, status:"video_running"
        S-->>D: {job_name, backend:"veo", status:"running"}

        loop poll by name (stateless)
            D->>S: get_shot_video(user_id, project_id, shot_id)
            S->>B: read shot.video_job
            S->>V: IN operations.get(GenerateVideosOperation(name=job))
            V-->>S: OUT {done:false} … {done:true, video_bytes|uri}
        end
        S->>FS: write vid_{shot}.mp4
        S->>B: shots[shot].video_uri, status:"video_done"
        S-->>D: {status:"done", video_uri, size_bytes}
    end
    end

    %% ---------- assemble (planned) ----------
    D->>S: assemble_movie(user_id, project_id)   %% planned
    S->>FS: IN read [vid_hearth.mp4 … vid_midnight.mp4]
    S->>FS: OUT ffmpeg concat + score + titles → final_movie.mp4
    S->>B: final_movie = uri
    S-->>D: {final_movie_uri}
```

## Input/output cheat-sheet (per tool)

| Tool | IN (args) | External call | OUT (returned) | Writes |
|---|---|---|---|---|
| `create_project` | user_id, title, style | — | project_id | Bible (new) |
| `add_character` | user_id, project_id, name, description | nano-banana (text→img) | char_id, ref_uri | sheet PNG + Bible.characters |
| `establish_scene` | user_id, project_id, scene, setting, lighting | nano-banana (text→img, **no people**) | establish_uri | plate PNG + Bible.scenes |
| `plan_scene` | user_id, project_id, scene, shots[] | FilmGrammar.validate_plan | errors, persisted, violations[] | Bible.shots (only if valid) |
| `generate_shot` | user_id, project_id, shot_id | nano-banana (**refs+text→img**) | keyframe_uri, refs_used | keyframe PNG + Bible.shot |
| `start_shot_video` | user_id, project_id, shot_id, model, duration | Veo generate_videos (async LRO) | job_name, status | Bible.shot (video_job) |
| `get_shot_video` | user_id, project_id, shot_id | Veo operations.get(name) | status, video_uri, size | mp4 + Bible.shot (video_uri) |
| `assemble_movie` *(planned)* | user_id, project_id | ffmpeg | final_movie_uri | final.mp4 + Bible |

## Data that flows (the payloads)
- **Text prompts** → nano-banana / Veo (built from style_guide + setting + camera + intent).
- **Reference images (file paths)** → nano-banana for keyframe composition (character sheets = identity, plate = set).
- **A keyframe PNG path** → Veo as the image-to-video seed.
- **A job name (string)** → the only handle for the async video; carried in the tool result, polled later.
- **URIs (not bytes)** → returned to the Director and stored in the Bible; the heavy media stays in Storage.

## State layers (who remembers what)
| Layer | Holds | Scope |
|---|---|---|
| Bible (`movie_store`) | project, characters, scenes, shot statuses + URIs | **per user_id** (projects not shared) |
| Storage (files/GCS) | sheets, plates, keyframes, shot videos, final cut | project folder |
| Veo (upstream) | in-flight render jobs | job name |
| MCP server | **nothing** (stateless) | — |

## Why this yields a coherent film
- **Consistency:** every `generate_shot` re-conditions on the *same character sheets* → Cinderella
  looks the same across all 8 scenes even as wardrobe/setting change; the plate is people-free so
  identity has a single source of truth.
- **Correctness gate:** `plan_scene` validates film grammar (180°, eyeline, 30°, establish-first,
  anchors) *before* any render — bad plans are rejected, not drawn.
- **Async/scale:** video polled *by job name* → the MCP server is stateless; state lives in the
  Bible (per-user), Storage (media), and Veo (jobs).
```
