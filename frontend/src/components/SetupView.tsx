"use client";

import { TripForm } from "@/components/TripForm";
import type { TripRequest, VersionMeta } from "@/lib/types";

/**
 * Choosing a version and describing a trip.
 *
 * The version picker is cards rather than a row of chips because the choice is
 * the interesting part of this project and a chip cannot say what it means. A
 * card can show what a version adds and what it costs you — and the versions
 * are cumulative, so reading down the list is reading the project's history.
 */
export function SetupView({
  versions,
  selected,
  onSelect,
  onSubmit,
  disabled,
}: {
  versions: VersionMeta[];
  selected: string;
  onSelect: (id: string) => void;
  onSubmit: (trip: TripRequest) => void;
  disabled?: boolean;
}) {
  const active = versions.find((v) => v.graph_id === selected);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section className="space-y-3">
        <header>
          <h2 className="text-sm font-semibold text-bright">Pick an architecture</h2>
          <p className="mt-0.5 text-xs text-muted">
            Each is a working system. They are cumulative — v5 is v1 with four more ideas in
            it — so running the same trip through two of them shows what the idea bought.
          </p>
        </header>

        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {versions.map((v) => (
            <VersionCard
              key={v.graph_id}
              version={v}
              active={v.graph_id === selected}
              onSelect={() => onSelect(v.graph_id)}
              disabled={disabled}
            />
          ))}
        </div>

        {active && (
          <p className="rounded-lg border border-line bg-surface px-4 py-3 text-xs leading-relaxed text-muted">
            {active.notes}
          </p>
        )}
      </section>

      <section className="space-y-3">
        <header>
          <h2 className="text-sm font-semibold text-bright">Describe the trip</h2>
          <p className="mt-0.5 text-xs text-muted">
            Everything is priced in rupees for a traveller starting in India.
          </p>
        </header>
        <div className="rounded-lg border border-line bg-surface p-4">
          <TripForm onSubmit={onSubmit} disabled={disabled} />
        </div>
      </section>
    </div>
  );
}

function VersionCard({
  version,
  active,
  onSelect,
  disabled,
}: {
  version: VersionMeta;
  active: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) {
  const caps = [
    version.parallel && "parallel",
    version.orchestrated && "self-audits",
    version.cross_trip_memory && "remembers you",
    version.section_review && "you review it",
    version.live_research && "browses live",
  ].filter(Boolean) as string[];

  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={active}
      className={[
        "flex h-full flex-col rounded-lg border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        active
          ? "border-accent/60 bg-accent/10"
          : "border-line bg-surface hover:border-muted/40",
      ].join(" ")}
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className={`text-sm font-semibold ${active ? "text-accent" : "text-bright"}`}>
          {version.label}
        </span>
        <span className="shrink-0 font-mono text-[10px] text-muted">
          {version.agents.length} agents
        </span>
      </div>
      <p className="mt-1 text-xs leading-snug text-body">{version.headline}</p>
      <p className="mt-1.5 text-[11px] leading-snug text-muted">{version.adds}</p>
      {caps.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {caps.map((c) => (
            <span
              key={c}
              className="rounded bg-raised px-1.5 py-0.5 text-[10px] text-muted"
            >
              {c}
            </span>
          ))}
        </div>
      )}
    </button>
  );
}
