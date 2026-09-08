"use client";

import { TripForm } from "@/components/TripForm";
import type { TripRequest, VersionMeta } from "@/lib/types";

/**
 * Describing a trip.
 *
 * The whole page, because it is the only screen where the quality of what you
 * get is actually decided. The architecture picker lives on the edge of the
 * screen instead — a thing you set once, not something to re-read every time
 * you plan a trip. What stays here is a single line saying which version is
 * live, so the choice is never invisible.
 */
export function SetupView({
  version,
  onSubmit,
  onOpenArchitecture,
  disabled,
}: {
  version?: VersionMeta;
  onSubmit: (trip: TripRequest) => void;
  onOpenArchitecture: () => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-tight text-bright">Plan a trip</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted">
            From anywhere in India, priced in rupees. Say as much or as little as you like —
            the more it knows, the less it has to guess.
          </p>
        </div>

        {version && (
          <button
            onClick={onOpenArchitecture}
            className="group flex items-center gap-3 rounded-xl border border-line bg-surface px-4 py-2.5 text-left transition-colors hover:border-accent/50"
          >
            <div>
              <span className="block text-[10px] tracking-wide text-muted uppercase">
                Running on
              </span>
              <span className="block text-sm font-semibold text-accent">{version.label}</span>
            </div>
            <span className="text-[11px] text-muted transition-colors group-hover:text-body">
              change
            </span>
          </button>
        )}
      </header>

      <TripForm onSubmit={onSubmit} disabled={disabled} />
    </div>
  );
}
