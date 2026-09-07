/** Validates the access code and sets the cookie the middleware checks. */

import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME, accessCode, codeMatches } from "@/lib/access";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { code } = (await req.json().catch(() => ({}))) as { code?: string };

  if (!codeMatches(code)) {
    // A uniform delay on failure blunts trivial brute-forcing of a short code.
    await new Promise((r) => setTimeout(r, 400));
    return NextResponse.json({ error: "invalid" }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(COOKIE_NAME, accessCode()!, {
    httpOnly: true,
    sameSite: "lax",
    // The tunnel is HTTPS; a plain-HTTP LAN session still needs this to work,
    // so it follows the scheme the request actually arrived on.
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  return res;
}
