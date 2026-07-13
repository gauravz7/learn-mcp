"""ADK agent that combines a SKILL (know-how) with an MCP TOOL (capability).

The pattern from THEORY.md §2.5, made concrete:

  * The **poster-designer Skill** (skills/poster_designer/SKILL.md) carries the *workflow* —
    how to turn a rough idea into a polished image prompt, when to use 4:5, what to do on an
    edit request. It runs inside the ADK agent's own runtime (no hosting).
  * The **MCP `generate_image` / `edit_image` tools** carry the *capability* — the actual
    nano-banana call, reached over Streamable HTTP, with the Vertex credential centralized on
    the server side.

Know-how in the Skill; the shared, credentialed capability in MCP. They compose in one agent.

Run:
    # start the MCP server in HTTP mode first (separate shell):
    #   uv run --project ../server python ../server/learn_mcp_server.py --http --port 9000
    uv run python skill_mcp_demo.py
"""

from __future__ import annotations

import asyncio
import os
import pathlib

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
# Set GOOGLE_CLOUD_PROJECT in your environment (or rely on ADC's default project).

MCP_URL = os.environ.get("MCP_URL", "http://localhost:9000/mcp")
HERE = pathlib.Path(__file__).parent

# 1) SKILLS — multiple workflows/know-how, loaded from the filesystem. Only each skill's
#    ~100-token L1 metadata is resident; the full L2/L3 loads only when a skill is triggered.
SKILL_NAMES = ["poster-designer", "social-post", "logo-maker", "photo-editor"]
skills = [load_skill_from_dir(HERE / "skills" / name) for name in SKILL_NAMES]

# 2) MCP TOOLS — the real image capability, reached over Streamable HTTP.
mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL, timeout=120.0),
)

# 3) One agent with MANY skills (know-how) + the MCP tools (capability).
root_agent = Agent(
    name="creative_agent",
    model="gemini-2.5-flash",
    instruction=(
        "You are a creative studio. Pick the right skill for the request (poster, social post, "
        "logo, or photo edit) and use the MCP image tools to create/edit. Always report the "
        "resource_uri."
    ),
    tools=[
        skill_toolset.SkillToolset(skills=skills),  # know-how (4 skills, progressive disclosure)
        mcp_tools,                                  # capability
    ],
)

APP, USER = "skill_mcp_demo", "designer"


async def ask(runner, session_id: str, text: str) -> None:
    print(f"\n>>> USER: {text}", flush=True)
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=msg):
        for part in (event.content.parts if event.content else []) or []:
            if getattr(part, "function_call", None):
                print(f"    [agent → tool] {part.function_call.name}({dict(part.function_call.args)})")
            if getattr(part, "function_response", None):
                print(f"    [tool → agent] {str(part.function_response.response)[:300]}")
            if getattr(part, "text", None):
                print(f"    [agent]: {part.text.strip()}")


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id=USER)
    # Two different requests → two DIFFERENT skills fire (progressive disclosure).
    # Only the relevant skill's L2 instructions load; the others stay at L1 metadata.
    await ask(runner, session.id, "Make a minimalist logo for a coffee brand called 'Orbit'.")
    await ask(runner, session.id, "Create an Instagram post for a summer sneaker drop.")


if __name__ == "__main__":
    asyncio.run(main())
