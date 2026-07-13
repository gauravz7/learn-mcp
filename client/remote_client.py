"""remote_client.py — talk to the learn-mcp server hosted on Cloud Run (Streamable HTTP).

Unlike raw_client.py (which launches the server locally over stdio), this connects to the
deployed URL over HTTPS and authenticates with a Google **identity token** (audience = the
service URL). That token is what Cloud Run IAM checks — our Boundary 1.

Usage:
    uv run --project ../server python remote_client.py
    MCP_URL=https://your-service.run.app uv run --project ../server python remote_client.py

Auth: by default we mint an identity token via `gcloud auth print-identity-token
--audiences=<url>`. Override by exporting MCP_BEARER_TOKEN=<token>.
"""

from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

DEFAULT_URL = "https://YOUR-MCP-SERVER.run.app"  # override via MCP_URL env var
BASE_URL = os.environ.get("MCP_URL", DEFAULT_URL).rstrip("/")
MCP_ENDPOINT = f"{BASE_URL}/mcp"


def get_token() -> str:
    """Return a Google identity token whose audience == the Cloud Run service URL.

    On GCP (workstation/GCE/Cloud Run) the metadata server mints an ID token with an
    arbitrary audience for the attached service account — this is what standard Cloud Run
    IAM auth expects. (Plain `gcloud auth print-identity-token --audiences` is ignored for
    user/ADC creds and yields the wrong audience, so we use the metadata server.)
    """
    token = os.environ.get("MCP_BEARER_TOKEN")
    if token:
        return token.strip()
    import urllib.request

    req = urllib.request.Request(
        f"http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity?audience={BASE_URL}",
        headers={"Metadata-Flavor": "Google"},
    )
    try:
        token = urllib.request.urlopen(req, timeout=5).read().decode().strip()
    except Exception as e:
        sys.exit(f"Could not mint identity token from metadata server: {e}")
    if not token:
        sys.exit("Metadata server returned an empty identity token.")
    return token


async def main() -> None:
    token = get_token()
    print(f"Connecting to {MCP_ENDPOINT}")
    print(f"Bearer token: {token[:24]}… ({len(token)} chars)\n")

    headers = {"Authorization": f"Bearer {token}"}
    async with streamablehttp_client(MCP_ENDPOINT, headers=headers) as (read, write, get_sid):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("== CONNECTED ==")
            print("server:", init.serverInfo.name, init.serverInfo.version)
            print("protocolVersion:", init.protocolVersion)
            print("Mcp-Session-Id:", get_sid(), "\n")

            tools = await session.list_tools()
            print("tools:", [t.name for t in tools.tools])

            r = await session.call_tool("add", {"a": 100, "b": 23})
            print("add(100,23) ->", r.content[0].text)

            r = await session.call_tool("get_weather", {"city": "Singapore"})
            print("get_weather(Singapore) ->", r.structuredContent)

            print("\ngenerating an image on the remote server (nano-banana)…")
            r = await session.call_tool(
                "generate_image", {"prompt": "a cheerful robot barista serving coffee, flat vector art"}
            )
            print("generate_image ->", r.structuredContent)

    print("\n[done — this all ran against the hosted Cloud Run server]")


if __name__ == "__main__":
    asyncio.run(main())
