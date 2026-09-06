"use client";

import { useState } from "react";
import { Markdown } from "@/lib/markdown";
import type { PlanReviewInterrupt } from "@/lib/types";

/**
 * The human gate — v4 and v5's interrupt, rendered.
 *
 * The four actions map exactly onto the resume types the graph accepts:
 * accept, edit, response and ignore. The run is paused at a checkpoint in
 * Postgres while this is on screen, so answering it minutes or days later
 * resumes from precisely this point and re-runs nothing that came before.
 */
export function HitlPanel({
  interrupt,
  onResume,
  busy,
}: {
  interrupt: PlanReviewInterrupt;
  onResume: (payload: { type: string; args?: unknown }) => void;
  busy?: boolean;
}) {
  const [mode, setMode] = useState<"none" | "respond" | "edit">("none");
  const [feedback, setFeedback] = useState("");
  const [edited, setEdited] = useState(interrupt.draft);
  const review = interrupt.review;

  return (
    <div className="rounded-lg border border-warn/50 bg-warn/5">
      <div className="flex items-center justify-between border-b border-warn/25 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="running-dot h-1.5 w-1.5 rounded-full bg-warn" />
          <h2 className="text-sm font-semibold text-warn">Waiting for your decision</h2>
        </div>
        <span className="font-mono text-[11px] text-muted">
          revision {interrupt.iteration} · checkpointed
        </span>
      </div>

      {review && (
        <div className="border-b border-warn/20 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span
              className={[
                "rounded px-2 py-0.5 font-medium",
                review.verdict === "approved" ? "bg-accent/15 text-accent" : "bg-warn/20 text-warn",
              ].join(" ")}
            >
              auditor: {review.verdict.replace("_", " ")}
            </span>
            <Check ok={review.budget_realistic} label="budget realistic" />
            <Check ok={review.pacing_reasonable} label="pacing reasonable" />
          </div>
          {review.issues.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {review.issues.map((issue, i) => (
                <li key={i} className="text-xs text-muted">
                  • {issue}
                  {review.suggestions[i] && <span className="text-accent-dim"> → {review.suggestions[i]}</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="max-h-80 overflow-y-auto border-b border-warn/20 px-4 py-3">
        {mode === "edit" ? (
          <textarea
            value={edited}
            onChange={(e) => setEdited(e.target.value)}
            rows={18}
            className="w-full resize-y rounded border border-line bg-ink p-3 font-mono text-xs text-body focus:border-accent/50 focus:outline-none"
          />
        ) : (
          <Markdown source={interrupt.draft} />
        )}
      </div>

      <div className="space-y-2 px-4 py-3">
        {mode === "respond" && (
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={2}
            autoFocus
            placeholder="Fewer temples on day 2, add a food market, lower the hotel tier…"
            className="w-full resize-none rounded border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none"
          />
        )}

        <div className="flex flex-wrap gap-2">
          {mode === "none" && (
            <>
              <Action primary disabled={busy} onClick={() => onResume({ type: "accept" })}>
                Accept
              </Action>
              {interrupt.config.allow_respond && (
                <Action disabled={busy} onClick={() => setMode("respond")}>
                  Request changes
                </Action>
              )}
              {interrupt.config.allow_edit && (
                <Action disabled={busy} onClick={() => setMode("edit")}>
                  Edit directly
                </Action>
              )}
              {interrupt.config.allow_ignore && (
                <Action danger disabled={busy} onClick={() => onResume({ type: "ignore" })}>
                  Discard
                </Action>
              )}
            </>
          )}

          {mode === "respond" && (
            <>
              <Action
                primary
                disabled={busy || !feedback.trim()}
                onClick={() => onResume({ type: "response", args: feedback.trim() })}
              >
                Send to the orchestrator
              </Action>
              <Action disabled={busy} onClick={() => setMode("none")}>Cancel</Action>
            </>
          )}

          {mode === "edit" && (
            <>
              <Action
                primary
                disabled={busy || !edited.trim()}
                onClick={() => onResume({ type: "edit", args: { final_plan: edited } })}
              >
                Save as final
              </Action>
              <Action disabled={busy} onClick={() => setMode("none")}>Cancel</Action>
            </>
          )}
        </div>

        <p className="text-[11px] text-muted/70">
          {mode === "respond"
            ? "The orchestrator reads this and re-runs only the specialists it affects."
            : mode === "edit"
              ? "Your text becomes the final plan verbatim; no agent runs again."
              : "Accept finalizes as-is. Request changes routes back through the orchestrator."}
        </p>
      </div>
    </div>
  );
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? "text-accent-dim" : "text-danger"}>
      {ok ? "✓" : "✕"} {label}
    </span>
  );
}

function Action({
  children, onClick, disabled, primary, danger,
}: {
  children: React.ReactNode; onClick: () => void; disabled?: boolean; primary?: boolean; danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={[
        "rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        primary
          ? "bg-accent text-ink hover:opacity-90"
          : danger
            ? "border border-danger/40 text-danger hover:bg-danger/10"
            : "border border-line bg-raised text-body hover:border-muted/50",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
