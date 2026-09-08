"use client";

import { useEffect, useRef } from "react";
import type { RunEvent } from "@/lib/types";

/**
 * Everything the run did, as it did it.
 *
 * This is the readable half of the live view: the screenshots show *where* the
 * browser is, and this says *why* — which agent asked, which site refused,
 * what it clicked. Typed text never appears here; the run redacts it before
 * emitting, because someone taking over a login types into the same browser
 * this is describing.
 */
export function ActionLog({ events }: { events: RunEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  const shown = events.filter((e) => e.kind !== "agent_finished");

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [shown.length]);

  if (shown.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center">
        <p className="text-xs text-muted">
          Nothing yet. Start a run and every step appears here as it happens.
        </p>
      </div>
    );
  }

  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <header className="flex items-baseline justify-between border-b border-line px-3 py-2">
        <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Activity</h2>
        <span className="font-mono text-[11px] text-muted">{shown.length} events</span>
      </header>
      <ol className="max-h-[52vh] space-y-0.5 overflow-y-auto px-3 py-2">
        {shown.map((e) => (
          <li key={e.seq} className="flex items-baseline gap-2 text-xs leading-relaxed">
            <span className="w-10 shrink-0 font-mono text-[10px] text-muted/50">
              {clock(e.ts)}
            </span>
            <span className={`shrink-0 ${tone(e)}`}>{icon(e)}</span>
            <span className="min-w-0 flex-1 text-muted">{describe(e)}</span>
          </li>
        ))}
        <div ref={endRef} />
      </ol>
    </section>
  );
}

function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], {
    minute: "2-digit",
    second: "2-digit",
  });
}

function icon(e: RunEvent): string {
  switch (e.kind) {
    case "agent_started":
      return "▸";
    case "agent_failed":
      return "✕";
    case "browser_action":
      return "→";
    case "browser_frame":
      return "▪";
    case "browser_blocked":
      return "⊘";
    case "needs_human":
      return "!";
    default:
      return "·";
  }
}

function tone(e: RunEvent): string {
  switch (e.kind) {
    case "agent_failed":
      return "text-danger";
    case "browser_blocked":
      return "text-warn";
    case "needs_human":
      return "text-warn";
    case "browser_action":
      return "text-info";
    case "phase":
      return "text-accent-dim";
    default:
      return "text-muted/50";
  }
}

function describe(e: RunEvent): string {
  switch (e.kind) {
    case "agent_started":
      return `${e.agent} started (${e.tier} tier)`;
    case "agent_failed":
      return `${e.agent} failed — ${e.error ?? "unknown"}`;
    case "browser_action":
      return `${e.action}${e.detail ? ` — ${e.detail}` : ""}`;
    case "browser_frame":
      return e.note ? `screenshot — ${e.note}` : "screenshot";
    case "browser_blocked":
      return `${e.target}: ${e.reason ?? "refused an automated visitor"}`;
    case "needs_human":
      return e.prompt ?? "waiting for a person";
    case "phase":
      return e.detail ? `${e.name} — ${e.detail}` : (e.name ?? "");
    default:
      return e.kind;
  }
}
