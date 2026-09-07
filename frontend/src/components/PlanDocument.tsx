"use client";

import { Markdown } from "@/lib/markdown";
import type { Revision } from "@/lib/types";

/**
 * The finished plan, and the one thing you do with a finished plan: keep it.
 *
 * Export goes through the browser's own print-to-PDF. A rendering library
 * would mean a dependency, a font bundle and a server round trip to produce
 * something every platform can already make from styled HTML — and the plan is
 * styled HTML by the time it reaches here. The print rules live in
 * `globals.css`; this component only marks the region to print and keeps the
 * controls out of it.
 *
 * The revision trail prints with the plan deliberately. A plan that took four
 * rounds of review is a different artefact from one accepted on sight, and
 * whoever reads it later cannot tell the two apart otherwise.
 */
export function PlanDocument({
  plan,
  revisions,
}: {
  plan: string;
  revisions?: Revision[] | null;
}) {
  const rounds = revisions?.filter((r) => r.decision !== "accept") ?? [];

  return (
    <article
      data-print-root
      className="rounded-lg border border-line bg-surface px-5 py-4"
    >
      <header
        data-print-hide
        className="mb-3 flex items-center justify-between gap-3 border-b border-line pb-2.5"
      >
        <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Plan</h2>
        <button
          onClick={() => window.print()}
          className="rounded-md border border-line bg-raised px-2.5 py-1 text-xs font-medium text-body transition-colors hover:border-muted/50"
          title="Opens your browser's print dialog — choose Save as PDF"
        >
          Export PDF
        </button>
      </header>

      <Markdown source={plan} />

      {rounds.length > 0 && (
        <section className="mt-6 border-t border-line pt-3">
          <h3 className="mb-2 text-xs font-medium tracking-wide text-muted uppercase">
            How this plan got here
          </h3>
          <ol className="space-y-1.5">
            {rounds.map((r, i) => (
              <li key={i} className="text-xs leading-relaxed text-muted">
                <span className="font-mono text-[10px] text-muted/60">
                  Draft {r.iteration + 1}
                </span>{" "}
                {r.decision === "comments"
                  ? r.comments.map((c) => `${c.section} — ${c.comment}`).join("; ")
                  : (r.feedback ?? r.decision)}
                {r.agents_rerun.length > 0 && (
                  <span className="text-accent-dim"> → re-ran {r.agents_rerun.join(", ")}</span>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </article>
  );
}
