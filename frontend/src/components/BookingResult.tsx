"use client";

import type { BookingSearch } from "@/lib/types";

/**
 * What the booking run actually found.
 *
 * Reports an attempt, never a transaction. `handed_over` says a person took
 * the browser; nothing here means anything was bought, and the panel says so
 * rather than leaving it to be assumed.
 */
export function BookingResult({ booking }: { booking: BookingSearch }) {
  const cheapest = booking.prices.length
    ? Math.min(...booking.prices.map((p) => Number(p.price_inr)))
    : null;

  return (
    <section className="rounded-lg border border-line bg-surface p-4">
      <header className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Live prices</h2>
        {booking.site && (
          <span className="font-mono text-[11px] text-muted">{booking.site}</span>
        )}
      </header>

      <p className="mt-2 text-xs leading-relaxed text-body">{booking.note}</p>

      {booking.checkin && (
        <p className="mt-1 text-[11px] text-muted">
          {booking.checkin} to {booking.checkout}
        </p>
      )}

      {cheapest !== null && (
        <p className="mt-2 text-sm font-semibold text-accent">
          from ₹{cheapest.toLocaleString("en-IN")}
        </p>
      )}

      {booking.prices.length > 0 && (
        <ul className="mt-2 space-y-1">
          {booking.prices.slice(0, 6).map((p, i) => (
            <li key={i} className="flex justify-between gap-2 text-[11px]">
              <span className="min-w-0 truncate text-muted">{p.line}</span>
              <span className="shrink-0 font-mono text-body">
                ₹{Number(p.price_inr).toLocaleString("en-IN")}
              </span>
            </li>
          ))}
        </ul>
      )}

      {booking.url && (
        <a
          href={booking.url}
          target="_blank"
          rel="noreferrer noopener"
          className="mt-3 block truncate text-[11px] text-info hover:underline"
        >
          open {booking.site} yourself →
        </a>
      )}

      {booking.attempts.length > 0 && (
        <details className="mt-2 text-[11px]">
          <summary className="cursor-pointer text-muted/70 hover:text-muted">
            {booking.attempts.length} site
            {booking.attempts.length === 1 ? "" : "s"} did not answer
          </summary>
          <ul className="mt-1 space-y-0.5 text-muted/70">
            {booking.attempts.map((a, i) => (
              <li key={i}>
                {a.site} — {a.outcome}
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="mt-3 border-t border-line pt-2 text-[11px] leading-relaxed text-muted/70">
        Nothing was booked. These are prices the browser saw; paying is yours to do.
      </p>
    </section>
  );
}
