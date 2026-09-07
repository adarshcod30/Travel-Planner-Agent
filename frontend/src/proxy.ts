/**
 * Gate every request when APP_ACCESS_CODE is set.
 *
 * A proxy (Next 16's replacement for middleware) rather than per-route checks,
 * because the route that actually matters is `/api/aegra/*` — that is the one
 * that spends money. Protecting only the pages would leave the expensive path
 * wide open to anyone who reads the network tab.
 */

import { NextRequest, NextResponse } from "next/server";
import { COOKIE_NAME, codeMatches, gateEnabled } from "@/lib/access";

export function proxy(req: NextRequest) {
  if (!gateEnabled()) return NextResponse.next();

  if (codeMatches(req.cookies.get(COOKIE_NAME)?.value)) return NextResponse.next();

  // An unauthenticated API call gets a 401, not a redirect to an HTML page —
  // the client is fetch(), and a 302 to markup would surface as a confusing
  // parse error rather than "you are not signed in".
  if (req.nextUrl.pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "Access code required" }, { status: 401 });
  }

  const url = req.nextUrl.clone();
  url.pathname = "/enter";
  url.search = "";
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the entry page itself, the endpoint that validates the
  // code, and Next's own static assets.
  matcher: ["/((?!enter|api/enter|_next/static|_next/image|favicon.ico).*)"],
};
