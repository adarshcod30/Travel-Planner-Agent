"use client";

import { BookingOfferPanel } from "@/components/BookingOfferPanel";
import { BookingResult } from "@/components/BookingResult";
import { PlanDocument } from "@/components/PlanDocument";
import { ReviewPanel } from "@/components/ReviewPanel";
import type { BookingOffer, PlanReviewInterrupt } from "@/lib/types";
import type { Run } from "@/lib/useRun";

/**
 * Whatever the plan currently needs from you: a review, a booking decision, or
 * nothing at all because it is finished and yours to keep.
 *
 * One view rather than three, because they are the same object at three
 * moments — and putting them in one place is what stops the page from being
 * the pile of simultaneous panels it used to be.
 */
export function PlanView({ run, onFinish }: { run: Run; onFinish: () => void }) {
  const interrupt = run.interrupt;

  if (interrupt?.type === "section_review") {
    return (
      <ReviewPanel
        interrupt={interrupt as PlanReviewInterrupt}
        onResume={run.resume}
        busy={run.busy}
      />
    );
  }

  if (interrupt?.type === "booking_offer") {
    return (
      <BookingOfferPanel
        offer={interrupt as BookingOffer}
        onResume={run.resume}
        busy={run.busy}
      />
    );
  }

  if (run.state.final_plan) {
    return (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0">
          <PlanDocument plan={run.state.final_plan} revisions={run.state.revisions} />
        </div>
        <aside className="space-y-4">
          {run.state.booking && <BookingResult booking={run.state.booking} />}
          <FinishCard run={run} onFinish={onFinish} />
        </aside>
      </div>
    );
  }

  return (
    <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-line px-6 py-16 text-center">
      <div className="max-w-md space-y-2">
        <p className="text-sm text-muted">
          {run.busy ? "The plan is still being written." : "No plan yet."}
        </p>
        <p className="text-xs leading-relaxed text-muted/70">
          {run.busy
            ? "Watch it happen under Live, or wait here — this fills in when the graph is done."
            : "Describe a trip under Plan a trip and the finished plan lands here."}
        </p>
      </div>
    </div>
  );
}

/**
 * Keeping the plan and reclaiming what produced it.
 *
 * The asymmetry is the point: the plan is a few kilobytes and is what you came
 * for; the checkpoints behind it are around 110 KB per run and will never be
 * replayed once the trip is finished.
 */
function FinishCard({ run, onFinish }: { run: Run; onFinish: () => void }) {
  const runs = run.state.agent_runs ?? [];
  const tokens = runs.reduce((s, r) => s + r.input_tokens + r.output_tokens, 0);

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <h2 className="text-xs font-medium tracking-wide text-muted uppercase">This run</h2>
      <dl className="mt-2 space-y-1 text-xs">
        <Row label="Version" value={run.version?.label ?? "—"} />
        <Row label="Agent calls" value={String(runs.length)} />
        <Row label="Tokens" value={tokens.toLocaleString()} />
        <Row label="Wall time" value={`${(run.elapsed / 1000).toFixed(1)}s`} />
      </dl>
      <button
        onClick={onFinish}
        className="mt-3 w-full rounded-md bg-accent px-3 py-2 text-xs font-semibold text-ink transition-opacity hover:opacity-90"
      >
        Save to History and start over
      </button>
      <p className="mt-1.5 text-[11px] leading-relaxed text-muted/70">
        Keeps the plan and deletes the checkpoints behind it — roughly 110 KB per run that
        nothing will ever read again.
      </p>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="text-body">{value}</dd>
    </div>
  );
}
