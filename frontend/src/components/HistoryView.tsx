"use client";

import { useCallback, useEffect, useState } from "react";
import { PlanDocument } from "@/components/PlanDocument";
import { money } from "@/components/Shell";
import { forgetTrip, getTrip, listTrips } from "@/lib/aegra";
import type { ArchivedTrip } from "@/lib/types";

/**
 * Trips that finished.
 *
 * This table is the only record that a trip ever happened: completing a run
 * archives the plan and then deletes the checkpoints that produced it, so
 * there is nothing else left to read. That is why the list is worth having a
 * view of its own rather than being a dropdown somewhere.
 */
export function HistoryView() {
  const [trips, setTrips] = useState<ArchivedTrip[]>([]);
  const [open, setOpen] = useState<ArchivedTrip | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [reloads, setReloads] = useState(0);

  // The effect *is* the fetch, and every state update lands in a callback
  // rather than in the effect body — refreshing is asking for another fetch,
  // not calling a function that sets state on the way in.
  useEffect(() => {
    let alive = true;
    listTrips()
      .then((r) => {
        if (!alive) return;
        setTrips(r.trips);
        setError(undefined);
      })
      .catch((e) => alive && setError(e instanceof Error ? e.message : String(e)))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [reloads]);

  const refresh = useCallback(() => setReloads((n) => n + 1), []);

  if (open) {
    return (
      <div className="space-y-3">
        <button
          onClick={() => setOpen(null)}
          className="text-xs text-muted hover:text-body"
        >
          ← back to history
        </button>
        <PlanDocument plan={open.final_plan ?? ""} />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <header className="flex items-baseline justify-between">
        <div>
          <h2 className="text-sm font-semibold text-bright">Finished trips</h2>
          <p className="mt-0.5 text-xs text-muted">
            Kept after the run that produced them was deleted.
          </p>
        </div>
        <button
          onClick={refresh}
          className="rounded-md border border-line bg-raised px-2.5 py-1 text-xs text-body transition-colors hover:border-muted/50"
        >
          Refresh
        </button>
      </header>

      {error && (
        <p className="rounded-lg border border-danger/40 bg-danger/5 px-4 py-3 text-xs text-danger">
          {error}
        </p>
      )}

      {loading && trips.length === 0 && <p className="text-xs text-muted">Loading…</p>}

      {!loading && trips.length === 0 && !error && (
        <div className="rounded-lg border border-dashed border-line px-6 py-12 text-center">
          <p className="text-sm text-muted">No trips saved yet.</p>
          <p className="mt-1 text-xs leading-relaxed text-muted/70">
            Finish a plan and choose &ldquo;Save to History&rdquo; — the plan is kept and the
            checkpoints behind it are reclaimed.
          </p>
        </div>
      )}

      {trips.length > 0 && (
        <ul className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {trips.map((t) => (
            <li key={t.trip_id}>
              <TripCard
                trip={t}
                onOpen={async () => setOpen(await getTrip(t.trip_id))}
                onForget={async () => {
                  await forgetTrip(t.trip_id);
                  refresh();
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TripCard({
  trip,
  onOpen,
  onForget,
}: {
  trip: ArchivedTrip;
  onOpen: () => Promise<void>;
  onForget: () => Promise<void>;
}) {
  const where = [trip.destination, trip.country].filter(Boolean).join(", ") || "Somewhere";
  const calls = trip.telemetry?.agent_calls;

  return (
    <article className="flex h-full flex-col rounded-lg border border-line bg-surface p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="min-w-0 truncate text-sm font-semibold text-bright">{where}</h3>
        <span className="shrink-0 font-mono text-[10px] text-muted">
          {new Date(trip.created_at).toLocaleDateString(undefined, {
            day: "numeric",
            month: "short",
          })}
        </span>
      </div>

      <p className="mt-1 text-xs text-muted">
        {trip.origin && <>from {trip.origin} · </>}
        {trip.days} day{trip.days === 1 ? "" : "s"}
        {trip.travelers ? ` · ${trip.travelers} traveller${trip.travelers === 1 ? "" : "s"}` : ""}
      </p>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {trip.budget_total != null && (
          <span className="text-sm font-semibold text-accent">
            {money(trip.budget_total, trip.currency ?? "INR")}
          </span>
        )}
        <span className="font-mono text-[10px] text-muted">{trip.graph_id}</span>
        {calls != null && <span className="text-[10px] text-muted">{calls} agent calls</span>}
      </div>

      <div className="mt-auto flex gap-2 pt-3">
        <button
          onClick={() => void onOpen()}
          className="flex-1 rounded-md border border-line bg-raised px-2 py-1.5 text-xs text-body transition-colors hover:border-muted/50"
        >
          Read
        </button>
        <button
          onClick={() => void onForget()}
          className="rounded-md border border-line px-2 py-1.5 text-xs text-muted transition-colors hover:border-danger/40 hover:text-danger"
          title="Delete this trip permanently"
        >
          Delete
        </button>
      </div>
    </article>
  );
}
