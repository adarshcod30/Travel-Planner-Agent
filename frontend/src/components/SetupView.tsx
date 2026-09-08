"use client";

import { useState } from "react";
import { TripForm } from "@/components/TripForm";
import type { TripRequest, VersionMeta } from "@/lib/types";

/**
 * Describing a trip, with the architecture choice out of the way.
 *
 * The version picker used to share the width with the form, which said the two
 * were equally important. They are not. Choosing an architecture is a thing
 * you do once and then forget; describing the trip is the only screen where
 * the quality of what you get is actually decided. So the form takes the page
 * and the picker collapses into a rail, remembering nothing except which
 * version is on — visible at a glance, open when you want to read about it.
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
  const [open, setOpen] = useState(false);
  const active = versions.find((v) => v.graph_id === selected);

  return (
    <div className={`grid gap-6 ${open ? "xl:grid-cols-[minmax(0,1fr)_380px]" : "xl:grid-cols-[minmax(0,1fr)_60px]"}`}>
      <section className="min-w-0 space-y-4">
        <header>
          <h1 className="text-2xl font-semibold tracking-tight text-bright">Plan a trip</h1>
          <p className="mt-1 text-sm text-muted">
            From anywhere in India, priced in rupees. Say as much or as little as you like —
            the more it knows, the less it has to guess.
          </p>
        </header>
        <TripForm onSubmit={onSubmit} disabled={disabled} />
      </section>

      <ArchitectureRail
        versions={versions}
        selected={selected}
        onSelect={onSelect}
        open={open}
        onOpen={setOpen}
        active={active}
        disabled={disabled}
      />
    </div>
  );
}

function ArchitectureRail({
  versions,
  selected,
  onSelect,
  open,
  onOpen,
  active,
  disabled,
}: {
  versions: VersionMeta[];
  selected: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpen: (v: boolean) => void;
  active?: VersionMeta;
  disabled?: boolean;
}) {
  if (!open) {
    return (
      <aside className="xl:sticky xl:top-16 xl:self-start">
        <button
          onClick={() => onOpen(true)}
          className="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-3 py-3 text-left transition-colors hover:border-accent/40 xl:flex-col xl:gap-4 xl:py-5"
          aria-expanded={false}
        >
          <span className="text-xs text-muted xl:[writing-mode:vertical-rl]">Architecture</span>
          <span className="text-sm font-semibold text-accent xl:[writing-mode:vertical-rl]">
            {active?.label.split("·")[0].trim() ?? "—"}
          </span>
          <span className="ml-auto text-[10px] text-muted xl:ml-0">◀</span>
        </button>
      </aside>
    );
  }

  return (
    <aside className="space-y-3 xl:sticky xl:top-16 xl:max-h-[calc(100vh-5rem)] xl:self-start xl:overflow-y-auto">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-bright">Architecture</h2>
        <button
          onClick={() => onOpen(false)}
          className="text-xs text-muted transition-colors hover:text-body"
          aria-expanded
        >
          collapse ▶
        </button>
      </div>

      <p className="text-xs leading-relaxed text-muted">
        Five working systems, each adding one idea to the last. Run the same trip through
        two of them and the difference is what that idea bought.
      </p>

      <div className="space-y-2">
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
        <div className="rounded-xl border border-line bg-surface p-3">
          <h3 className="text-[11px] font-medium tracking-wide text-muted uppercase">
            How {active.label.split("·")[0].trim()} works
          </h3>
          <p className="mt-1.5 text-xs leading-relaxed text-body">{active.notes}</p>
          <dl className="mt-3 space-y-1 border-t border-line pt-2 text-[11px]">
            <Row label="Agents" value={String(active.agents.length)} />
            <Row label="Runs in parallel" value={yesNo(active.parallel)} />
            <Row label="Audits itself" value={yesNo(active.orchestrated)} />
            <Row label="Remembers you" value={yesNo(active.cross_trip_memory)} />
            <Row label="You review sections" value={yesNo(active.section_review)} />
            <Row label="Browses live" value={yesNo(active.live_research)} />
          </dl>
        </div>
      )}
    </aside>
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
  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={active}
      className={[
        "block w-full rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        active ? "border-accent/60 bg-accent/10" : "border-line bg-surface hover:border-muted/40",
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
      <p className="mt-1 text-[11px] leading-snug text-muted">{version.adds}</p>
    </button>
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

function yesNo(on: boolean): string {
  return on ? "yes" : "no";
}
