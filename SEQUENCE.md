# learn-mcp — end-to-end sequence diagram

The full flow of a request through the system: an agent (with Skills) calling the MCP server,
which calls a Gemini image model, saves the result, and returns a link the client reads on
demand. Renders on GitHub, in VS Code (Mermaid preview), or at <https://mermaid.live>.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant H as Host / Agent<br/>(Gemini LLM)
    participant SK as Skills runtime<br/>(SkillToolset, in-agent)
    participant C as MCP Client
    participant S as MCP Server<br/>(learn-mcp)
    participant V as Vertex AI<br/>(nano-banana)
    participant FS as Storage<br/>(generated/ or GCS)

    %% ---- Session setup (once per connection) ----
    rect rgb(244,247,252)
    Note over C,S: Session setup — handshake & capability negotiation
    C->>S: initialize (protocolVersion, client capabilities)
    S-->>C: serverInfo + capabilities {tools, resources, prompts}
    C->>S: notifications/initialized
    C->>S: tools/list
    S-->>C: tool schemas (generate_image incl. model enum, edit_image, add, …)
    end

    %% ---- User request → Skill (know-how) loads in the agent runtime ----
    U->>H: "Design a jazz poster — use the pro model"
    rect rgb(245,244,252)
    Note over H,SK: Skills load into the AGENT's own runtime (not the server)
    H->>SK: load_skill("poster-designer")  (L2 instructions)
    SK-->>H: workflow instructions
    opt recipe needed
        H->>SK: load_skill_resource("references/prompt_recipe.md")  (L3)
        SK-->>H: prompt recipe
    end
    Note over H: LLM crafts the image prompt per the skill,<br/>and picks model = "gemini-3-pro-image"
    end

    %% ---- Tool call → model → storage → link back ----
    H->>C: generate_image(prompt, aspect_ratio="4:5", model="gemini-3-pro-image")
    C->>S: tools/call generate_image { … }
    loop while working (~12s)
        S--)C: notifications/progress (0.1 → 0.7 → 1.0)
    end
    S->>V: generate_content(model, contents=prompt)
    alt image returned
        V-->>S: image bytes (PNG)
        S->>FS: save gen.png
        FS-->>S: path
        S-->>C: result { resource_uri:"image://gen.png", size_bytes, model }  ← link, NOT bytes
        C-->>H: structured result (small JSON)
        H-->>U: "Here's your poster: image://gen.png" + headline & caption
    else generation failed
        V-->>S: error / no image
        S-->>C: result { isError: true, content:"…" }
        C-->>H: error the model can read
        H-->>U: explains and offers to retry
    end

    %% ---- On-demand: fetch the actual pixels only when needed ----
    opt host/UI needs the pixels — to DISPLAY or SAVE (not for the model)
        C->>S: resources/read image://gen.png
        S->>FS: read gen.png
        FS-->>S: bytes
        S-->>C: blob (base64, image/png)
        C-->>U: rendered / saved image  (bytes go to screen/disk, NOT into the LLM context)
    end
    opt only if a step needs the MODEL to SEE the image (e.g. vision critique)
        Note over C,H: host chooses to pass the fetched bytes to the LLM →<br/>THEN (and only then) they enter the context window, once
    end

    %% ---- Auth (only when the server is hosted over HTTP) ----
    Note over C,S: Hosted over Streamable HTTP → per-session Mcp-Session-Id
    Note over H,V: Boundary 1: user token → server (who you are).<br/>Boundary 2: server's own identity → Vertex (may call the model). Never mixed.
```

## Legend / notes
- **Solid arrow →** request; **dashed arrow ⇠** response; **open async arrow ⇢)** one-way
  notification (progress).
- **Skills run in the agent's runtime**, so `load_skill` / `load_skill_resource` never touch the
  MCP server — the Skill only decides *how*, then calls the MCP tool for the *what*.
- **Only a `resource_uri` crosses back** in the tool result (~100 tokens); the image bytes travel
  to the **client/host** only on demand via `resources/read`. Resources are *app-controlled*, so
  those bytes reach the **LLM's context only if the host explicitly feeds them to the model**
  (e.g. a vision step) — for display/save they never do. Inlining bytes in the tool result, by
  contrast, puts them in context on **every** call.
- **`model` is chosen per call** (enum in the tool schema); adding a model is a one-line change to
  the server's `ImageModel` Literal.
- **stdio vs HTTP:** over stdio there's no session id (one subprocess per client); over Streamable
  HTTP the server issues an `Mcp-Session-Id` and the two auth boundaries apply.
