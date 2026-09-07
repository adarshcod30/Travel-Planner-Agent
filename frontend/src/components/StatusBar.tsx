"use client";

import type { RunPhase, TripState } from "@/lib/types";

/** A one-line summary of where the run is and what it has decided so far. */
export function StatusBar({
  phase,
  state,
  elapsed,
  error,
}: {
  phase: RunPhase;
  state: TripState;
  elapsed: number;
  error?: string;
}) {
  const dest = state.destination;
  // The decision survives in state after the run ends, so a finished plan would
  // otherwise read "Complete ... re-running budget" — describing work that
  // already happened as if it were still in flight.
  const decision = phase === "running" ? state.orchestrator_decision : null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border border-line bg-surface px-3 py-2 text-xs">
      <span className="flex items-center gap-1.5">
        <span
          className={[
            "h-1.5 w-1.5 rounded-full",
            phase === "running" ? "running-dot bg-accent"
            : phase === "interrupted" ? "bg-warn"
            : phase === "done" ? "bg-accent"
            : phase === "error" ? "bg-danger"
            : "bg-line",
          ].join(" ")}
        />
        <span className={phase === "error" ? "text-danger" : "text-body"}>
          {phase === "idle" ? "Ready"
            : phase === "running" ? "Planning"
            : phase === "interrupted" ? "Awaiting your decision"
            : phase === "done" ? "Complete"
            : "Failed"}
        </span>
      </span>

      {elapsed > 0 && <span className="font-mono text-muted">{(elapsed / 1000).toFixed(1)}s</span>}

      {dest && (
        <span className="text-muted">
          → <span className="text-bright">{dest.city}, {dest.country}</span>
        </span>
      )}

      {state.budget && (
        <span className="text-muted">
          <span className="text-bright">
            {state.budget.currency === "INR"
              ? `\u20b9${state.budget.total.toLocaleString("en-IN")}`
              : `${state.budget.currency} ${state.budget.total.toLocaleString()}`}
          </span>
        </span>
      )}

      {typeof state.iteration === "number" && state.iteration > 0 && (
        <span className="text-info">revision {state.iteration}</span>
      )}

      {decision && decision.agents_to_rerun.length > 0 && (
        <span className="text-info" title={decision.reasoning}>
          re-running {decision.agents_to_rerun.join(", ")}
        </span>
      )}

      {error && <span className="text-danger">{error}</span>}
    </div>
  );
}
