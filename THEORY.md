# MCP, explained clearly — with examples

A plain-English but technically complete guide to the **Model Context Protocol**, for
developers who know what an LLM and an API are. Every claim is backed by runnable code in this
repo: `server/learn_mcp_server.py` (an MCP server wrapping Google's **nano-banana** image
model), `client/raw_client.py` (proves the wire protocol), `client/remote_client.py` (talks to
the hosted server), and `adk_agent/` + `creative_studio/` (Gemini agents that use it).

> **Version note.** The published spec revision is `2025-06-18`, but MCP is *negotiated per
> connection*: our SDK actually agrees on `2025-11-25` at startup. Always trust the version the
> handshake returns, never a hardcoded one.

---

## 1. The one-sentence version

**MCP is a standard way to plug tools and data into any AI app — like USB-C, but for AI.**

Write a *server* once (say, "generate images"), and any MCP-aware app — Claude Desktop, a
Gemini agent, an IDE — can use it with no custom integration code.

---

## 2. Why not just call the API directly?

You often can, and sometimes should. The trade-off, using our image tool as the example:

- **Hardcode it into your app.** Simplest thing that works — perfect for *one tool in one app*.
  But it's trapped there; a second app means a rewrite in that app's function-calling dialect.
- **Wrap it in your own REST API.** Reusable, but every app *still* writes glue to tell its LLM
  the tool exists and translate tool-calls into HTTP. You moved the glue, didn't delete it.
- **MCP.** Write the server **once**. Every MCP host uses it with no glue, and discovery,
  progress, errors, and consent come *free* as part of the standard.

**Rule of thumb:** one tool, one app you own → hardcode it. The moment a capability must be
**reused across 2+ apps, shared, or discovered dynamically** → MCP pays for itself. This turns
the **M×N** integration explosion (apps × systems) into **M+N** (build each once).

---

## 3. REST vs MCP vs Skills — three ways to extend an AI app

These get conflated constantly but sit at **different layers** and **compose**:

- **REST API** = *the app calls a service.* A resource/verb web API. Not agent-aware — each app
  writes glue to expose it to its LLM.
- **MCP server** = *the agent calls a service.* An agent-native protocol (discovery, typed
  tools, structured I/O, even server→client requests). External to the agent; you run it.
- **Skill** = *the agent gains know-how it runs itself.* A `SKILL.md` (metadata → instructions →
  scripts/resources), disclosed progressively into the agent's **own runtime**. An open spec
  (`agentskills.io`), implemented today by both Claude products *and* **Google ADK**
  (`SkillToolset` / `load_skill_from_dir`).

> **MCP adds *connections* (to external systems); Skills add *procedures/knowledge* (how to do
> something).** A Skill can call MCP tools or REST APIs. Complementary, not rivals.

| Dimension | REST API | MCP server | Skill (Agent Skill spec) |
|---|---|---|---|
| What it is | resource/verb web API | tool/resource/prompt service (JSON-RPC) | folder of instructions + scripts (`SKILL.md`) |
| Where code runs | your server | your server (separate process) | inside the **agent's own runtime** |
| Who invokes it | your app code | the **agent** (model-decided) | the agent **runs it itself** |
| Agent-native (discovery, schema) | ❌ (you add glue) | ✅ built-in (`tools/list`) | ✅ (metadata in system prompt) |
| Hosting / ops | you host | stdio: none; HTTP: you host | none separate (rides the runtime) |
| Where credentials live | in your service | **centralized** in the server | in the **agent's environment** |
| Reuse across AI vendors | ✅ but with per-app glue | ✅ open protocol (Claude, Gemini/ADK, IDEs) | ✅ across runtimes implementing the spec |
| Server→client (progress/sampling/elicitation) | ❌ | ✅ (stateful) | ❌ (in-runtime) |
| Relative cost | hosting + glue | stdio ~free; HTTP hosting + ops | cheapest (no hosting; low context) |
| Best for | plain APIs; non-LLM consumers | shared/sensitive/external capabilities, **centralized secrets & quota** | **know-how**, workflows, helper scripts |

