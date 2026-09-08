"""The Aegra auth handler.

Two behaviours here failed in a way that looked like success, so both are
pinned: assistants must stay readable (an owner filter over them hides the
server's own graphs and returns an empty 200), and the owner stamp must
survive an explicit `metadata: null` from the client.
"""

from types import SimpleNamespace

import pytest

from travel_planner.auth import handler as h


@pytest.fixture
def ctx():
    return SimpleNamespace(user=SimpleNamespace(identity="alice"))


# --- authentication -------------------------------------------------------------


async def test_noop_mode_authenticates_everyone():
    user = await h.authenticate({})
    assert user["identity"] == h.DEV_IDENTITY and user["is_authenticated"]


async def test_token_mode_rejects_a_missing_token(monkeypatch):
    monkeypatch.setattr(h, "AUTH_TYPE", "token")
    monkeypatch.setattr(h, "API_TOKEN", "s3cret")
    with pytest.raises(h.Auth.exceptions.HTTPException):
        await h.authenticate({})


async def test_token_mode_rejects_a_wrong_token(monkeypatch):
    monkeypatch.setattr(h, "AUTH_TYPE", "token")
    monkeypatch.setattr(h, "API_TOKEN", "s3cret")
    with pytest.raises(h.Auth.exceptions.HTTPException):
        await h.authenticate({b"authorization": b"Bearer wrong"})


async def test_token_mode_accepts_and_takes_identity_from_header(monkeypatch):
    monkeypatch.setattr(h, "AUTH_TYPE", "token")
    monkeypatch.setattr(h, "API_TOKEN", "s3cret")
    user = await h.authenticate({b"authorization": b"Bearer s3cret", b"x-user-id": b"bob"})
    assert user["identity"] == "bob"


async def test_token_mode_falls_back_to_a_generic_identity(monkeypatch):
    monkeypatch.setattr(h, "AUTH_TYPE", "token")
    monkeypatch.setattr(h, "API_TOKEN", "s3cret")
    assert (await h.authenticate({b"Authorization": b"Bearer s3cret"}))["identity"] == "api-user"


async def test_token_mode_with_no_token_configured_rejects(monkeypatch):
    """An unset AEGRA_API_TOKEN must not become an accept-anything mode."""
    monkeypatch.setattr(h, "AUTH_TYPE", "token")
    monkeypatch.setattr(h, "API_TOKEN", "")
    with pytest.raises(h.Auth.exceptions.HTTPException):
        await h.authenticate({b"authorization": b"Bearer anything"})


# --- ownership ------------------------------------------------------------------


def test_own_stamps_and_filters(ctx):
    value = {}
    assert h._own(ctx, value) == {"owner": "alice"}
    assert value["metadata"]["owner"] == "alice"


def test_own_survives_explicit_null_metadata(ctx):
    """Clients send `metadata: null`; setdefault would return None and raise."""
    value = {"metadata": None}
    assert h._own(ctx, value) == {"owner": "alice"}
    assert value["metadata"] == {"owner": "alice"}


def test_own_preserves_existing_metadata(ctx):
    value = {"metadata": {"trip": "kyoto"}}
    h._own(ctx, value)
    assert value["metadata"] == {"trip": "kyoto", "owner": "alice"}


async def test_threads_and_crons_are_owner_scoped(ctx):
    """Called the way Aegra calls them: `handler(ctx=..., value=...)`.

    Keyword arguments are not a style choice here. `auth_handlers.py` invokes
    every registered handler with both names, so a handler that only accepts
    them positionally would still pass a positional test and fail in the
    server. Matching the real call convention is the point of the test.
    """
    for fn in (h.owns_threads, h.owns_crons, h.owns_store):
        assert await fn(ctx=ctx, value={}) == {"owner": "alice"}


async def test_assistant_create_is_owner_scoped(ctx):
    assert await h.restrict_assistant_create(ctx=ctx, value={}) == {"owner": "alice"}


async def test_assistant_delete_is_owner_scoped(ctx):
    assert await h.restrict_assistant_delete(ctx=ctx, value={}) == {"owner": "alice"}


def test_no_global_handler_is_registered():
    """A global @auth.on filters assistant reads too, hiding the server's graphs.

    Aegra creates its five default assistants with user_id="system" and no
    `owner` metadata, so a global owner filter matches none of them and
    /assistants/search returns an empty 200 — a silent failure that looks
    exactly like a healthy server with no graphs configured.
    """
    import inspect

    src = inspect.getsource(h)
    assert "@auth.on\n" not in src, "a global @auth.on hides the default assistants"
    assert "@auth.on.assistants.read" not in src, "assistants must stay readable"
