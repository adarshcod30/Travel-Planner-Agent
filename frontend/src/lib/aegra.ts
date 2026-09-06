/**
 * Browser-side client for the planner, talking to our own /api/aegra proxy.
 *
 * Nothing here reaches Aegra directly. Every call goes through a Next.js route
 * handler, which means the Aegra URL and any bearer token stay on the server,
 * and there is no CORS configuration to keep in sync between two deployments.
 */

import type { ThreadState, TripRequest, TripState, VersionMeta } from "./types";

const API = "/api/aegra";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}${detail ? ` — ${detail.slice(0, 300)}` : ""}`);
  }
  return res.json() as Promise<T>;
}

export function listVersions(): Promise<{ versions: VersionMeta[]; default: string }> {
  return jsonFetch("/versions");
}

export function createThread(): Promise<{ thread_id: string }> {
  return jsonFetch("/threads", { method: "POST", body: JSON.stringify({}) });
}

export function getThreadState(threadId: string): Promise<ThreadState> {
  return jsonFetch(`/threads/${threadId}/state`);
}

export interface StreamEvent {
  event: string;
  data: unknown;
}

/**
 * Start a run and yield its SSE events as they arrive.
 *
 * Aegra streams `values` updates as the graph progresses; the caller decides
 * what to do with each. Errors mid-stream are yielded as an `error` event
 * rather than thrown, so a partially-complete run still renders what it got.
 */
export async function* streamRun(
  threadId: string,
  assistantId: string,
  body: { input?: TripRequest; command?: { resume: unknown } },
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API}/threads/${threadId}/runs/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ assistant_id: assistantId, stream_mode: ["values"], ...body }),
    signal,
  });

  if (!res.ok || !res.body) {
    yield { event: "error", data: `${res.status} ${res.statusText}` };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let eventName = "message";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; a frame may span reads.
    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        yield { event: eventName, data: JSON.parse(data) };
      } catch {
        yield { event: eventName, data };
      }
    }
  }
}

/** The final state after a stream finishes, read back authoritatively. */
export async function finalState(threadId: string): Promise<TripState> {
  return (await getThreadState(threadId)).values;
}
