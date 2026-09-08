"use client";

import { ActionLog } from "@/components/ActionLog";
import { BrowserStage } from "@/components/BrowserStage";
import { ResearchPanel } from "@/components/ResearchPanel";
import { RunTimeline } from "@/components/RunTimeline";
import type { Run } from "@/lib/useRun";

/**
 * The run while it is running.
 *
 * The browser leads because it is the only part that is genuinely worth
 * watching in real time — an agent thinking for two seconds does not need a
 * stage. For the versions that never open a browser, the timeline takes the
 * width instead of leaving a hole where a screenshot would be.
 */
export function LiveView({ run }: { run: Run }) {
  const browsing = run.version?.live_research ?? false;
  const notes = run.state.research_notes ?? [];

  if (run.phase === "idle" && run.events.length === 0) {
    return (
      <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-line px-6 py-16 text-center">
        <div className="max-w-md space-y-2">
          <p className="text-sm text-muted">Nothing is running.</p>
          <p className="text-xs leading-relaxed text-muted/70">
            Start a trip and this fills with what the graph is doing — which agent is
            working, what the browser is looking at, and which sites refused it.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className={browsing ? "grid gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]" : "grid gap-4 lg:grid-cols-2"}>
      <div className="min-w-0 space-y-4">
        {browsing && <BrowserStage frames={run.frames} threadId={run.threadId} />}
        <ActionLog events={run.events} />
      </div>

      <div className="min-w-0 space-y-4">
        <div className="rounded-lg border border-line bg-surface p-3">
          <RunTimeline
            version={run.version}
            runs={run.state.agent_runs ?? []}
            errors={run.state.errors ?? []}
            running={run.busy}
          />
        </div>
        {notes.length > 0 && <ResearchPanel notes={notes} />}
      </div>
    </div>
  );
}
