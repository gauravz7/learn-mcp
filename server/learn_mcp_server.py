"""learn-mcp — a FastMCP server that exercises every MCP primitive.

Flagship tools wrap a real Google Cloud API — nano-banana image generation
(`gemini-3.1-flash-image`) on Vertex AI — as two MCP tools:

    * generate_image  : text -> image
    * edit_image      : image + prompt -> image

Plus supporting tools, resources, a prompt, and (capability-gated) elicitation and
sampling demos. Run over stdio (default, for the ADK agent) or Streamable HTTP (--http).

See ../THEORY.md for the concepts each piece demonstrates.
"""

from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ResourceLink
from pydantic import BaseModel, Field

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")  # set in env, or resolved from ADC
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
IMAGE_MODEL = os.environ.get("NANO_BANANA_MODEL", "gemini-3.1-flash-image")

GENERATED_DIR = Path(__file__).parent / "generated"
GENERATED_DIR.mkdir(exist_ok=True)

# Behind Cloud Run the Host header is the *.run.app domain, so FastMCP's default
# localhost-only DNS-rebinding allowlist would 421 every request. DNS-rebinding protection
# defends browser→localhost servers; for a public service fronted by Cloud Run + IAM it's
# not the relevant threat, so we disable that specific check and let Cloud Run be the
# security boundary. (For a purely-local HTTP server, keep it enabled and pin localhost.)
_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
mcp = FastMCP("learn-mcp", transport_security=_security)

# Lazy genai client so the server can start (and list tools) even without Vertex creds.
_genai_client: genai.Client | None = None


def _client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(vertexai=True, project=PROJECT, location=LOCATION)
    return _genai_client


def _save_image_bytes(data: bytes, mime: str, stem: str) -> Path:
    ext = "png" if "png" in mime else ("jpg" if "jp" in mime else "bin")
    # Deterministic-ish unique name without Math.random/Date: use monotonic counter file.
    path = GENERATED_DIR / f"{stem}.{ext}"
    n = 1
    while path.exists():
        path = GENERATED_DIR / f"{stem}_{n}.{ext}"
        n += 1
    path.write_bytes(data)
    return path


def _extract_image(resp) -> tuple[bytes, str, str]:
    """Pull the first inline image + any text out of a genai response."""
    text_out = ""
    for cand in resp.candidates or []:
        for part in cand.content.parts or []:
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data, inline.mime_type or "image/png", text_out
            if getattr(part, "text", None):
                text_out += part.text
    raise ValueError(f"Model returned no image. Text was: {text_out[:300]!r}")


# --------------------------------------------------------------------------------------
# Structured-output models (become each tool's outputSchema)
# --------------------------------------------------------------------------------------
class GeneratedImage(BaseModel):
    """Structured result of an image tool — machine-readable, no megabytes of base64."""

    resource_uri: str = Field(description="MCP resource URI to read the image back, e.g. image://name.png")
    path: str = Field(description="Absolute path where the PNG was saved on the server")
    mime_type: str
    size_bytes: int
    model: str = Field(description="The nano-banana model that produced it")
    prompt: str


class WeatherReport(BaseModel):
    city: str
    temperature_c: float
    condition: str
    humidity_pct: int


