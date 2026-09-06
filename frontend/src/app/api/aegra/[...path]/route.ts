/**
 * Proxy between the browser and Aegra.
 *
 * Everything the UI does goes through here for three reasons: the Aegra URL and
 * any bearer token stay server-side, there is no CORS to configure, and the
 * browser talks to one origin regardless of where Aegra is deployed.
 *
 * SSE is passed straight through rather than buffered — the whole point of the
 * run stream is that events arrive as the graph produces them, so the response
 * body is forwarded unread.
 */

import { NextRequest } from "next/server";

const AEGRA_URL = process.env.AEGRA_URL ?? "http://127.0.0.1:2026";
const AEGRA_TOKEN = process.env.AEGRA_API_TOKEN ?? "";

/** Streaming must not be pre-rendered or cached. */
export const dynamic = "force-dynamic";

function upstreamHeaders(req: NextRequest): HeadersInit {
  const headers: Record<string, string> = {
    "Content-Type": req.headers.get("content-type") ?? "application/json",
    Accept: req.headers.get("accept") ?? "application/json",
  };
  if (AEGRA_TOKEN) headers.Authorization = `Bearer ${AEGRA_TOKEN}`;
  return headers;
}

async function forward(req: NextRequest, path: string[]) {
  const target = `${AEGRA_URL}/${path.join("/")}${req.nextUrl.search}`;
  const isStream = path[path.length - 1] === "stream";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers: upstreamHeaders(req),
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
      // Without this, Node buffers the SSE body and events arrive in one burst
      // when the run finishes — which defeats the purpose of streaming.
      // @ts-expect-error duplex is required by Node's fetch for streaming bodies
      duplex: "half",
      cache: "no-store",
    });
  } catch (err) {
    return Response.json(
      {
        error: "Cannot reach the Aegra server.",
        detail: err instanceof Error ? err.message : String(err),
        aegra_url: AEGRA_URL,
        hint: "Start it with ./scripts/run_aegra.sh",
      },
      { status: 502 },
    );
  }

  if (isStream && upstream.body) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  }

  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}

export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(req, (await ctx.params).path);
}
