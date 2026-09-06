"use client";

import type { AgentError, AgentRun, VersionMeta } from "@/lib/types";

/**
 * Per-agent telemetry for the current run.
 *
 * Every agent the selected version *can* run is listed from the start, so the
 * shape of the version is visible before anything executes and it is obvious
 * which agents a targeted revision skipped. Bars are scaled against the slowest
 * agent in the run, which is what makes the model tiering legible: the Pro-tier
 * itinerary agent dominates, and the Micro-tier lookups barely register.
 */
export function RunTimeline({
  version,
  runs,
  errors,
  running,
}: {
  version?: VersionMeta;
  runs: AgentRun[];
  errors: AgentError[];
  running: boolean;
}) {
  const expected = version?.agents ?? [];
  const slowest = Math.max(1, ...runs.map((r) => r.duration_ms));
  const byAgent = new Map<string, AgentRun[]>();
  for (const r of runs) byAgent.set(r.agent, [...(byAgent.get(r.agent) ?? []), r]);
  const failed = new Set(errors.map((e) => e.agent));

  const totalMs = runs.reduce((s, r) => s + r.duration_ms, 0);
  const totalIn = runs.reduce((s, r) => s + r.input_tokens, 0);
  const totalOut = runs.reduce((s, r) => s + r.output_tokens, 0);

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Agents</h2>
        {runs.length > 0 && (
          <span className="font-mono text-[11px] text-muted">
            {runs.length} calls · {(totalMs / 1000).toFixed(1)}s · {totalIn.toLocaleString()}/{totalOut.toLocaleString()} tok
          </span>
        )}
      </div>

      <div className="space-y-1">
        {expected.map((agent) => {
          const calls = byAgent.get(agent) ?? [];
          const last = calls[calls.length - 1];
          const didFail = failed.has(agent);
          const pending = !last && !didFail;

          return (
            <div
              key={agent}
              className={[
                "flex items-center gap-2.5 rounded border px-2.5 py-1.5 text-xs transition-colors",
                didFail ? "border-danger/40 bg-danger/5" : last ? "border-line bg-surface" : "border-line/50 bg-transparent",
              ].join(" ")}
            >
              <span
                className={[
                  "h-1.5 w-1.5 shrink-0 rounded-full",
                  didFail ? "bg-danger" : last ? "bg-accent" : running ? "running-dot bg-muted" : "bg-line",
                ].join(" ")}
              />
              <span className={`w-24 shrink-0 truncate ${last || didFail ? "text-body" : "text-muted/60"}`}>
                {agent}
              </span>

              {last ? (
                <>
                  <TierBadge tier={last.tier} />
                  <div className="h-1 flex-1 overflow-hidden rounded-full bg-raised">
                    <div
                      className="h-full rounded-full bg-accent-dim/70"
                      style={{ width: `${Math.max(3, (last.duration_ms / slowest) * 100)}%` }}
                    />
                  </div>
                  <span className="w-14 shrink-0 text-right font-mono text-[10px] text-muted">
                    {(last.duration_ms / 1000).toFixed(1)}s
                  </span>
                  <span className="w-20 shrink-0 text-right font-mono text-[10px] text-muted/70">
                    {last.input_tokens}/{last.output_tokens}
                  </span>
                  {calls.length > 1 && (
                    <span
                      className="shrink-0 rounded bg-info/15 px-1 text-[10px] text-info"
                      title="Re-run by the orchestrator"
                    >
                      ×{calls.length}
                    </span>
                  )}
                  {last.repairs > 0 && (
                    <span
                      className="shrink-0 rounded bg-warn/15 px-1 text-[10px] text-warn"
                      title="Structured output needed a repair prompt"
                    >
                      repair
                    </span>
                  )}
                  {last.escalated && (
                    <span
                      className="shrink-0 rounded bg-warn/20 px-1 text-[10px] text-warn"
                      title="Escalated to a higher model tier"
                    >
                      escalated
                    </span>
                  )}
                </>
              ) : (
                <span className="flex-1 text-[10px] text-muted/50">
                  {didFail ? "failed" : pending && running ? "waiting" : "not run"}
                </span>
              )}
            </div>
          );
        })}
      </div>

      {errors.length > 0 && (
        <div className="space-y-1 rounded border border-danger/40 bg-danger/5 p-2.5">
          {errors.map((e, i) => (
            <p key={i} className="text-xs text-danger">
              <span className="font-medium">{e.agent}</span> — {e.error_type}: {e.message.slice(0, 160)}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

function TierBadge({ tier }: { tier: string }) {
  const color =
    tier === "high" ? "bg-accent/15 text-accent"
    : tier === "mid" ? "bg-info/15 text-info"
    : tier === "fallback" ? "bg-warn/15 text-warn"
    : "bg-raised text-muted";
  return <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] ${color}`}>{tier}</span>;
}
