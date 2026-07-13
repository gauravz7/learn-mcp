"""A Google ADK (Gemini) agent that uses the learn-mcp server as an MCP toolset.

The agent's LLM (Gemini on Vertex) never talks to nano-banana directly. It only sees the
MCP tools that learn-mcp advertises; when the user asks for an image, Gemini calls the MCP
`generate_image` tool over **Streamable HTTP**, and the MCP server makes the nano-banana
Vertex call. This is MCP wrapping a real cloud API, end to end, over the network transport.

The server URL is configurable via MCP_URL (defaults to a local HTTP-streaming instance):
    MCP_URL=http://localhost:9000/mcp   uv run adk web
"""

from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool import StreamableHTTPConnectionParams

# Use Vertex for the Gemini driver model too (same project as nano-banana).
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "global")
# Set GOOGLE_CLOUD_PROJECT in your environment (or rely on ADC's default project).

# Point at the MCP server's Streamable HTTP endpoint. Local by default; set MCP_URL to the
# Cloud Run URL (+ auth headers) once this org's IAP token audience is sorted out.
MCP_URL = os.environ.get("MCP_URL", "http://localhost:9000/mcp")

# Connect the ADK agent to the MCP server over HTTP streaming (not stdio).
mcp_tools = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=MCP_URL,
        # nano-banana image generation takes ~10-15s; default MCP tool timeout is only 5s.
        timeout=120.0,
    ),
)

root_agent = Agent(
    name="mcp_image_agent",
    model="gemini-2.5-flash",
    instruction=(
        "You are a creative assistant with image tools provided over MCP. "
        "When the user wants a picture, call generate_image. To modify an existing image, "
        "call edit_image with its resource_uri. You can also add numbers and fetch weather. "
        "After an image tool returns, tell the user the resource_uri and file path."
    ),
    tools=[mcp_tools],
)
