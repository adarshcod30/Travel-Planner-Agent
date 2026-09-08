"""Aegra authentication handler.

Aegra calls `@auth.authenticate` on every request and uses the returned
identity to scope threads, runs and assistants — so the identity is not just a
gate, it is the tenancy boundary. Two modes, chosen by `AUTH_TYPE`:

**noop** (default, local development) — every caller is the same
`local-dev` user. Threads are shared, which is what you want when you are
switching between a terminal, the frontend and a test script against one
database.

**token** — a shared bearer token from `AEGRA_API_TOKEN`, with the caller's
identity taken from an optional `X-User-Id` header. This is deliberately
modest: it is enough to stop an open port on a shared network from being
anonymously writable, and it is not a substitute for real OIDC. The structure
here is the part that matters — swapping in JWT verification means replacing
the body of `authenticate`, not rewiring the app.

The authorization handler below runs after authentication and stamps the
owner onto every resource the caller creates, then filters reads by it.
"""

import os
from typing import Any, cast

from langgraph_sdk import Auth

from travel_planner.core.logging import get_logger

log = get_logger(__name__)

auth = Auth()

AUTH_TYPE = os.getenv("AUTH_TYPE", "noop").lower()
API_TOKEN = os.getenv("AEGRA_API_TOKEN", "")
DEV_IDENTITY = "local-dev"


@auth.authenticate
async def authenticate(headers: dict[bytes, bytes]) -> dict[str, Any]:
    """Resolve the caller. Raising `Auth.exceptions.HTTPException` rejects."""
    if AUTH_TYPE == "noop":
        return {
            "identity": DEV_IDENTITY,
            "display_name": "Local developer",
            "is_authenticated": True,
        }

    provided = _header(headers, b"authorization").removeprefix("Bearer ").strip()
    if not API_TOKEN or provided != API_TOKEN:
        log.warning("auth_rejected", reason="missing or incorrect bearer token")
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Invalid or missing bearer token"
        )

    identity = _header(headers, b"x-user-id") or "api-user"
    return {"identity": identity, "display_name": identity, "is_authenticated": True}


def _header(headers: dict[bytes, bytes], name: bytes) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value.decode() if isinstance(value, bytes) else str(value)
    return ""


# --------------------------------------------------------------------------
# Authorization
#
# The scope here is deliberate, and getting it wrong fails silently.
#
# Threads, runs and crons are user data: each belongs to whoever created it,
# and one caller must not read or resume another's. Returning a filter dict
# makes Aegra use it both as the metadata stamped on create and as the
# predicate applied on search.
#
# Assistants are NOT user data. Aegra creates one per graph at startup, owned
# by "system" and carrying no `owner` metadata — they are five server-defined
# graphs, identical for every caller. A global `@auth.on` that filters
# everything by owner therefore matches zero assistants and makes the entire
# API's graph list invisible, while /health stays green and
# `POST /assistants/search` returns a perfectly valid empty list. Assistants
# are left readable, with only the mutating operations restricted.
# --------------------------------------------------------------------------


def _own(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Stamp the owner onto the payload and return the matching read filter.

    `setdefault` is wrong here: clients routinely send `metadata: null`
    explicitly, and `setdefault` only fills a key that is *absent*, so it
    happily returns None and the next line raises. The key has to be checked
    for a None value, not just for presence.
    """
    metadata = value.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        value["metadata"] = metadata
    metadata["owner"] = ctx.user.identity
    return {"owner": ctx.user.identity}


@auth.on.threads
async def owns_threads(*, ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Threads, and the runs inside them, belong to their creator."""
    return _own(ctx, value)


@auth.on.crons
async def owns_crons(*, ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Scheduled runs belong to whoever scheduled them."""
    return _own(ctx, value)


@auth.on.store
async def owns_store(*, ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Anything written to the semantic store is scoped to its writer."""
    return _own(ctx, value)


@auth.on.assistants.create
async def restrict_assistant_create(
    *, ctx: Auth.types.AuthContext, value: Auth.types.AssistantsCreate
) -> dict[str, str]:
    """A caller-created assistant is theirs; the server's defaults stay public."""
    return _own(ctx, cast(dict[str, Any], value))


@auth.on.assistants.delete
async def restrict_assistant_delete(
    *, ctx: Auth.types.AuthContext, value: Auth.types.AssistantsDelete
) -> dict[str, str]:
    return {"owner": ctx.user.identity}
