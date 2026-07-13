"""Hosted ADK agent = 4 Skills (know-how) + MCP image tools (capability).

Selectable in `adk web` as "creative_studio". Skills load from this package's own skills/
directory (self-contained); the image capability is reached over MCP Streamable HTTP.

  * Skills (poster-designer, social-post, logo-maker, photo-editor) — workflows the agent
    runs in its own runtime. Only ~44 tok of L1 metadata each is resident; L2 loads on trigger.
  * MCP tools (generate_image, edit_image, …) — the real nano-banana capability, credential
    centralized on the server.
"""

from __future__ import annotations

import os
import pathlib

from google.adk.agents import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools import skill_toolset
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
# Set GOOGLE_CLOUD_PROJECT in your environment (or rely on ADC's default project).

# MCP server URL (local HTTP-streaming instance by default; set MCP_URL to the Cloud Run URL).
MCP_URL = os.environ.get("MCP_URL", "http://localhost:9000/mcp")

SKILLS_DIR = pathlib.Path(__file__).parent / "skills"
SKILL_NAMES = ["poster-designer", "social-post", "logo-maker", "photo-editor"]
skills = [load_skill_from_dir(SKILLS_DIR / name) for name in SKILL_NAMES]

mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(url=MCP_URL, timeout=120.0),
)

root_agent = Agent(
    name="creative_studio",
    model="gemini-2.5-flash",
    instruction=(
        "You are a creative studio. Pick the right skill for the request (poster, social post, "
        "logo, or photo edit), follow its workflow, and use the MCP image tools to create or "
        "edit the image. Always report the returned resource_uri."
    ),
    tools=[
        skill_toolset.SkillToolset(skills=skills),  # know-how (progressive disclosure)
        mcp_tools,                                  # capability (nano-banana over MCP)
    ],
)
