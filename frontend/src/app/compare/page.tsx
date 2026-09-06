"use client";

import { useEffect, useState } from "react";
import { createThread, getThreadState, listVersions, streamRun } from "@/lib/aegra";
import { Markdown } from "@/lib/markdown";
import type { TripRequest, TripState, VersionMeta } from "@/lib/types";

/**
 * Run one request through two versions and put the results side by side.
 *
 * This is the screen that makes the project's premise checkable rather than
 * asserted. The same trip, the same models, the same specialists — only the
 * topology differs, so any difference in latency, token spend or output quality
 * is attributable to the architecture and nothing else.
 *
 * Versions that pause for a human are run to their gate and then accepted
 * automatically, since the comparison is about the graph, not about how long a
 * person took to click.
 */

const DEFAULT_TRIP: TripRequest = {
  request: "Temples and food in Kyoto",
  days: 3,
  interests: ["temples", "food"],
  budget_level: "mid-range",
  season: "November",
  travelers: 2,
};

interface Result {
  state: TripState;
  wallMs: number;
  error?: string;
}

export default function ComparePage() {
  const [versions, setVersions] = useState<VersionMeta[]>([]);
  const [left, setLeft] = useState("v2_parallel");
  const [right, setRight] = useState("v5_mcp");
  const [trip, setTrip] = useState<TripRequest>(DEFAULT_TRIP);
  const [results, setResults] = useState<Record<string, Result | "running">>({});

  useEffect(() => {
    listVersions().then(({ versions }) => setVersions(versions)).catch(() => {});
  }, []);

  const running = Object.values(results).some((r) => r === "running");

  async function runOne(graphId: string): Promise<Result> {
    const meta = versions.find((v) => v.graph_id === graphId);
    if (!meta) return { state: {}, wallMs: 0, error: "unknown version" };

    const started = performance.now();
    try {
      const { thread_id } = await createThread();
      for await (const _ of streamRun(thread_id, meta.assistant_id, { input: trip })) void _;

      // A gated version stops at its interrupt; accept it so the comparison
      // measures the graph rather than the reviewer's reaction time.
      let snapshot = await getThreadState(thread_id);
      let guard = 0;
      while (snapshot.next.length && snapshot.tasks?.[0]?.interrupts?.length && guard++ < 3) {
        for await (const _ of streamRun(thread_id, meta.assistant_id, {
          command: { resume: [{ type: "accept" }] },
        })) void _;
        snapshot = await getThreadState(thread_id);
      }
      return { state: snapshot.values, wallMs: performance.now() - started };
    } catch (e) {
      return { state: {}, wallMs: performance.now() - started, error: e instanceof Error ? e.message : String(e) };
    }
  }

  async function compare() {
    setResults({ [left]: "running", [right]: "running" });
    // Concurrent on purpose: the two runs are independent, and running them
    // together halves the wait without affecting either one's own timing.
    const [l, r] = await Promise.all([runOne(left), runOne(right)]);
    setResults({ [left]: l, [right]: r });
  }

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-line bg-surface p-4">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_1fr_auto] md:items-end">
          <Picker label="Version A" versions={versions} value={left} onChange={setLeft} disabled={running} />
          <span className="hidden pb-2 text-center text-xs text-muted md:block">vs</span>
          <Picker label="Version B" versions={versions} value={right} onChange={setRight} disabled={running} />
          <button
            onClick={compare}
            disabled={running || !versions.length || left === right}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {running ? "Running both…" : "Run both"}
          </button>
        </div>

        <label className="mt-3 block">
          <span className="mb-1.5 block text-[11px] font-medium tracking-wide text-muted uppercase">
            The same request goes to both
          </span>
          <input
            value={trip.request}
            onChange={(e) => setTrip({ ...trip, request: e.target.value })}
            disabled={running}
            className="w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-body focus:border-accent/50 focus:outline-none disabled:opacity-50"
          />
        </label>
        {left === right && (
          <p className="mt-2 text-xs text-warn">Pick two different versions to compare.</p>
        )}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {[left, right].map((graphId, i) => (
          <Column
            key={`${graphId}-${i}`}
            meta={versions.find((v) => v.graph_id === graphId)}
            result={results[graphId]}
            other={results[graphId === left ? right : left]}
          />
        ))}
      </div>
    </div>
  );
}

