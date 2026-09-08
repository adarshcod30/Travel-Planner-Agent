"use client";

import type { VersionMeta } from "@/lib/types";

/**
 * The architecture picker, as a drawer on the edge of the screen.
 *
 * It was a card in the page before, sharing the width with the trip form,
 * which said the two were equally important. They are not — you choose an
 * architecture once and then spend your time describing trips. But it was then
 * collapsed into a small box in the corner, which went too far the other way
 * and made the most interesting thing about this project easy to miss.
 *
 * A tab on the edge is the shape that fits: tall enough to see from anywhere
 * on the page, always showing which version is live, and opening over the
 * content rather than squeezing it — so the page underneath does not reflow
 * every time you look something up.
 */
export function ArchitectureDrawer({
  versions,
  selected,
  onSelect,
  open,
  onOpen,
  disabled,
}: {
  versions: VersionMeta[];
  selected: string;
  onSelect: (id: string) => void;
  open: boolean;
  onOpen: (v: boolean) => void;
  disabled?: boolean;
}) {
  const active = versions.find((v) => v.graph_id === selected);
  const short = active?.label.split("·")[1]?.trim() ?? active?.label ?? "";

  if (!open) {
    return (
      <button
        onClick={() => onOpen(true)}
        aria-expanded={false}
        aria-label="Open the architecture picker"
        className="fixed top-1/2 right-0 z-30 flex -translate-y-1/2 flex-col items-center gap-3 rounded-l-xl border border-r-0 border-line bg-surface/95 py-6 pr-2 pl-2.5 shadow-lg backdrop-blur transition-colors hover:border-accent/50 hover:bg-raised"
      >
        <Glyph className="h-4 w-4 text-accent" />
        <span className="text-[11px] font-medium tracking-wide text-muted [writing-mode:vertical-rl]">
          Architecture
        </span>
        <span className="font-mono text-xs font-semibold text-accent [writing-mode:vertical-rl]">
          {active?.graph_id.split("_")[0] ?? "—"}
        </span>
        <span className="text-[10px] text-muted">◀</span>
      </button>
    );
  }

  return (
    <>
      {/* Dismiss by clicking away, the way a drawer should behave. */}
      <div
        className="fixed inset-0 z-30 bg-ink/40 backdrop-blur-[1px]"
        onClick={() => onOpen(false)}
        aria-hidden
      />
      <aside className="fixed top-0 right-0 bottom-0 z-40 flex w-full max-w-[520px] flex-col border-l border-line bg-surface shadow-2xl">
        <header className="flex items-center gap-2.5 border-b border-line px-5 py-4">
          <Glyph className="h-5 w-5 text-accent" />
          <h2 className="text-base font-semibold text-bright">Architecture</h2>
          {active && (
            <span className="flex items-center gap-1.5 rounded-full bg-accent/15 px-2 py-0.5 text-[11px] font-medium text-accent">
              <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              {short}
            </span>
          )}
          <button
            onClick={() => onOpen(false)}
            aria-label="Close"
            className="ml-auto rounded p-1 text-muted transition-colors hover:bg-raised hover:text-bright"
          >
            ✕
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          <p className="text-sm leading-relaxed text-muted">
            Five working systems, each adding exactly one idea to the one before it. Run the
            same trip through two of them and the difference is what that idea bought.
          </p>

          <div className="mt-4 space-y-2.5">
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

          {disabled && (
            <p className="mt-3 text-xs text-warn">
              A run is in flight — the version is fixed until it finishes.
            </p>
          )}
        </div>
      </aside>
    </>
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
  const caps: [string, boolean][] = [
    ["parallel", version.parallel],
    ["audits itself", version.orchestrated],
    ["remembers you", version.cross_trip_memory],
    ["you review it", version.section_review],
    ["browses live", version.live_research],
  ];

  return (
    <button
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={active}
      className={[
        "block w-full rounded-xl border p-4 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        active ? "border-accent/60 bg-accent/10" : "border-line bg-ink/40 hover:border-muted/50",
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

      <p className="mt-1 text-sm leading-snug text-body">{version.headline}</p>
      <p className="mt-1.5 text-xs leading-snug text-muted">{version.adds}</p>

      <div className="mt-2.5 flex flex-wrap gap-1">
        {caps.map(([label, on]) => (
          <span
            key={label}
            className={[
              "rounded px-1.5 py-0.5 text-[10px]",
              on ? "bg-accent/15 text-accent-dim" : "bg-raised/60 text-muted/40 line-through",
            ].join(" ")}
          >
            {label}
          </span>
        ))}
      </div>

      {active && (
        <p className="mt-3 border-t border-accent/20 pt-2.5 text-xs leading-relaxed text-muted">
          {version.notes}
        </p>
      )}
    </button>
  );
}

function Glyph({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden>
      <path
        d="M12 3v4M12 17v4M4.9 7.5l3.5 2M15.6 14.5l3.5 2M4.9 16.5l3.5-2M15.6 9.5l3.5-2"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="3" r="1.4" fill="currentColor" />
      <circle cx="12" cy="21" r="1.4" fill="currentColor" />
      <circle cx="3.6" cy="6.8" r="1.4" fill="currentColor" />
      <circle cx="20.4" cy="17.2" r="1.4" fill="currentColor" />
      <circle cx="3.6" cy="17.2" r="1.4" fill="currentColor" />
      <circle cx="20.4" cy="6.8" r="1.4" fill="currentColor" />
    </svg>
  );
}
