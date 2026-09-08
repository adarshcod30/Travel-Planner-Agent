"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import type { RunPhase } from "@/lib/types";

export type ViewKey = "setup" | "live" | "plan" | "history" | "about";

/**
 * The frame around everything: who you are looking at, where you are, and what
 * the run is doing.
 *
 * The four views exist because the old single page put a version picker, a
 * trip form, a live timeline, a review gate and a finished plan in one column,
 * and every one of them competed for the same attention at the same time. They
 * are not simultaneous concerns — you set a trip up, then watch it, then read
 * it — so they are not on screen simultaneously.
 *
 * The tabs still move on their own when the run reaches a stage that needs
 * you. Being taken to the thing that is waiting beats being told a badge
 * appeared somewhere.
 */
export function Shell({
  view,
  onView,
  badges,
  status,
  children,
}: {
  view: ViewKey;
  onView: (v: ViewKey) => void;
  badges: Partial<Record<ViewKey, string>>;
  status: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-line bg-ink/85 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-6 gap-y-2 px-5 py-2.5">
          <div className="flex items-baseline gap-2.5">
            <h1 className="text-sm font-semibold tracking-tight text-bright">Travel Planner</h1>
            <span className="hidden text-[11px] text-muted sm:inline">
              five architectures, one Aegra server
            </span>
          </div>

          <nav className="flex items-center gap-0.5" aria-label="Views">
            {TABS.map(({ key, label }) => (
              <Tab
                key={key}
                active={view === key}
                badge={badges[key]}
                onClick={() => onView(key)}
              >
                {label}
              </Tab>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {status}
            <Link
              href="/compare"
              className="rounded px-2 py-1 text-xs text-muted transition-colors hover:bg-raised hover:text-body"
            >
              Compare
            </Link>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1400px] px-5 py-5">{children}</main>
    </div>
  );
}

const TABS: { key: ViewKey; label: string }[] = [
  { key: "setup", label: "Plan a trip" },
  { key: "live", label: "Live" },
  { key: "plan", label: "The plan" },
  { key: "history", label: "History" },
  { key: "about", label: "About" },
];

function Tab({
  children,
  active,
  badge,
  onClick,
}: {
  children: ReactNode;
  active: boolean;
  badge?: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={[
        "relative rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
        active ? "bg-raised text-bright" : "text-muted hover:text-body",
      ].join(" ")}
    >
      {children}
      {badge && (
        <span className="ml-1.5 rounded-full bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent">
          {badge}
        </span>
      )}
    </button>
  );
}

/** A compact, always-visible summary of the run. */
export function RunStatus({
  phase,
  elapsed,
  activity,
  destination,
  total,
  currency,
  error,
}: {
  phase: RunPhase;
  elapsed: number;
  activity?: string;
  destination?: string;
  total?: number;
  currency?: string;
  error?: string;
}) {
  const dot =
    phase === "running"
      ? "running-dot bg-accent"
      : phase === "interrupted"
        ? "bg-warn"
        : phase === "done"
          ? "bg-accent"
          : phase === "error"
            ? "bg-danger"
            : "bg-line";

  const label =
    phase === "idle"
      ? "Ready"
      : phase === "running"
        ? (activity ?? "Working")
        : phase === "interrupted"
          ? "Waiting for you"
          : phase === "done"
            ? "Done"
            : "Failed";

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span className="flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
        <span
          className={`max-w-56 truncate ${phase === "error" ? "text-danger" : "text-body"}`}
          title={label}
        >
          {label}
        </span>
      </span>
      {elapsed > 0 && (
        <span className="font-mono text-muted">{(elapsed / 1000).toFixed(1)}s</span>
      )}
      {destination && <span className="text-bright">{destination}</span>}
      {typeof total === "number" && (
        <span className="text-muted">{money(total, currency)}</span>
      )}
      {error && (
        <span className="max-w-64 truncate text-danger" title={error}>
          {error}
        </span>
      )}
    </div>
  );
}

export function money(amount: number, currency = "INR"): string {
  return currency === "INR"
    ? `₹${amount.toLocaleString("en-IN")}`
    : `${currency} ${amount.toLocaleString()}`;
}