### 3.1 Quantitative: context-window utilization (the real cost lever)

Measured from this repo (≈4 chars/token):

- **MCP** loads **every tool's schema into context on every turn** — resident whether used or
  not. Our 9 tools = **~2,040 tokens, always on**.
- **Skills** keep only **L1 metadata (~44 tok/skill)** resident; the **L2 body (~110–300 tok)**
  loads only when that skill fires. Our 4 skills = **~174 tokens resident**; a typical turn
  ≈ **~470 tokens** (plus a small fixed overhead: the SkillToolset adds ~2 management tools).
- **REST** adds nothing automatically, but to let an LLM call it you inject a function schema
  per endpoint — resident like MCP, minus discovery and on-demand loading. Treat REST ≈ MCP.

**Scaling law:** MCP/REST resident context is **O(N) always-on**; Skills are **O(N) tiny
pointers + O(1) on-demand detail.**

| Capabilities | REST / MCP (all schemas resident) | Skills (metadata + 1 loaded) | Context saved |
|---|---|---|---|
| 5   | ~1,130  | ~380   | ~66% |
| 50  | ~11,300 | ~2,330 | ~79% |
| 100 | ~22,600 | ~4,500 | ~80% |

**Tokens → money.** Resident context is re-paid every turn: `cost ≈ resident_tokens × turns ×
sessions × input_price`. At 50 capabilities, 20-turn sessions, illustrative $0.30/1M input:
MCP ≈ **$0.068/session** vs Skills ≈ **$0.014/session** (~5×) → at 1M sessions/month, ≈ **$68k
vs $14k** from context alone.

**Why is MCP slightly above REST?** Not fundamental — *defaults* and *richness*: (1) MCP
auto-exposes the whole toolset via discovery (REST you hand-pick a few); (2) MCP schemas carry
`outputSchema`, annotations, and titles that REST schemas omit. Real example: `add` is ~107 tok,
but `list_generated_images` is ~644 tok — almost all of it the structured-output schema. MCP's
extra tokens *buy* discovery and typed I/O. The axis that matters is **resident vs on-demand**
(MCP/REST vs Skills), not REST vs MCP.

**Three honest caveats:** (1) this is *capability-context* cost only — the **model/inference
cost of the actual work is identical** across all three; (2) **prompt caching** discounts stable
resident context (~1/10 price) when enabled; (3) MCP has its own levers (tool filtering, fewer
servers).

**Takeaway:** breadth of know-how → **Skills** (progressive disclosure, which cuts input-token
cost); shared, credentialed capabilities → **MCP**; the cost of **the work itself** (e.g. each
generated image) is the same regardless.

### 3.2 Can a Skill live *in* an MCP server?

Not as a native primitive — MCP has no "skill" type, and a Skill executes in the **agent's**
runtime, not on the server. But they connect three ways:
1. **Skill *calls* MCP tools** — the standard composition (our `creative_studio`): the Skill's
   instructions say "call `generate_image`"; the tool lives on the server. Know-how references
   capability.
2. **MCP *prompts* ≈ workflow-text over the wire** — the closest MCP-native analog to a Skill's
   instructions, but no bundled scripts and no L1/L2/L3 progressive disclosure (see §7.3).
