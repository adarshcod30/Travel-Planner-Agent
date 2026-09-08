"use client";

import { useState } from "react";
import { ActionLog } from "@/components/ActionLog";
import { BrowserStage } from "@/components/BrowserStage";
import { ResearchPanel } from "@/components/ResearchPanel";
import { RunTimeline } from "@/components/RunTimeline";
import type { Run } from "@/lib/useRun";

/**
 * The run, while it is running.
 *
 * The first version of this put four panels side by side and left you to work
 * out which one mattered. It does not read as a dashboard; it reads as four
 * things competing. So there is one headline that says what is happening right
 * now in a sentence, the browser gets the width when there is a browser, and
 * the detail is behind tabs you open when you want it.
 *
 * For the versions that never open a browser there is nothing to watch, and
 * pretending otherwise with an empty stage is worse than saying so.
 */
type Detail = "activity" | "agents" | "research";

export function LiveView({ run }: { run: Run }) {
  const [detail, setDetail] = useState<Detail>("activity");
  const browsing = run.version?.live_research ?? false;
  const notes = run.state.research_notes ?? [];
  const runs = run.state.agent_runs ?? [];
  const errors = run.state.errors ?? [];

  if (run.phase === "idle" && run.events.length === 0) {
    return (
      <Empty>
        <p className="text-sm text-body">Nothing is running.</p>
        <p className="text-xs leading-relaxed text-muted">
          Start a trip and this fills with what the graph is doing — which agent is
          working, what the browser is looking at, and which sites turned it away.
        </p>
      </Empty>
    );
  }

  return (
    <div className="space-y-4">
      <Headline run={run} />

      <div className={browsing ? "grid gap-4 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]" : ""}>
        {browsing && (
          <div className="min-w-0">
            <BrowserStage frames={run.frames} threadId={run.threadId} />
          </div>
        )}

        <div className="min-w-0 space-y-3">
          <div className="flex gap-1 rounded-lg border border-line bg-surface p-1">
            <Tab on={detail === "activity"} onClick={() => setDetail("activity")}>
              Activity
              {run.events.length > 0 && <Count n={run.events.length} />}
            </Tab>
            <Tab on={detail === "agents"} onClick={() => setDetail("agents")}>
              Agents
              {runs.length > 0 && <Count n={runs.length} />}
            </Tab>
            <Tab on={detail === "research"} onClick={() => setDetail("research")}>
              Sources
              {notes.length > 0 && <Count n={notes.length} />}
            </Tab>
          </div>

          {detail === "activity" && <ActionLog events={run.events} />}
          {detail === "agents" && (
            <div className="rounded-lg border border-line bg-surface p-3">
              <RunTimeline
                version={run.version}
                runs={runs}
                errors={errors}
                running={run.busy}
              />
            </div>
          )}
          {detail === "research" &&
            (notes.length > 0 ? (
              <ResearchPanel notes={notes} />
            ) : (
              <Empty>
                <p className="text-xs leading-relaxed text-muted">
                  {browsing
                    ? "Nothing gathered yet. Sources appear here as the browser reads them."
                    : "This version does no live research — that is what v5 adds."}
                </p>
              </Empty>
            ))}
        </div>
      </div>
    </div>
  );
}

/**
 * One sentence for what is happening now.
 *
 * The single most useful thing on this screen, and it used to be a truncated
 * fragment in the corner of the header.
 */
function Headline({ run }: { run: Run }) {
  const runs = run.state.agent_runs ?? [];
  const done = run.phase === "done";
  const waiting = run.phase === "interrupted";

  return (
    <section
      className={[
        "rounded-xl border px-5 py-4",
        waiting ? "border-warn/40 bg-warn/5" : done ? "border-line bg-surface" : "border-accent/30 bg-accent/5",
      ].join(" ")}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="min-w-0 text-lg font-medium text-bright">
          {run.busy && <span className="running-dot mr-2 inline-block h-2 w-2 rounded-full bg-accent align-middle" />}
          {run.activity ??
            (waiting
              ? "Waiting for you"
              : done
                ? "Finished"
                : run.phase === "error"
                  ? "The run did not complete"
                  : "Working")}
        </p>
        <span className="shrink-0 font-mono text-xs text-muted">
          {(run.elapsed / 1000).toFixed(1)}s
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        <Stat label="version" value={run.version?.label ?? "—"} />
        <Stat label="agent calls" value={String(runs.length)} />
        <Stat
          label="tokens"
          value={runs.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0).toLocaleString()}
        />
        {run.frames.length > 0 && <Stat label="screenshots" value={String(run.frames.length)} />}
        {run.state.destination && (
          <Stat
            label="destination"
            value={`${run.state.destination.city}, ${run.state.destination.country}`}
          />
        )}
      </div>

      {run.error && <p className="mt-2 text-xs text-danger">{run.error}</p>}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span>
      <span className="text-muted/60">{label} </span>
      <span className="text-body">{value}</span>
    </span>
  );
}

function Tab({
  children,
  on,
  onClick,
}: {
  children: React.ReactNode;
  on: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      className={[
        "flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        on ? "bg-raised text-bright" : "text-muted hover:text-body",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function Count({ n }: { n: number }) {
  return <span className="font-mono text-[10px] text-muted">{n}</span>;
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-40 items-center justify-center rounded-xl border border-dashed border-line px-6 py-10 text-center">
      <div className="max-w-sm space-y-2">{children}</div>
    </div>
  );
}
