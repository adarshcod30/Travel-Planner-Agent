"use client";

import { useState } from "react";
import type { BudgetLevel, TripRequest } from "@/lib/types";

const INTEREST_OPTIONS = [
  "food", "temples", "history", "museums", "beach", "nature",
  "nightlife", "shopping", "adventure", "wellness", "family", "art",
];

const PRESETS: { label: string; trip: TripRequest }[] = [
  {
    label: "Kyoto · temples & food",
    trip: { request: "Temples and food in Kyoto", days: 3, interests: ["temples", "food"],
            budget_level: "mid-range", season: "November", travelers: 2 },
  },
  {
    label: "Somewhere warm · beaches",
    trip: { request: "Somewhere warm with good beaches and cheap food", days: 5, interests: ["beach", "food"],
            budget_level: "budget", season: "January", travelers: 2 },
  },
  {
    label: "Lisbon · long weekend",
    trip: { request: "A relaxed long weekend in Lisbon", days: 4, interests: ["food", "history"],
            budget_level: "mid-range", season: "May", travelers: 2 },
  },
];

export function TripForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (trip: TripRequest) => void;
  disabled?: boolean;
}) {
  const [trip, setTrip] = useState<TripRequest>(PRESETS[0].trip);

  const set = <K extends keyof TripRequest>(key: K, value: TripRequest[K]) =>
    setTrip((t) => ({ ...t, [key]: value }));

  const toggleInterest = (i: string) =>
    setTrip((t) => ({
      ...t,
      interests: t.interests.includes(i) ? t.interests.filter((x) => x !== i) : [...t.interests, i],
    }));

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(trip);
      }}
      className="space-y-4"
    >
      <div className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => setTrip(p.trip)}
            disabled={disabled}
            className="rounded border border-line bg-raised px-2 py-1 text-[11px] text-muted transition-colors hover:text-body disabled:opacity-50"
          >
            {p.label}
          </button>
        ))}
      </div>

      <Field label="What kind of trip?">
        <textarea
          value={trip.request}
          onChange={(e) => set("request", e.target.value)}
          disabled={disabled}
          rows={2}
          placeholder="Somewhere warm with good food and not too touristy"
          className="w-full resize-none rounded-md border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none disabled:opacity-50"
        />
      </Field>

      <div className="grid grid-cols-3 gap-3">
        <Field label="Days">
          <NumberInput value={trip.days} min={1} max={30} disabled={disabled} onChange={(v) => set("days", v)} />
        </Field>
        <Field label="Travelers">
          <NumberInput value={trip.travelers} min={1} max={12} disabled={disabled} onChange={(v) => set("travelers", v)} />
        </Field>
        <Field label="When">
          <input
            value={trip.season}
            onChange={(e) => set("season", e.target.value)}
            disabled={disabled}
            placeholder="November"
            className="w-full rounded-md border border-line bg-ink px-2.5 py-1.5 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none disabled:opacity-50"
          />
        </Field>
      </div>

      <Field label="Budget">
        <div className="flex gap-1.5">
          {(["budget", "mid-range", "luxury"] as BudgetLevel[]).map((level) => (
            <button
              key={level}
              type="button"
              onClick={() => set("budget_level", level)}
              disabled={disabled}
              className={[
                "flex-1 rounded-md border px-2 py-1.5 text-xs capitalize transition-colors disabled:opacity-50",
                trip.budget_level === level
                  ? "border-accent/60 bg-accent/15 text-accent"
                  : "border-line bg-raised text-muted hover:text-body",
              ].join(" ")}
            >
              {level}
            </button>
          ))}
        </div>
      </Field>

      <Field label={`Interests (${trip.interests.length})`}>
        <div className="flex flex-wrap gap-1">
          {INTEREST_OPTIONS.map((i) => (
            <button
              key={i}
              type="button"
              onClick={() => toggleInterest(i)}
              disabled={disabled}
              className={[
                "rounded px-2 py-1 text-[11px] transition-colors disabled:opacity-50",
                trip.interests.includes(i)
                  ? "bg-accent/15 text-accent"
                  : "bg-raised text-muted hover:text-body",
              ].join(" ")}
            >
              {i}
            </button>
          ))}
        </div>
      </Field>

      <button
        type="submit"
        disabled={disabled || !trip.request.trim()}
        className="w-full rounded-md bg-accent px-4 py-2.5 text-sm font-semibold text-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {disabled ? "Planning…" : "Plan this trip"}
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-medium tracking-wide text-muted uppercase">{label}</span>
      {children}
    </label>
  );
}

function NumberInput({
  value, min, max, disabled, onChange,
}: { value: number; min: number; max: number; disabled?: boolean; onChange: (v: number) => void }) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      disabled={disabled}
      onChange={(e) => onChange(Math.max(min, Math.min(max, Number(e.target.value) || min)))}
      className="w-full rounded-md border border-line bg-ink px-2.5 py-1.5 text-sm text-body focus:border-accent/50 focus:outline-none disabled:opacity-50"
    />
  );
}
