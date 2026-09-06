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
from typing import Any

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


@auth.on
async def owns_resource(ctx: Auth.types.AuthContext, value: dict[str, Any]) -> dict[str, str]:
    """Stamp the owner on writes and filter reads to that owner.

    Returning a filter dict makes Aegra apply it as both the metadata written
    on create and the predicate applied on search, so a caller cannot read or
    resume another caller's thread.
    """
    metadata = value.setdefault("metadata", {})
    metadata["owner"] = ctx.user.identity
    return {"owner": ctx.user.identity}