# --------------------------------------------------------------------------------------
# FLAGSHIP TOOLS — nano-banana on Vertex
# --------------------------------------------------------------------------------------
@mcp.tool()
async def generate_image(prompt: str, ctx: Context, aspect_ratio: str = "16:9") -> GeneratedImage:
    """Generate a brand-new image from a text prompt using nano-banana (Gemini image model).

    Use this when the user wants an image created from scratch. Returns a resource URI
    (image://<name>) that can be read back via resources, plus metadata.
    """
    await ctx.info(f"Calling nano-banana ({IMAGE_MODEL}) for a {aspect_ratio} image…")
    await ctx.report_progress(0.1, 1.0, "contacting Vertex")

    resp = _client().models.generate_content(
        model=IMAGE_MODEL,
        contents=f"{prompt}. Aspect ratio {aspect_ratio}.",
    )
    await ctx.report_progress(0.7, 1.0, "decoding image")
    data, mime, _ = _extract_image(resp)

    path = _save_image_bytes(data, mime, stem="gen")
    await ctx.report_progress(1.0, 1.0, "saved")
    await ctx.info(f"Saved {len(data)} bytes to {path}")

    return GeneratedImage(
        resource_uri=f"image://{path.name}",
        path=str(path),
        mime_type=mime,
        size_bytes=len(data),
        model=IMAGE_MODEL,
        prompt=prompt,
    )


@mcp.tool()
async def edit_image(source: str, edit_prompt: str, ctx: Context) -> GeneratedImage:
    """Edit an existing image with a natural-language instruction (nano-banana image edit).

    `source` may be an MCP image:// resource URI, a bare filename in the generated/ dir,
    or an absolute path. Example edit_prompt: 'add sunglasses, keep everything else the same'.
    """
    # Resolve source -> bytes
    name = source.removeprefix("image://")
    src_path = Path(name) if os.path.isabs(name) else (GENERATED_DIR / name)
    if not src_path.exists():
        # Surface as a *tool* error the model can read/react to (isError), not a crash.
        raise ValueError(f"Source image not found: {src_path}")

    await ctx.info(f"Editing {src_path.name} with nano-banana…")
    await ctx.report_progress(0.2, 1.0, "reading source")
    img_bytes = src_path.read_bytes()

    resp = _client().models.generate_content(
        model=IMAGE_MODEL,
        contents=[
            genai_types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
            edit_prompt,
        ],
    )
    await ctx.report_progress(0.8, 1.0, "decoding edited image")
    data, mime, _ = _extract_image(resp)
    path = _save_image_bytes(data, mime, stem="edit")
    await ctx.report_progress(1.0, 1.0, "saved")

    return GeneratedImage(
        resource_uri=f"image://{path.name}",
        path=str(path),
        mime_type=mime,
        size_bytes=len(data),
        model=IMAGE_MODEL,
        prompt=edit_prompt,
    )


# --------------------------------------------------------------------------------------
# SUPPORTING TOOLS — cover the rest of the tool surface
# --------------------------------------------------------------------------------------
@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers. Simplest possible tool: typed inputs, scalar output."""
    return a + b


@mcp.tool()
def get_weather(city: str) -> WeatherReport:
    """Return a (mock) structured weather report — demonstrates a second outputSchema."""
    seed = sum(ord(c) for c in city)
    return WeatherReport(
        city=city,
        temperature_c=round(10 + seed % 20 + 0.5, 1),
        condition=["sunny", "cloudy", "rainy", "windy"][seed % 4],
        humidity_pct=40 + seed % 50,
    )


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Divide a by b. Raises on divide-by-zero to demonstrate a tool error (isError)."""
    if b == 0:
        raise ValueError("Cannot divide by zero — this reaches the model as isError=true.")
    return a / b


@mcp.tool()
async def long_task(steps: int, ctx: Context) -> str:
    """Simulate a long job, emitting progress notifications and log messages."""
    for i in range(steps):
        await ctx.report_progress((i + 1) / steps, 1.0, f"step {i + 1}/{steps}")
        await ctx.debug(f"working on step {i + 1}")
        time.sleep(0.05)
    return f"Completed {steps} steps."


@mcp.tool()
def list_generated_images() -> list[ResourceLink]:
    """List previously generated images as MCP resource_link content blocks."""
    links: list[ResourceLink] = []
    for p in sorted(GENERATED_DIR.glob("*.png")):
        links.append(
            ResourceLink(
                type="resource_link",
                uri=f"image://{p.name}",
                name=p.name,
                mimeType="image/png",
            )
        )
    return links


