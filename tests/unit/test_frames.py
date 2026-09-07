"""Screenshot capture and storage."""

import base64

from travel_planner.tools.mcp import frames


def test_extracts_jpeg_from_an_mcp_result():
    payload = base64.b64encode(b"\xff\xd8\xff-not-really-a-jpeg").decode()
    result = [
        {"type": "text", "text": "Took a screenshot"},
        {"type": "image", "base64": payload},
    ]
    assert frames.extract_image(result) == b"\xff\xd8\xff-not-really-a-jpeg"


def test_accepts_the_older_data_key():
    """Adapter versions differ on `base64` vs `data`; both must work."""
    payload = base64.b64encode(b"bytes").decode()
    assert frames.extract_image([{"type": "image", "data": payload}]) == b"bytes"


def test_returns_none_when_there_is_no_image():
    assert frames.extract_image([{"type": "text", "text": "no picture here"}]) is None
    assert frames.extract_image("not a list") is None
    assert frames.extract_image([{"type": "image"}]) is None


def test_undecodable_payload_returns_none_rather_than_raising():
    assert frames.extract_image([{"type": "image", "base64": "!!!not base64!!!"}]) is None


def test_path_traversal_is_refused():
    """The name arrives from an HTTP route, so `../../.env` is a real request."""
    assert frames.frame_path("run", "../../.env") is None
    assert frames.frame_path("run", "../../../etc/passwd") is None


def test_missing_frame_returns_none():
    assert frames.frame_path("no-such-run", "0001.jpg") is None


def test_screenshot_is_viewport_jpeg():
    """A full-page PNG of a results page can be 2 MB and 8000px tall — useless
    in a UI panel and slow to produce."""
    assert frames.SCREENSHOT_ARGS == {"type": "jpeg", "fullPage": False}
