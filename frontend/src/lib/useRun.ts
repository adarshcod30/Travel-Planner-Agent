"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  createThread,
  getThreadState,
  listVersions,
  streamRun,
} from "@/lib/aegra";
import type {
  Frame,
  RunEvent,
  RunInterrupt,
  RunPhase,
  TripRequest,
  TripState,
  VersionMeta,
} from "@/lib/types";

/**
 * Everything one run does, in one place.
 *
 * This used to live inside the page component, which worked while a run was
 * "post a request, replace the state, render it". It stopped working when the
 * run started pushing screenshots and browser actions out mid-node: those
 * arrive on the same connection as the state, need accumulating rather than
 * replacing, and are read by three different views.
 *
 * Two streams, two rules:
 *
 * **`values`** — Aegra sends the whole state on every update, so the client
 * replaces its copy and cannot drift from the server's.
 *
 * **`custom`** — the run's own events, which are a log: they accumulate, in
 * `seq` order, and are never replaced.
 */
export interface Run {
  versions: VersionMeta[];
  version?: VersionMeta;
  selected: string;
  select: (graphId: string) => void;

  state: TripState;
  phase: RunPhase;
  error?: string;
  elapsed: number;
  threadId: string | null;

  events: RunEvent[];
  frames: Frame[];
  /** What the run is doing right now, in words. */
  activity?: string;

  interrupt: RunInterrupt | null;
  busy: boolean;

  start: (trip: TripRequest) => Promise<void>;
  resume: (payload: { type: string; args?: unknown }) => Promise<void>;
  reset: () => void;
}

const MAX_EVENTS = 500;

export function useRun(): Run {
  const [versions, setVersions] = useState<VersionMeta[]>([]);
  const [selected, setSelected] = useState("");
  const [state, setState] = useState<TripState>({});
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [error, setError] = useState<string>();
  const [elapsed, setElapsed] = useState(0);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [interrupt, setInterrupt] = useState<RunInterrupt | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);

  const startedRef = useRef(0);
  const version = versions.find((v) => v.graph_id === selected);
  const busy = phase === "running";

  useEffect(() => {
    listVersions()
      .then(({ versions, default: def }) => {
        setVersions(versions);
        setSelected((cur) => cur || def);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (phase !== "running") return;
    const id = setInterval(() => setElapsed(Date.now() - startedRef.current), 100);
    return () => clearInterval(id);
  }, [phase]);

  const ingest = useCallback((ev: RunEvent) => {
    setEvents((prev) => {
      const next = [...prev, ev];
      return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
    });
    if (ev.kind === "browser_frame" && ev.path) {
      setFrames((prev) =>
        prev.some((f) => f.path === ev.path)
          ? prev
          : [...prev, { seq: ev.seq, path: ev.path!, url: ev.url, note: ev.note, ts: ev.ts }],
      );
    }
  }, []);

  const consume = useCallback(
    async (thread: string, body: Parameters<typeof streamRun>[2]) => {
      setPhase("running");
      setError(undefined);
      startedRef.current = startedRef.current || Date.now();

      try {
        for await (const ev of streamRun(thread, version!.assistant_id, body)) {
          if (ev.event === "error") {
            setError(typeof ev.data === "string" ? ev.data : JSON.stringify(ev.data));
            continue;
          }
          if (ev.event === "custom") {
            ingest(ev.data as RunEvent);
            continue;
          }
          if (ev.data && typeof ev.data === "object" && !Array.isArray(ev.data)) {
            const values = ev.data as TripState;
            if ("agent_runs" in values || "destination" in values || "final_plan" in values) {
              setState((prev) => ({ ...prev, ...values }));
            }
          }
        }

        // The interrupt is not part of `values`, so the thread is read back
        // once, authoritatively, when the stream ends.
        const snapshot = await getThreadState(thread);
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
    [ingest, version],
  );

  const start = useCallback(
    async (trip: TripRequest) => {
      if (!version) return;
      setState({});
      setEvents([]);
      setFrames([]);
      setInterrupt(null);
      setElapsed(0);
      startedRef.current = Date.now();
      try {
        const thread = await createThread();
        setThreadId(thread.thread_id);
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
      if (!threadId) return;
      setInterrupt(null);
      await consume(threadId, { command: { resume: [payload] } });
    },
    [consume, threadId],
  );

  const reset = useCallback(() => {
    setState({});
    setEvents([]);
    setFrames([]);
    setInterrupt(null);
    setPhase("idle");
    setElapsed(0);
    setError(undefined);
    setThreadId(null);
    startedRef.current = 0;
  }, []);

  return {
    versions,
    version,
    selected,
    select: setSelected,
    state,
    phase,
    error,
    elapsed,
    threadId,
    events,
    frames,
    activity: describeActivity(events, phase),
    interrupt,
    busy,
    start,
    resume,
    reset,
  };
}

/** The most recent thing worth saying out loud about a running graph. */
function describeActivity(events: RunEvent[], phase: RunPhase): string | undefined {
  if (phase !== "running") return undefined;
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.kind === "browser_action") return `${e.action} ${e.detail ?? ""}`.trim();
    if (e.kind === "phase") return e.detail || e.name;
    if (e.kind === "agent_started") return `${e.agent} is working`;
  }
  return undefined;
}