# --------------------------------------------------------------------------------------
# CLIENT-FEATURE DEMOS — capability-gated (degrade gracefully)
# --------------------------------------------------------------------------------------
class ArtCommission(BaseModel):
    subject: str = Field(description="What to depict")
    style: str = Field(description="Art style, e.g. 'watercolor', 'pixel art'")
    aspect_ratio: str = Field(default="16:9", description="e.g. 16:9, 1:1")


@mcp.tool()
async def commission_art(ctx: Context) -> str:
    """Elicitation demo: ask the USER (via the client) for structured art details, then generate.

    Requires a client that advertises the `elicitation` capability. Degrades gracefully.
    """
    try:
        result = await ctx.elicit(
            message="Let's commission some art. Tell me what to make:",
            schema=ArtCommission,
        )
    except Exception as e:  # client didn't advertise elicitation
        return f"[elicitation unavailable on this client: {e}] Call generate_image directly instead."

    if result.action != "accept" or result.data is None:
        return f"User {result.action}ed the commission."
    spec = result.data
    img = await generate_image(
        prompt=f"{spec.subject}, {spec.style} style",
        ctx=ctx,
        aspect_ratio=spec.aspect_ratio,
    )
    return f"Commissioned '{spec.subject}' in {spec.style}. Saved to {img.resource_uri}."


@mcp.tool()
async def caption_last_image(ctx: Context) -> str:
    """Sampling demo: ask the HOST's LLM t
    o write a caption for the latest image.

    Requires a client that advertises the `sampling` capability. Degrades gracefully.
    """
    pngs = sorted(GENERATED_DIR.glob("*.png"))
    if not pngs:
        return "No generated images yet."
    latest = pngs[-1]
    try:
        from mcp.types import SamplingMessage, TextContent

        result = await ctx.session.create_message(
            messages=[
                SamplingMessage(
                    role="user",
                    content=TextContent(
                        type="text",
                        text=f"Write a witty one-line caption for an image file named {latest.name}.",
                    ),
                )
            ],
            max_tokens=60,
        )
        text = getattr(result.content, "text", str(result.content))
        return f"Caption for {latest.name}: {text}"
    except Exception as e:  # client didn't advertise sampling
        return f"[sampling unavailable on this client: {e}] Would have captioned {latest.name}."


# --------------------------------------------------------------------------------------
# RESOURCES
# --------------------------------------------------------------------------------------
@mcp.resource("config://app")
def app_config() -> str:
    """A static resource: server configuration as JSON text."""
    return (
        '{"name": "learn-mcp", "image_model": "%s", "project": "%s", "location": "%s"}'
        % (IMAGE_MODEL, PROJECT, LOCATION)
    )


@mcp.resource("image://{name}", mime_type="image/png")
def read_image(name: str) -> bytes:
    """A templated resource: read a generated image back by filename (returned as a blob)."""
    path = GENERATED_DIR / name
    if not path.exists():
        raise ValueError(f"No such image: {name}")
    return path.read_bytes()


# --------------------------------------------------------------------------------------
# PROMPT
# --------------------------------------------------------------------------------------
@mcp.prompt(title="Art brief")
def art_brief(subject: str, style: str = "digital art") -> str:
    """A user-invoked prompt: expand a rough idea into a polished image-generation brief."""
    return (
        f"You are an art director. Expand this into a single vivid, detailed image-generation "
        f"prompt (one paragraph, no preamble):\n\nSubject: {subject}\nStyle: {style}"
    )


# --------------------------------------------------------------------------------------
# Entrypoint
# --------------------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="learn-mcp server")
    parser.add_argument("--http", action="store_true", help="serve over Streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = parser.parse_args()

    # Cloud Run injects $PORT and requires binding 0.0.0.0. If PORT is set, assume HTTP.
    if args.http or "PORT" in os.environ:
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run()  # stdio (default)


if __name__ == "__main__":
    main()