function Picker({
  label, versions, value, onChange, disabled,
}: {
  label: string; versions: VersionMeta[]; value: string;
  onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-medium tracking-wide text-muted uppercase">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        className="w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-body focus:border-accent/50 focus:outline-none disabled:opacity-50"
      >
        {versions.map((v) => (
          <option key={v.graph_id} value={v.graph_id}>{v.label}</option>
        ))}
      </select>
    </label>
  );
}

function Column({
  meta, result, other,
}: {
  meta?: VersionMeta; result?: Result | "running"; other?: Result | "running";
}) {
  if (!meta) return null;

  const done = result && result !== "running" ? result : null;
  const runs = done?.state.agent_runs ?? [];
  const tokens = runs.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0);
  const agentMs = runs.reduce((s, r) => s + r.duration_ms, 0);

  const otherDone = other && other !== "running" ? other : null;
  const otherTokens = (otherDone?.state.agent_runs ?? []).reduce(
    (s, r) => s + r.input_tokens + r.output_tokens, 0,
  );

  return (
    <div className="space-y-3 rounded-lg border border-line bg-surface p-4">
      <div>
        <h2 className="text-sm font-semibold text-bright">{meta.label}</h2>
        <p className="text-xs text-muted">{meta.headline}</p>
      </div>

      {result === "running" && <p className="text-xs text-accent">running…</p>}
      {done?.error && <p className="text-xs text-danger">{done.error}</p>}

      {done && !done.error && (
        <>
          <div className="grid grid-cols-4 gap-2">
            <Metric label="wall clock" value={`${(done.wallMs / 1000).toFixed(1)}s`}
              delta={otherDone ? done.wallMs - otherDone.wallMs : undefined} unit="s" lowerIsBetter />
            <Metric label="agent time" value={`${(agentMs / 1000).toFixed(1)}s`} />
            <Metric label="agent calls" value={String(runs.length)} />
            <Metric label="tokens" value={tokens.toLocaleString()}
              delta={otherTokens ? tokens - otherTokens : undefined} lowerIsBetter />
          </div>

          {agentMs > done.wallMs && (
            <p className="rounded bg-accent/10 px-2.5 py-1.5 text-[11px] text-accent-dim">
              Ran {(agentMs / 1000).toFixed(1)}s of agent work in {(done.wallMs / 1000).toFixed(1)}s —
              parallelism saved {((agentMs - done.wallMs) / 1000).toFixed(1)}s.
            </p>
          )}

          {done.state.review && (
            <p className="text-xs text-muted">
              auditor:{" "}
              <span className={done.state.review.verdict === "approved" ? "text-accent" : "text-warn"}>
                {done.state.review.verdict.replace("_", " ")}
              </span>
              {done.state.review.issues.length > 0 && ` · ${done.state.review.issues.length} issue(s)`}
            </p>
          )}

          <div className="max-h-[28rem] overflow-y-auto rounded border border-line bg-ink px-3 py-2">
            {done.state.final_plan
              ? <Markdown source={done.state.final_plan} />
              : <p className="text-xs text-muted">no plan produced</p>}
          </div>
        </>
      )}

      {!result && <p className="text-xs text-muted/60">not run yet</p>}
    </div>
  );
}

function Metric({
  label, value, delta, unit, lowerIsBetter,
}: {
  label: string; value: string; delta?: number; unit?: string; lowerIsBetter?: boolean;
}) {
  const show = delta !== undefined && Math.abs(delta) > (unit === "s" ? 200 : 50);
  const better = lowerIsBetter ? (delta ?? 0) < 0 : (delta ?? 0) > 0;
  return (
    <div className="rounded border border-line bg-ink px-2 py-1.5">
      <p className="text-[10px] tracking-wide text-muted uppercase">{label}</p>
      <p className="font-mono text-sm text-bright">{value}</p>
      {show && (
        <p className={`font-mono text-[10px] ${better ? "text-accent" : "text-warn"}`}>
          {delta! > 0 ? "+" : ""}
          {unit === "s" ? `${(delta! / 1000).toFixed(1)}s` : delta!.toLocaleString()}
        </p>
      )}
    </div>
  );
}
