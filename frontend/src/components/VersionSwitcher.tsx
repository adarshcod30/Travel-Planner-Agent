"use client";

import type { VersionMeta } from "@/lib/types";

/**
 * The version switcher.
 *
 * This is the whole point of the project made clickable: selecting a version
 * changes exactly one field in the API call — `assistant_id` — because all five
 * graphs are registered with the same Aegra server. No redeploy, no feature
 * flag, no branching in the client.
 */
export function VersionSwitcher({
  versions,
  selected,
  onSelect,
  disabled,
}: {
  versions: VersionMeta[];
  selected: string;
  onSelect: (graphId: string) => void;
  disabled?: boolean;
}) {
  const active = versions.find((v) => v.graph_id === selected);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {versions.map((v) => {
          const isActive = v.graph_id === selected;
          return (
            <button
              key={v.graph_id}
              onClick={() => onSelect(v.graph_id)}
              disabled={disabled}
              title={v.headline}
              className={[
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                "border disabled:cursor-not-allowed disabled:opacity-50",
                isActive
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-line bg-raised text-muted hover:border-muted/50 hover:text-body",
              ].join(" ")}
            >
              {v.label}
            </button>
          );
        })}
      </div>

      {active && (
        <div className="rounded-lg border border-line bg-surface p-3">
          <p className="text-sm text-bright">{active.headline}</p>
          <p className="mt-1 text-xs text-muted">
            <span className="text-accent-dim">Adds:</span> {active.adds}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Capability on label={`${active.agents.length} agents`} />
            <Capability on={active.parallel} label="parallel" />
            <Capability on={active.orchestrated} label="orchestrated" />
            <Capability on={active.human_in_the_loop} label="human gate" />
            <Capability on={active.live_research} label="live research" />
            <Capability on={active.cross_trip_memory} label="memory" />
          </div>
          <p className="mt-2.5 text-xs leading-relaxed text-muted">{active.notes}</p>
        </div>
      )}
    </div>
  );
}

function Capability({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      className={[
        "rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide uppercase",
        on ? "bg-accent/10 text-accent-dim" : "bg-raised text-muted/50 line-through",
      ].join(" ")}
    >
      {label}
    </span>
  );
}
