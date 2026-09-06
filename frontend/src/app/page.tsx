"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { HitlPanel } from "@/components/HitlPanel";
import { ResearchPanel } from "@/components/ResearchPanel";
import { RunTimeline } from "@/components/RunTimeline";
import { StatusBar } from "@/components/StatusBar";
import { TripForm } from "@/components/TripForm";
import { VersionSwitcher } from "@/components/VersionSwitcher";
import { createThread, getThreadState, listVersions, streamRun } from "@/lib/aegra";
import { Markdown } from "@/lib/markdown";
import type {
  PlanReviewInterrupt,
  RunPhase,
  TripRequest,
  TripState,
  VersionMeta,
} from "@/lib/types";

export default function PlannerPage() {
  const [versions, setVersions] = useState<VersionMeta[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [state, setState] = useState<TripState>({});
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [interrupt, setInterrupt] = useState<PlanReviewInterrupt | null>(null);
  const [error, setError] = useState<string>();
  const [elapsed, setElapsed] = useState(0);
  const threadRef = useRef<string | null>(null);
  const startedRef = useRef(0);

  const version = versions.find((v) => v.graph_id === selected);
  const busy = phase === "running";

  useEffect(() => {
    listVersions()
      .then(({ versions, default: def }) => {
        setVersions(versions);
        setSelected(def);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // A live elapsed counter while the graph is executing.
  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => setElapsed(Date.now() - startedRef.current), 100);
    return () => clearInterval(id);
  }, [phase]);

  /**
   * Consume a run's SSE stream.
   *
   * Aegra emits the whole state on every `values` event, so the UI simply
   * replaces its copy — no patching, and no chance of the client's view
   * drifting from the server's. When the stream ends the thread state is read
   * back once, authoritatively, because that is where a pending interrupt
   * lives (it is not part of `values`).
   */
  const consume = useCallback(
    async (threadId: string, body: Parameters<typeof streamRun>[2]) => {
      setPhase("running");
      setError(undefined);
      startedRef.current = startedRef.current || Date.now();

      try {
        for await (const ev of streamRun(threadId, version!.assistant_id, body)) {
          if (ev.event === "error") {
            setError(typeof ev.data === "string" ? ev.data : JSON.stringify(ev.data));
            continue;
          }
          if (ev.data && typeof ev.data === "object" && !Array.isArray(ev.data)) {
            const values = ev.data as TripState;
            if ("agent_runs" in values || "destination" in values || "final_plan" in values) {
              setState((prev) => ({ ...prev, ...values }));
            }
          }
        }

        const snapshot = await getThreadState(threadId);
        setState(snapshot.values);
        const pending = snapshot.tasks?.[0]?.interrupts?.[0]?.value;
        if (snapshot.next.length && pending) {
          setInterrupt(pending);
          setPhase("interrupted");
        } else {
          setInterrupt(null);
          setPhase("done");
          setElapsed(Date.now() - startedRef.current);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    },
    [version],
  );

  const plan = useCallback(
    async (trip: TripRequest) => {
      if (!version) return;
      setState({});
      setInterrupt(null);
      setElapsed(0);
      startedRef.current = Date.now();
      try {
        const thread = await createThread();
        threadRef.current = thread.thread_id;
        await consume(thread.thread_id, { input: trip });
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        setPhase("error");
      }
    },
    [consume, version],
  );

  const resume = useCallback(
    async (payload: { type: string; args?: unknown }) => {
      if (!threadRef.current) return;
      setInterrupt(null);
      await consume(threadRef.current, { command: { resume: [payload] } });
    },
    [consume],
  );

  return (
    <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
      <aside className="space-y-5">
        <section className="space-y-3">
          <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Version</h2>
          <VersionSwitcher
            versions={versions}
            selected={selected}
            onSelect={setSelected}
            disabled={busy || phase === "interrupted"}
          />
        </section>

        <section className="space-y-3">
          <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Trip</h2>
          <TripForm onSubmit={plan} disabled={busy || phase === "interrupted"} />
        </section>
      </aside>

      <section className="space-y-4">
        <StatusBar phase={phase} state={state} elapsed={elapsed} error={error} />

        {interrupt && <HitlPanel interrupt={interrupt} onResume={resume} busy={busy} />}

        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-4">
            {state.final_plan ? (
              <article className="rounded-lg border border-line bg-surface px-5 py-4">
                <Markdown source={state.final_plan} />
              </article>
            ) : (
              <Placeholder phase={phase} versionLabel={version?.label} />
            )}
          </div>

          <div className="space-y-4">
            <RunTimeline
              version={version}
              runs={state.agent_runs ?? []}
              errors={state.errors ?? []}
              running={busy}
            />
            {state.research_notes && state.research_notes.length > 0 && (
              <ResearchPanel notes={state.research_notes} />
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

function Placeholder({ phase, versionLabel }: { phase: RunPhase; versionLabel?: string }) {
  return (
    <div className="flex min-h-72 items-center justify-center rounded-lg border border-dashed border-line px-6 py-12 text-center">
      <div className="max-w-sm space-y-2">
        <p className="text-sm text-muted">
          {phase === "running"
            ? `${versionLabel ?? "The graph"} is working…`
            : phase === "error"
              ? "The run did not complete."
              : "Describe a trip and pick a version."}
        </p>
        {phase === "idle" && (
          <p className="text-xs leading-relaxed text-muted/70">
            Each version is a working system. Run the same request through more than one
            and the differences — parallelism, a self-audit loop, a human gate, live
            research — show up in the timeline on the right.
          </p>
        )}
      </div>
    </div>
  );
}
