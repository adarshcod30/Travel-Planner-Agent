"use client";

import { useState } from "react";
import type { TripState } from "@/lib/types";

/**
 * What v5's research node actually found.
 *
 * The provenance line is the interesting part and is always visible: which
 * source answered, and which refused automated access before it. The page
 * excerpt underneath is what the specialists were given, collapsed by default
 * because it is raw accessibility tree — useful to inspect, unreadable to
 * scroll past.
 */
export function ResearchPanel({ notes }: { notes: NonNullable<TripState["research_notes"]> }) {
  return (
    <div className="space-y-2">
      <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Live research</h2>
      <div className="space-y-1.5">
        {notes.map((note, i) => (
          <Note key={i} note={note} />
        ))}
      </div>
    </div>
  );
}

function Note({ note }: { note: string }) {
  const [open, setOpen] = useState(false);
  const newline = note.indexOf("\n");
  const headline = newline === -1 ? note : note.slice(0, newline);
  const body = newline === -1 ? "" : note.slice(newline + 1).trim();

  const blocked = headline.includes("refused automated access");
  const failed = headline.includes("unavailable") || headline.includes("every source");

  return (
    <div className="rounded border border-line bg-surface">
      <button
        onClick={() => body && setOpen((o) => !o)}
        disabled={!body}
        className="flex w-full items-start gap-2 px-2.5 py-2 text-left disabled:cursor-default"
      >
        <span
          className={[
            "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
            failed ? "bg-danger" : blocked ? "bg-warn" : "bg-accent",
          ].join(" ")}
        />
        <span className="flex-1 text-xs leading-relaxed text-body">{headline}</span>
        {body && <span className="mt-0.5 shrink-0 text-[10px] text-muted">{open ? "hide" : "page"}</span>}
      </button>
      {open && body && (
        <pre className="max-h-56 overflow-auto border-t border-line bg-ink px-2.5 py-2 font-mono text-[10px] leading-relaxed whitespace-pre-wrap text-muted">
          {body}
        </pre>
      )}
    </div>
  );
}
