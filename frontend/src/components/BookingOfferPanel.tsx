"use client";

import { money } from "@/components/Shell";
import type { BookingOffer } from "@/lib/types";

/**
 * The last thing v5 asks: shall I open a real booking page for this?
 *
 * Worth being plain about what "yes" means, which is why the boundary is
 * stated on the button rather than buried: the browser opens real commercial
 * sites, you watch it, it hands control to you when a site wants a login, and
 * it stops at payment. Nothing is bought without you.
 */
export function BookingOfferPanel({
  offer,
  onResume,
  busy,
}: {
  offer: BookingOffer;
  onResume: (payload: { type: string; args?: unknown }) => void;
  busy?: boolean;
}) {
  const nights = Math.max(
    1,
    Math.round(
      (new Date(offer.checkout).getTime() - new Date(offer.checkin).getTime()) / 86_400_000,
    ),
  );

  return (
    <section className="mx-auto max-w-2xl overflow-hidden rounded-lg border border-accent/40 bg-accent/5">
      <header className="border-b border-accent/25 px-4 py-3">
        <h2 className="text-sm font-semibold text-accent">Look for real prices?</h2>
        <p className="mt-0.5 text-xs text-muted">
          {offer.destination ?? "Your destination"} · {fmt(offer.checkin)} to{" "}
          {fmt(offer.checkout)} · {nights} night{nights === 1 ? "" : "s"} ·{" "}
          {offer.travelers} traveller{offer.travelers === 1 ? "" : "s"}
        </p>
      </header>

      {offer.shortlist.length > 0 && (
        <div className="border-b border-accent/20 px-4 py-3">
          <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted/70">
            What the plan suggested
          </p>
          <ul className="space-y-1">
            {offer.shortlist.map((h) => (
              <li key={h.name} className="flex justify-between gap-3 text-xs">
                <span className="min-w-0 truncate text-body">
                  {h.name} <span className="text-muted">· {h.tier}</span>
                </span>
                <span className="shrink-0 font-mono text-muted">
                  {money(h.price_per_night)}/night
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted/70">
            Those are the planner&apos;s estimates. This checks what the sites are actually
            charging.
          </p>
        </div>
      )}

      <div className="space-y-3 px-4 py-3">
        <p className="text-xs leading-relaxed text-muted">{offer.note}</p>
        <div className="flex flex-wrap gap-2">
          <button
            disabled={busy}
            onClick={() => onResume({ type: "book" })}
            className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-ink transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            Open real booking pages
          </button>
          <button
            disabled={busy}
            onClick={() => onResume({ type: "skip" })}
            className="rounded-md border border-line bg-raised px-3 py-1.5 text-xs font-medium text-body transition-colors hover:border-muted/50 disabled:opacity-40"
          >
            No thanks, just the plan
          </button>
        </div>
        <p className="text-[11px] leading-relaxed text-muted/70">
          You will watch every click under <span className="text-muted">Live</span>. Card, UPI
          and bank details are never entered by the planner — if a page asks for them, the
          browser becomes yours and stays that way.
        </p>
      </div>
    </section>
  );
}

function fmt(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
