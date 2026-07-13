"""Drive the ADK agent end-to-end and capture the transcript as blog evidence.

Sends two prompts: a simple tool call (add) and the centerpiece image request. Prints
every event so we can see Gemini deciding to call the MCP tools and using the results.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from google.genai import types

from agent import root_agent
from google.adk.runners import InMemoryRunner

APP = "mcp_demo"
USER = "learner"
_log: list[str] = []


def out(*a) -> None:
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    _log.append(line)


async def ask(runner, session_id: str, text: str) -> None:
    out(f"\n>>> USER: {text}")
    msg = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(user_id=USER, session_id=session_id, new_message=msg):
        for part in (event.content.parts if event.content else []) or []:
            if getattr(part, "function_call", None):
                fc = part.function_call
                out(f"    [Gemini -> MCP tool] {fc.name}({dict(fc.args)})")
            if getattr(part, "function_response", None):
                resp = part.function_response.response
                # Trim any base64 from the printed response
                out(f"    [MCP tool -> Gemini] {str(resp)[:400]}")
            if getattr(part, "text", None):
                out(f"    [Gemini]: {part.text.strip()}")


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name=APP)
    session = await runner.session_service.create_session(app_name=APP, user_id=USER)

    await ask(runner, session.id, "What is 2 plus 3? Use your tool.")
    await ask(
        runner,
        session.id,
        "Generate an image of a banana astronaut floating above the moon, cartoon style.",
    )

    transcript = Path(__file__).parent.parent / "transcripts" / "adk_run.txt"
    transcript.parent.mkdir(exist_ok=True)
    transcript.write_text("\n".join(_log) + "\n")
    out(f"\n[saved transcript -> {transcript}]")


if __name__ == "__main__":
    asyncio.run(main())