3. **MCP server as a Skill *registry*** — host `SKILL.md` + files as MCP **resources** and load
   them with a custom loader (ADK's Skill `Source` is "backed by any data store"). The server
   *distributes* the skill; the agent still *runs* it.

The dividing line stays **where code runs**: Skill in the agent, MCP tool on the server. Wire
them together; don't merge them.

---

## 4. Architecture — Host, Client, Server

```
   YOU  ⇄   HOST (the AI app)   ⇄   CLIENT   ⇄   SERVER   ⇄   nano-banana API
            e.g. a Gemini agent    (1 per        (our code)
                                    server)
```

- **Host** — the AI app you use. Owns the model, asks *you* for permission.
- **Client** — a connector inside the host. **One client ↔ one server.**
- **Server** — your program exposing capabilities. Ours turns "make an image" into a real
  nano-banana call.

A server only ever sees its own little conversation — never your whole chat or other servers.
Isolation by design.

---

## 5. What's on the wire? Just JSON.

MCP is **JSON-RPC 2.0**. Three message types:

**Request** (has an `id`):
```json
{ "jsonrpc":"2.0", "id":1, "method":"tools/call",
  "params": { "name":"generate_image", "arguments": { "prompt":"a banana in space" } } }
```
**Response** (same `id`):
```json
{ "jsonrpc":"2.0", "id":1, "result": { "content":[{"type":"text","text":"done"}] } }
```
**Notification** (no `id`, no reply — e.g. progress):
```json
{ "jsonrpc":"2.0", "method":"notifications/progress",
  "params": { "progress":0.7, "total":1.0 } }
```

A real round-trip (request → progress → response) for our image tool:
```jsonc
// → tools/call generate_image
// ← notifications/progress  {progress:0.7, message:"decoding image"}
// ← result: { content:[…text…], structuredContent:{resource_uri:"image://gen.png", size_bytes:1837224}, isError:false }
```
Note the response carries **both** a human-readable string *and* machine-readable
`structuredContent`.

---

## 6. The handshake (and capability negotiation)

Every connection opens the same way:
1. Client → `initialize`: "I'm version X, here's what I can do."
2. Server → replies with *its* version and capabilities.
3. Client → `notifications/initialized`: "Let's go."

This "here's what I can do" exchange is **capability negotiation** — neither side may use a
feature the other didn't advertise. It's *why* the same server behaves differently in different
apps. Real output from `raw_client.py`:
```
server: learn-mcp 1.28.1   protocolVersion: 2025-11-25
server capabilities: {prompts, resources, tools}
```

---

## 7. What a server offers (by who's in control)

- **Tools** → the **model** decides to call them.
- **Resources** → the **app** decides to read them.
- **Prompts** → the **user** decides to run them.

### 7.1 Tools
Functions the LLM invokes (with approval). Type hints become the JSON schema:
```python
@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b
```
- **Structured output:** return a typed object → callers get clean JSON. `get_weather("Tokyo")`
  → `{"temperature_c":24.5,"condition":"rainy",...}`. Our image tool returns
  `{"resource_uri":"image://gen.png","size_bytes":1837224}` instead of megabytes of base64.
- **Tool errors vs protocol errors:** a *logic* failure returns a normal result with
  `isError:true` so the model can read it and recover (our `divide`); a bad/unknown call is a
  real JSON-RPC `error` (negative code) the SDK raises. See §7.4.

### 7.2 Resources
File-like context with a URI; the app reads them (the model doesn't call them).
```python
@mcp.resource("config://app")     def app_config() -> str: ...   # fixed
@mcp.resource("image://{name}")   def read_image(name) -> bytes: ...  # templated
```
Our image tool *saves* a PNG; the `image://{name}` resource *reads it back* — tools and
resources working together.

### 7.3 Prompts
User-invoked templates (e.g. slash commands). A prompt returns either a **string** (one user
message) or a **list of `base.Message`** (system/few-shot/embedded-resource turns), and can take
typed arguments with autocomplete. You can register **as many as you like** — they all appear in
`prompts/list`.
```python
from mcp.server.fastmcp.prompts import base

@mcp.prompt(title="Art brief")                       # 1) simple, returns one message
def art_brief(subject: str, style: str = "digital art") -> str: ...

@mcp.prompt(title="Social captions")                 # 2) multi-message (style turn + ask)
def social_captions(topic: str, platform: str = "Instagram") -> list[base.Message]:
    return [base.AssistantMessage("Witty copywriter, <200 chars, 2–3 hashtags."),
            base.UserMessage(f"Write 3 {platform} captions about: {topic}")]

@mcp.prompt(title="Explain config")                  # 3) embed a resource as context
def explain_config() -> list[base.Message]:
    return [base.UserMessage("Explain this config to a new engineer:"),
            base.UserMessage(app_config())]
```
**When prompts are handy:** a *human* (in a UI host like Claude Desktop / an IDE) wants an
expert-crafted, reusable, parameterized starting point — slash commands, context-loaded reviews,
few-shot scaffolds, discoverable "what can I do here" menus. **When not:** if the *model* should
decide when to invoke → that's a **tool**; if it's data → a **resource**; in autonomous agents
prompts are largely bypassed (agents drive via tools). A prompt is essentially a tiny,
user-triggered "skill over the wire" — instructions only, no scripts or progressive disclosure.

### 7.4 What happens when a tool fails?
1. **Logic failure (recoverable):** `isError:true` result → fed back to the model → it retries /
   picks another tool / explains. **Conversation continues.** (In FastMCP, just `raise`.)
2. **Invalid call (hard):** JSON-RPC `error` (unknown tool, bad args) → client SDK raises; the
   model doesn't get a clean turn.
3. **Transport died:** timeout → `Connection closed`. (Our real one: ADK's default 5s tool
   timeout killed a healthy ~12s image call → set `timeout=120`.)

> Author's rule: recoverable → `isError` result; broken/impossible → protocol error.

---

## 8. What a client offers back (server → you)

The twist most people miss: the server can reach **back** mid-tool — if the host supports it.
Picture your tool as a **baker making a cake you ordered**:

- **Progress** — the baker **texts status**: "in the oven, 20 min left." No reply. *(Our
  `generate_image` reports "contacting Vertex → decoding → saved".)*
- **Elicitation** — the baker **needs info only you have**: "what name on the cake?" You answer.
  *(Our `commission_art` asks subject/style before drawing.)*
- **Sampling** — the baker **borrows a brain**: asks the art school to design the icing. Your
  server has no AI of its own, so it asks the **host's LLM**. *(Our `caption_last_image`.)*

Cheat sheet: **Progress** = "status update" (no reply); **Elicitation** = "answer this" (human
replies); **Sampling** = "think about this for me" (host's model replies). All three need the
open session (§9); a stateless server can't do them.

**Where they're defined:** declared in the client's `capabilities` at `initialize`; sent by the
server (`ctx.report_progress`, `ctx.elicit`, `ctx.session.create_message` in
`server/learn_mcp_server.py`) and answered by the client's callbacks (`sampling_callback`,
`elicitation_callback` in `client/raw_client.py`). They're a **matched pair** — both halves must
exist. (ADK supports progress and *optional* sampling callbacks, but **not** elicitation.)

---

## 9. Transports & state — in plain terms

Two ideas trip everyone up: **how** the client and server talk (transport), and whether the
server **remembers you** (stateful vs stateless).

**The transport is just the phone line.** The protocol is *what you say*; the transport is *how
the words travel*:
- **stdio** — the server is a program on **your own computer**, talked to via input/output pipes
  (like `cmd1 | cmd2`). → *Same room.*
- **Streamable HTTP** — the server runs **on the web**, over HTTPS. → *A phone call.*

**Why "streamable"?** A normal web request is one question → one answer → hang up (a text).
Streamable HTTP lets the server **keep sending on the same open line** (Server-Sent Events) —
like a phone call — which is what carries progress pings and the server's follow-up questions.

**Stateful vs stateless — a coffee shop:**
- **Stateful = a barista who knows you.** "Customer **#42**, the usual?" Remembers your
  order-in-progress, can call "2 min left!" and ask "oat or almond?" That memory is your
  *session*; ticket **#42** is the `Mcp-Session-Id`, which **the server issues at `initialize`**
  and you echo on every request. Downside: only that barista has your tab (session affinity).
- **Stateless = a vending machine.** Request in, coffee out, no memory, no ticket. Any machine
  works — clone a hundred. Downside: can't chat, remember you, or ask follow-ups.

So: the **session id** is the barista's ticket (a vending machine issues none);
**progress/sampling/elicitation** are barista-only; **scaling** favors vending machines.
**MCP supports both** — stateful is the default (`FastMCP(...)`), stateless is one flag
(`FastMCP(stateless_http=True, json_response=True)`) for horizontal scale, at the cost of the
server→client trio.

**How MCP differs from REST even over HTTP:** MCP is JSON-RPC with a stateful session,
`initialize` handshake, built-in discovery, and bidirectional calls; REST is stateless,
one-way, resource/verb, with no standard discovery. Same-room vs phone call *for the same
protocol*; agent-native vs a plain resource API *between MCP and REST*.

**Choosing:** local/one-user → stdio; interactive (needs progress/questions) → stateful HTTP;
simple in→out at scale → stateless HTTP.

---

## 10. Authorization (the two-boundary model)

OAuth applies to **HTTP** transport only (stdio inherits the trusting parent process). The MCP
server is an OAuth 2.1 **Resource Server** — it *validates* tokens; login is delegated to a
separate Authorization Server (your IdP).

For a hosted image server, there are **two independent boundaries that must never mix**:
```
  User/Agent ──token──▶  MCP Server  ──own identity──▶  nano-banana (Vertex)
     BOUNDARY 1: who the user is        BOUNDARY 2: may the server call the model
     (OAuth / platform IAM)             (Workload Identity — no key file)
```
- **Boundary 1** decides *who may use the capability*.
- **Boundary 2** decides *whether the server may call the model* — under its **own** identity.

The cardinal rule: **never pass the user's token through to the downstream API** (the classic
confused-deputy breach). Bind tokens to your server (audience), require PKCE, use managed
identities.

---

## 11. Hosting & scaling (to 1000s of clients)

Deploy: containerize, bind `0.0.0.0:$PORT`, run `transport="streamable-http"`, authenticate to
the model API via a **runtime service account** (no secrets in the image). Then it's a URL any
agent can point `StreamableHTTPConnectionParams` at.

**What breaks first at scale — in order:**
1. **Model quota, not your server.** Thousands of concurrent image calls share one quota →
   `429`. Image models are slow (~12s) and priced per image → cost scales linearly. Add
   per-user rate limits and a queue.
2. **Stateful sessions vs horizontal scaling.** In-memory sessions live on one instance; a
   follow-up request may hit another. Fix: **stateless HTTP** (clean scale, lose the
   server→client trio) or session affinity (fragile).
3. **Ephemeral per-instance filesystem.** Local disk breaks across instances and vanishes on
   scale-down. Fix: **object storage + signed URLs** (also keeps big blobs out of context).

```
1000s clients → LB → Cloud Run (STATELESS MCP, autoscale) → model ← the bottleneck
                                      ↓
                               Object storage → signed URLs
```
**Lesson:** stateless + object storage + per-user rate limits against a sized quota; the
autoscaler handles the rest. The MCP server is never the hard part.

---

## 12. Safety (non-negotiable)

- **Consent** — the host must ask before invoking a tool.
- **Data privacy** — no forwarding user data without permission.
- **Untrusted metadata** — treat third-party tool descriptions/servers as untrusted code
  (prompt-injection risk); vet before connecting.
- **Sampling control** — the user approves and sees sampling prompts.

The protocol can't enforce these; good hosts do.

---

## 13. Map to this repo

| Concept | Where |
|---|---|
| Simple tool / structured output | `add` · `generate_image`, `get_weather` |
| Tool error (`isError`) | `divide` |
| Progress + logging | `long_task`, image tools |
| Static + templated resources | `config://app`, `image://{name}` |
| Prompt | `art_brief` |
| Elicitation / Sampling | `commission_art` / `caption_last_image` |
| stdio transport | default run mode |
| Streamable HTTP | `--http`; `server/Dockerfile` for Cloud Run |
| Remote client over HTTP + auth | `client/remote_client.py` |
| ADK agent over HTTP streaming | `adk_agent/agent.py` |
| **Skills + MCP composed** | `creative_studio/` (4 skills + MCP tools) |
| Real cloud API behind MCP | nano-banana (`gemini-3.1-flash-image`) on Vertex |

**Next:** read `server/learn_mcp_server.py`, run `client/raw_client.py` to watch the protocol,
then chat with `creative_studio` in `adk web` to see Skills + MCP together.
