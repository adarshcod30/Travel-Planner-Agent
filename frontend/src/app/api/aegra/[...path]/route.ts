/**
 * Proxy between the browser and Aegra.
 *
 * Everything the UI does goes through here for three reasons: the Aegra URL and
 * any bearer token stay server-side, there is no CORS to configure, and the
 * browser talks to one origin regardless of where Aegra is deployed.
 *
 * Nothing here reads the response body. SSE needs that because the point of a
 * run stream is that events arrive as the graph produces them — but so do the
 * browser screenshots, and for a sharper reason: `await res.text()` decodes
 * bytes as UTF-8, and a JPEG is not UTF-8. Every invalid sequence becomes
 * U+FFFD, so the reply keeps its status, its content-type and roughly its
 * length, and is no longer an image. Nothing errors; the picture is simply
 * blank. Forwarding the stream is both faster and the only correct thing.
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

  const headers = new Headers({
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  });
  if (isStream) {
    headers.set("Content-Type", "text/event-stream");
    headers.set("Cache-Control", "no-cache, no-transform");
    headers.set("Connection", "keep-alive");
  } else if (upstream.headers.get("cache-control")) {
    // Frames are immutable once written and are served with a long max-age.
    // Dropping it would make the filmstrip refetch every screenshot on every
    // render.
    headers.set("Cache-Control", upstream.headers.get("cache-control")!);
  }
  return new Response(upstream.body, { status: upstream.status, headers });
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
