"use client";

import { useCallback, useState } from "react";
import { HistoryView } from "@/components/HistoryView";
import { LiveView } from "@/components/LiveView";
import { PlanView } from "@/components/PlanView";
import { RunStatus, Shell, type ViewKey } from "@/components/Shell";
import { SetupView } from "@/components/SetupView";
import { completeTrip } from "@/lib/aegra";
import type { RunPhase, TripRequest } from "@/lib/types";
import { useRun } from "@/lib/useRun";

/**
 * The planner.
 *
 * All the state lives in `useRun`; this decides which of the four views you
 * are looking at, and follows the run to whatever needs you next. A badge
 * appearing on a tab you are not looking at is not a notification — it is a
 * thing you find later.
 *
 * The view is derived rather than stored, and that is what makes the follow
 * and the override coexist: a tab you click is remembered *along with the
 * phase you clicked it in*, so it holds while that stage lasts and gives way
 * the moment the run moves on to something new. No effect, no state to keep
 * in sync, and no chance of being yanked off a plan you are still reading.
 */
export default function PlannerPage() {
  const run = useRun();
  const [chosen, setChosen] = useState<{ view: ViewKey; duringPhase: RunPhase } | null>(null);

  const follows: ViewKey =
    run.phase === "running"
      ? "live"
      : run.phase === "interrupted" || run.phase === "done"
        ? "plan"
        : "setup";

  const view = chosen?.duringPhase === run.phase ? chosen.view : follows;

  const choose = useCallback(
    (v: ViewKey) => setChosen({ view: v, duringPhase: run.phase }),
    [run.phase],
  );

  const start = useCallback(
    async (trip: TripRequest) => {
      setChosen(null);
      await run.start(trip);
    },
    [run],
  );

  const finish = useCallback(async () => {
    if (run.threadId && run.version) {
      try {
        await completeTrip(run.threadId, run.version.graph_id, run.state);
      } catch {
        // Archiving is a convenience; failing it should not trap you on a
        // finished plan you have already read.
      }
    }
    run.reset();
    setChosen({ view: "history", duringPhase: "idle" });
  }, [run]);

  const dest = run.state.destination;

  return (
    <Shell
      view={view}
      onView={choose}
      badges={{
        live: run.busy ? "•" : undefined,
        plan:
          run.phase === "interrupted"
            ? "you"
            : run.state.final_plan
              ? "ready"
              : undefined,
      }}
      status={
        <RunStatus
          phase={run.phase}
          elapsed={run.elapsed}
          activity={run.activity}
          destination={dest ? `${dest.city}, ${dest.country}` : undefined}
          total={run.state.budget?.total}
          currency={run.state.budget?.currency}
          error={run.error}
        />
      }
    >
      {view === "setup" && (
        <SetupView
          versions={run.versions}
          selected={run.selected}
          onSelect={run.select}
          onSubmit={start}
          disabled={run.busy || run.phase === "interrupted"}
        />
      )}
      {view === "live" && <LiveView run={run} />}
      {view === "plan" && <PlanView run={run} onFinish={finish} />}
      {view === "history" && <HistoryView />}
    </Shell>
  );
}
