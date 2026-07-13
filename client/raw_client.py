"""raw_client.py — a minimal MCP client that talks to learn-mcp over stdio.

Purpose: watch the protocol happen directly (no LLM in the loop). It advertises the
`sampling`, `elicitation`, `roots`, and `logging` client capabilities and provides
callbacks for them, so the server's client-feature demos actually round-trip — something
a basic ADK setup won't do.

Run:  uv run --project ../server python raw_client.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.context import RequestContext
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ElicitRequestParams,
    ElicitResult,
    ListRootsResult,
    Root,
    TextContent,
)

SERVER = Path(__file__).parent.parent / "server" / "learn_mcp_server.py"
_lines: list[str] = []


def out(*a) -> None:
    line = " ".join(str(x) for x in a)
    print(line)
    _lines.append(line)


# ---- Client-side callbacks (this is what makes us a capable host) --------------------
async def sampling_cb(ctx: RequestContext, params: CreateMessageRequestParams) -> CreateMessageResult:
    """Server asked us to run an LLM. We fake a completion so the demo works offline."""
    asked = params.messages[-1].content
    asked_text = getattr(asked, "text", str(asked))
    out(f"    [sampling] server requested a completion for: {asked_text!r}")
    return CreateMessageResult(
        role="assistant",
        content=TextContent(type="text", text="One small step for fruit, one giant leap for snacks."),
        model="raw-client-stub",
    )


async def elicitation_cb(ctx: RequestContext, params: ElicitRequestParams) -> ElicitResult:
    """Server asked the user for structured input. We auto-answer to demo the round-trip."""
    out(f"    [elicitation] server asks: {params.message!r}")
    return ElicitResult(
        action="accept",
        content={"subject": "a robot barista", "style": "cyberpunk", "aspect_ratio": "1:1"},
    )


async def roots_cb(ctx: RequestContext) -> ListRootsResult:
    """Server asked what filesystem roots it may use."""
    root = Root(uri=f"file://{SERVER.parent}", name="server-dir")
    out(f"    [roots] advertising root: {root.uri}")
    return ListRootsResult(roots=[root])


async def logging_cb(params) -> None:
    out(f"    [log/{params.level}] {params.data}")


async def main() -> None:
    params = StdioServerParameters(
        command="uv",
        args=["run", "--project", str(SERVER.parent), "python", str(SERVER)],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read,
            write,
            sampling_callback=sampling_cb,
            elicitation_callback=elicitation_cb,
            list_roots_callback=roots_cb,
            logging_callback=logging_cb,
        ) as session:
            # 1) LIFECYCLE ---------------------------------------------------------------
            init = await session.initialize()
            out("== INITIALIZE ==")
            out("server:", init.serverInfo.name, init.serverInfo.version)
            out("protocolVersion:", init.protocolVersion)
            out("server capabilities:", init.capabilities.model_dump(exclude_none=True))

            # 2) DISCOVERY ---------------------------------------------------------------
            tools = await session.list_tools()
            out("\n== TOOLS ==", [t.name for t in tools.tools])
            resources = await session.list_resources()
            out("== RESOURCES ==", [str(r.uri) for r in resources.resources])
            templates = await session.list_resource_templates()
            out("== TEMPLATES ==", [t.uriTemplate for t in templates.resourceTemplates])
            prompts = await session.list_prompts()
            out("== PROMPTS ==", [p.name for p in prompts.prompts])

            # 3) SIMPLE TOOL + STRUCTURED OUTPUT ----------------------------------------
            r = await session.call_tool("add", {"a": 2, "b": 3})
            out("\nadd(2,3) ->", r.content[0].text)
            r = await session.call_tool("get_weather", {"city": "Tokyo"})
            out("get_weather(Tokyo) structuredContent ->", r.structuredContent)

            # 4) TOOL ERROR (isError) ---------------------------------------------------
            r = await session.call_tool("divide", {"a": 1, "b": 0})
            out("divide(1,0) isError ->", r.isError, "|", r.content[0].text[:80])

            # 5) FLAGSHIP: nano-banana text->image --------------------------------------
            out("\n== generate_image (nano-banana) ==")
            r = await session.call_tool(
                "generate_image", {"prompt": "a raccoon astronaut planting a flag on the moon"}
            )
            out("structuredContent ->", r.structuredContent)
            img_uri = r.structuredContent["resource_uri"]

            # 6) READ IT BACK VIA TEMPLATED RESOURCE ------------------------------------
            name = img_uri.removeprefix("image://")
            res = await session.read_resource(f"image://{name}")
            blob = res.contents[0]
            out(f"read_resource({img_uri}) -> mime={blob.mimeType} blob_len={len(blob.blob)}")

            # 7) EDIT THAT IMAGE --------------------------------------------------------
            out("\n== edit_image (nano-banana) ==")
            r = await session.call_tool(
                "edit_image", {"source": img_uri, "edit_prompt": "give the raccoon a tiny top hat"}
            )
            out("edited ->", r.structuredContent["resource_uri"])

            # 8) resource_link content type ---------------------------------------------
            r = await session.call_tool("list_generated_images", {})
            out("\nlist_generated_images -> resource_links:", [c.uri for c in r.content])

            # 9) STATIC RESOURCE + PROMPT ----------------------------------------------
            res = await session.read_resource("config://app")
            out("\nconfig://app ->", res.contents[0].text)
            p = await session.get_prompt("art_brief", {"subject": "a lighthouse", "style": "oil painting"})
            out("art_brief prompt ->", p.messages[0].content.text[:90], "…")

            # 10) CLIENT FEATURES: elicitation + sampling round-trips --------------------
            out("\n== elicitation demo ==")
            r = await session.call_tool("commission_art", {})
            out("commission_art ->", r.content[0].text)
            out("\n== sampling demo ==")
            r = await session.call_tool("caption_last_image", {})
            out("caption_last_image ->", r.content[0].text)

    transcript = Path(__file__).parent.parent / "transcripts" / "raw_client.txt"
    transcript.parent.mkdir(exist_ok=True)
    transcript.write_text("\n".join(_lines) + "\n")
    out(f"\n[saved transcript -> {transcript}]")


if __name__ == "__main__":
    asyncio.run(main())
