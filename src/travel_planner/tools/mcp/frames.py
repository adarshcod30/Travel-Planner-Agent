"""Capturing and storing browser screenshots.

Frames are written to disk and referenced by path in the event stream rather
than inlined. A base64 JPEG of a full page is 100-300 KB; at one frame per
browser action that would swamp the SSE connection and make the live view
*slower* than the browsing it is showing. On disk they are fetched over plain
HTTP, cached by the browser, and survive the run — which also gives a
replayable filmstrip.

They are deleted with the thread, by `storage.purge_thread`.
"""

import base64
from pathlib import Path
from typing import Any

from travel_planner.core.logging import get_logger

log = get_logger(__name__)

FRAME_ROOT = Path("data/runs")

#: JPEG rather than PNG, and viewport rather than full page. A full-page
#: screenshot of a search results page can be 2 MB and 8000px tall — unreadable
#: in a UI panel and slow to produce. The viewport is what a person would see.
SCREENSHOT_ARGS: dict[str, Any] = {"type": "jpeg", "fullPage": False}


def frame_dir(thread_id: str) -> Path:
    d = FRAME_ROOT / thread_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_image(result: Any) -> bytes | None:
    """Pull the JPEG bytes out of an MCP screenshot result.

    Playwright MCP returns a list of content blocks: a text block describing the
    action and an image block carrying base64. Older adapter versions used
    `data` rather than `base64`, so both are accepted.
    """
    if not isinstance(result, list):
        return None
    for item in result:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        payload = item.get("base64") or item.get("data")
        if payload:
            try:
                return base64.b64decode(payload)
            except Exception:
                return None
    return None


async def capture(toolset: Any, thread_id: str, seq: int, timeout: float = 20.0) -> str | None:
    """Screenshot the current page and store it. Returns a servable path.

    Returns None rather than raising: a failed screenshot should cost the run a
    frame, never the browse.
    """
    import asyncio

    shot = toolset.get("browser_take_screenshot")
    if shot is None:
        return None
    try:
        result = await asyncio.wait_for(shot.ainvoke(SCREENSHOT_ARGS), timeout=timeout)
    except Exception as exc:
        log.debug("frame_capture_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None

    data = extract_image(result)
    if not data:
        return None

    name = f"{seq:04d}.jpg"
    (frame_dir(thread_id) / name).write_bytes(data)
    return f"{thread_id}/{name}"


def frame_path(thread_id: str, name: str) -> Path | None:
    """Resolve a servable frame path, refusing anything outside the run's directory.

    The name reaches this from an HTTP route, so a caller could send
    `../../.env`. Resolving both sides and checking containment is what makes
    that impossible rather than merely unlikely.
    """
    root = FRAME_ROOT.resolve()
    candidate = (FRAME_ROOT / thread_id / name).resolve()
    if not candidate.is_file() or root not in candidate.parents:
        return None
    return candidate
