"""Handing the live browser to a person without losing it.

The thing under test is a design decision, not just a queue: v4 pauses with
`interrupt()`, which unwinds the node — and a browser handover cannot, because
unwinding closes the Chromium the person is about to take over. So the node
blocks here instead, and these tests pin what that costs and guarantees.
"""

import asyncio

import pytest

from travel_planner.tools.mcp import control, handover


class FakeTool:
    def __init__(self, result=None, boom=False):
        self.result, self.boom, self.calls = result, boom, []

    async def ainvoke(self, args):
        self.calls.append(args)
        if self.boom:
            raise RuntimeError("the browser went away")
        return self.result


SNAPSHOT = """### Page
- Page URL: https://example.test/login
- Page Title: Sign in
### Snapshot
```yaml
- generic [ref=e1]:
  - textbox "Email" [ref=e2]
  - button "Continue" [ref=e5]
```
"""

GATE = '### Result\n{"password": true, "path": "/login"}\n### Ran'


class FakeToolset:
    """Enough of a browser to drive a handover without launching one."""

    def __init__(self):
        self.clicked: list[dict] = []
        self.tools = {
            "browser_snapshot": FakeTool(SNAPSHOT),
            "browser_evaluate": FakeTool(GATE),
            "browser_navigate": FakeTool("ok"),
            "browser_take_screenshot": FakeTool(None),
            "browser_press_key": FakeTool("ok"),
        }

    def get(self, *names):
        for n in names:
            if n in self.tools:
                return self.tools[n]
        return None


@pytest.fixture(autouse=True)
def _no_leaked_handovers():
    yield
    handover._open.clear()


# --- the lifecycle --------------------------------------------------------------


async def test_a_person_can_drive_and_then_release():
    ts = FakeToolset()
    served = asyncio.create_task(handover.serve(ts, "t-1", reason="login", timeout=5, refresh=0.05))
    await asyncio.sleep(0.05)

    assert handover.current("t-1") is not None
    result = await handover.submit("t-1", {"kind": "press", "key": "Tab"})
    assert result["ok"] is True
    assert ts.tools["browser_press_key"].calls == [{"key": "Tab"}]

    assert handover.release("t-1") is True
    assert await served == "released"
    assert handover.current("t-1") is None


async def test_what_is_waiting_is_visible_while_it_waits():
    ts = FakeToolset()
    task = asyncio.create_task(handover.serve(ts, "t-2", reason="login", timeout=5, refresh=0.05))
    await asyncio.sleep(0.05)

    (item,) = handover.waiting()
    assert item["thread_id"] == "t-2"
    assert item["reason"] == "login"
    assert item["url"] == "https://example.test/login"
    assert item["terminal"] is False
    # The page is described so a client can offer buttons without driving the
    # browser itself — a second reader taking snapshots would fight the node.
    assert {"ref": "e5", "role": "button", "name": "Continue"} in item["elements"]

    handover.release("t-2")
    await task


async def test_an_unanswered_handover_expires():
    """A blocked node holds one of very few browser slots. Waiting forever
    would mean one forgotten tab blocks the next traveller."""
    ts = FakeToolset()
    assert await handover.serve(ts, "t-3", reason="login", timeout=0.2, refresh=0.05) == "expired"
    assert handover.current("t-3") is None


async def test_a_payment_handover_is_marked_terminal():
    """A login is a detour and the run resumes. A payment page is where the
    automation stops for good."""
    ts = FakeToolset()
    task = asyncio.create_task(handover.serve(ts, "t-4", reason="payment", timeout=5, refresh=0.05))
    await asyncio.sleep(0.05)
    assert handover.waiting()[0]["terminal"] is True
    handover.release("t-4")
    await task


async def test_an_unknown_reason_is_refused():
    with pytest.raises(ValueError, match="unknown handover reason"):
        await handover.serve(FakeToolset(), "t-5", reason="vibes", timeout=1)


# --- driving it -----------------------------------------------------------------


async def test_submitting_to_nothing_is_an_error_not_a_silent_noop():
    """Driving a browser that has moved on should be something the caller
    hears about, not a click that lands nowhere."""
    with pytest.raises(LookupError, match="no handover is open"):
        await handover.submit("nobody-home", {"kind": "press", "key": "Enter"})


async def test_a_bad_instruction_is_rejected_before_it_reaches_the_browser():
    ts = FakeToolset()
    task = asyncio.create_task(handover.serve(ts, "t-6", reason="login", timeout=5, refresh=0.05))
    await asyncio.sleep(0.05)
    with pytest.raises(control.ControlError):
        await handover.submit("t-6", {"kind": "launch_missiles"})
    handover.release("t-6")
    await task


async def test_a_failing_action_answers_rather_than_hanging():
    ts = FakeToolset()
    ts.tools["browser_press_key"] = FakeTool(boom=True)
    task = asyncio.create_task(handover.serve(ts, "t-7", reason="login", timeout=5, refresh=0.05))
    await asyncio.sleep(0.05)

    result = await handover.submit("t-7", {"kind": "press", "key": "Enter"})
    assert result["ok"] is False and "ControlError" in result["error"]

    handover.release("t-7")
    assert await task == "released"


async def test_queued_work_is_answered_when_the_handover_closes():
    """Otherwise a caller waits out its own timeout for a browser that is gone,
    so the request looks slow rather than answered."""
    h = handover._open_handover("t-8", "login", None, "")
    cmd = handover.Command(action=control.Action(kind="press", key="Enter"))
    await h.commands.put(cmd)

    assert handover.answer_pending(h) == 1
    assert cmd.done.result() == {"ok": False, "error": "the handover closed"}


async def test_expiry_leaves_nothing_queued_behind():
    ts = FakeToolset()
    assert await handover.serve(ts, "t-8b", reason="login", timeout=0.2, refresh=0.05) == "expired"
    assert handover.current("t-8b") is None


async def test_the_page_view_refreshes_while_nobody_sends_anything():
    """A watcher should see a live browser, not a frozen screenshot."""
    ts = FakeToolset()
    task = asyncio.create_task(handover.serve(ts, "t-9", reason="login", timeout=0.4, refresh=0.05))
    await asyncio.sleep(0.25)
    snapshots_taken = len(ts.tools["browser_snapshot"].calls)
    assert snapshots_taken > 1, "the page should be re-read on a timer"
    handover.release("t-9")
    await task
