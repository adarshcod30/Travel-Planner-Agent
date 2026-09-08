"use client";

import { useState } from "react";
import type { BudgetLevel, TripPace, TripRequest } from "@/lib/types";

/**
 * The brief.
 *
 * This is the page now, not a sidebar, because it is the only screen where the
 * quality of what you get is decided. Everything below "the essentials" is
 * optional and most of it stays closed — but it is the half a traveller
 * usually knows and is usually never asked: that two of the four are
 * vegetarian, that someone cannot manage stairs, that the budget is a ceiling
 * rather than a preference, that they would rather see one city properly than
 * three badly. A specialist can only use what it is told.
 *
 * Nothing here is validated beyond "there is a destination and a starting
 * point". Interpreting a vague request is the destination agent's job; this
 * only has to make it easy to say more.
 */

const INTERESTS = [
  "food", "history", "temples", "beaches", "hills", "wildlife", "trekking",
  "shopping", "nightlife", "wellness", "photography", "architecture",
  "art", "music", "festivals", "nature",
];

const DIETARY = [
  "vegetarian", "vegan", "jain", "halal", "no beef", "no pork",
  "gluten-free", "nut allergy",
];

const ACCESSIBILITY = [
  "step-free access", "no long walks", "wheelchair accessible",
  "travelling with a pram", "avoid high altitude",
];

const TRANSPORT = ["train", "flight", "bus", "self-drive", "cab"];

const COMPANIONS = ["partner", "kids", "parents", "friends", "colleagues", "solo"];

const STAY_TYPES = [
  "hostel", "budget hotel", "3-star hotel", "boutique", "heritage property",
  "homestay", "resort", "5-star",
];

const ORIGINS = [
  "Delhi", "Mumbai", "Bengaluru", "Kolkata", "Chennai", "Hyderabad",
  "Pune", "Ahmedabad", "Jaipur", "Lucknow", "Kochi", "Chandigarh",
];

const PRESETS: { label: string; hint: string; trip: Partial<TripRequest> }[] = [
  {
    label: "Forts & street food",
    hint: "3 days · by train · mid-range",
    trip: {
      request: "Forts and street food, somewhere I can reach by train",
      origin: "Delhi", days: 3, interests: ["history", "food"],
      budget_level: "mid-range", season: "November", travelers: 2,
      pace: "balanced", transport: ["train"],
    },
  },
  {
    label: "Beaches on a budget",
    hint: "5 days · seafood · cheap",
    trip: {
      request: "Beaches and seafood without spending much",
      origin: "Bengaluru", days: 5, interests: ["beaches", "food"],
      budget_level: "budget", season: "January", travelers: 2,
      pace: "relaxed", budget_cap_inr: 25000,
    },
  },
  {
    label: "Hills, long weekend",
    hint: "4 days · cool weather",
    trip: {
      request: "Somewhere cool in the hills for a long weekend",
      origin: "Mumbai", days: 4, interests: ["hills", "trekking"],
      budget_level: "mid-range", season: "March", travelers: 2, pace: "relaxed",
    },
  },
  {
    label: "Family trip, elders along",
    hint: "5 days · gentle · vegetarian",
    trip: {
      request: "Somewhere meaningful we can all manage together",
      origin: "Chennai", days: 5, interests: ["temples", "history"],
      budget_level: "mid-range", season: "December", travelers: 4,
      pace: "relaxed", dietary: ["vegetarian"],
      accessibility: ["no long walks"], travelling_with: ["parents"],
    },
  },
];

const EMPTY: TripRequest = {
  request: "", origin: "Delhi", days: 3, interests: [], budget_level: "mid-range",
  season: "", travelers: 2, start_date: "", pace: "balanced", budget_cap_inr: null,
  dietary: [], accessibility: [], stay_type: "", transport: [], must_see: "",
  avoid: "", occasion: "", travelling_with: [], notes: "",
};

export function TripForm({
  onSubmit,
  disabled,
}: {
  onSubmit: (trip: TripRequest) => void;
  disabled?: boolean;
}) {
  const [trip, setTrip] = useState<TripRequest>({ ...EMPTY, ...PRESETS[0].trip });
  const [open, setOpen] = useState<string | null>(null);

  const set = <K extends keyof TripRequest>(key: K, value: TripRequest[K]) =>
    setTrip((t) => ({ ...t, [key]: value }));

  const toggle = (key: "interests" | "dietary" | "accessibility" | "transport" | "travelling_with", v: string) =>
    setTrip((t) => {
      const cur = (t[key] ?? []) as string[];
      return { ...t, [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] };
    });

  const extras = countExtras(trip);
  const ready = trip.request.trim() && trip.origin.trim();

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (ready) onSubmit(trip);
      }}
      className="space-y-5"
    >
      {/* --- presets ----------------------------------------------------- */}
      <div className="flex flex-wrap gap-2">
        {PRESETS.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => setTrip({ ...EMPTY, ...p.trip })}
            disabled={disabled}
            className="group rounded-lg border border-line bg-surface px-3 py-2 text-left transition-colors hover:border-accent/40 disabled:opacity-50"
          >
            <span className="block text-xs font-medium text-body group-hover:text-bright">
              {p.label}
            </span>
            <span className="block text-[11px] text-muted">{p.hint}</span>
          </button>
        ))}
        <button
          type="button"
          onClick={() => setTrip(EMPTY)}
          disabled={disabled}
          className="rounded-lg border border-dashed border-line px-3 py-2 text-xs text-muted transition-colors hover:text-body disabled:opacity-50"
        >
          Start blank
        </button>
      </div>

      {/* --- the essentials ---------------------------------------------- */}
      <section className="rounded-xl border border-line bg-surface p-5">
        <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <Field label="What kind of trip?" hint="Say it however you would say it out loud.">
            <textarea
              value={trip.request}
              onChange={(e) => set("request", e.target.value)}
              disabled={disabled}
              rows={3}
              placeholder="Somewhere with forts and good street food, not too far, and not too touristy"
              className={INPUT + " resize-none text-base"}
            />
          </Field>

          <div className="space-y-4">
            <Field label="Starting from" hint="Decides train, flight or international — and every cost.">
              <input
                value={trip.origin}
                onChange={(e) => set("origin", e.target.value)}
                disabled={disabled}
                list="origins"
                placeholder="Delhi"
                className={INPUT}
              />
              <datalist id="origins">
                {ORIGINS.map((c) => <option key={c} value={c} />)}
              </datalist>
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Days">
                <Num value={trip.days} min={1} max={30} disabled={disabled} onChange={(v) => set("days", v)} />
              </Field>
              <Field label="Travellers">
                <Num value={trip.travelers} min={1} max={12} disabled={disabled} onChange={(v) => set("travelers", v)} />
              </Field>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <Field label="When" hint="A month is enough.">
            <input
              value={trip.season}
              onChange={(e) => set("season", e.target.value)}
              disabled={disabled}
              placeholder="November"
              className={INPUT}
            />
          </Field>

          <Field label="Budget level">
            <Segmented
              options={["budget", "mid-range", "luxury"] as BudgetLevel[]}
              value={trip.budget_level}
              disabled={disabled}
              onChange={(v) => set("budget_level", v)}
            />
          </Field>

          <Field label="Pace" hint="How much a day should hold.">
            <Segmented
              options={["relaxed", "balanced", "packed"] as TripPace[]}
              value={trip.pace ?? "balanced"}
              disabled={disabled}
              onChange={(v) => set("pace", v)}
            />
          </Field>
        </div>

        <div className="mt-4">
          <Field label={`Interests${trip.interests.length ? ` · ${trip.interests.length}` : ""}`}>
            <Chips
              options={INTERESTS}
              selected={trip.interests}
              disabled={disabled}
              onToggle={(v) => toggle("interests", v)}
            />
          </Field>
        </div>
      </section>

      {/* --- everything optional ----------------------------------------- */}
      <section className="space-y-2">
        <div className="flex items-baseline justify-between">
          <h3 className="text-sm font-semibold text-bright">Tell it more</h3>
          <span className="text-xs text-muted">
            All optional{extras > 0 && ` · ${extras} added`}
          </span>
        </div>
        <p className="text-xs leading-relaxed text-muted">
          None of this is required. It is also the part that changes the answer most — a
          specialist can only work with what it has been told.
        </p>

        <div className="grid gap-2 md:grid-cols-2">
          <Panel
            title="Dates and money"
            summary={summaryOf([trip.start_date, trip.budget_cap_inr ? `under ₹${trip.budget_cap_inr.toLocaleString("en-IN")}` : ""])}
            open={open === "money"}
            onToggle={() => setOpen(open === "money" ? null : "money")}
          >
            <Field label="Exact start date" hint="Used for real availability and prices.">
              <input
                type="date"
                value={trip.start_date ?? ""}
                onChange={(e) => set("start_date", e.target.value)}
                disabled={disabled}
                className={INPUT}
              />
            </Field>
            <Field label="Hard ceiling (₹)" hint="A limit, not a preference. The plan must come in under it.">
              <input
                type="number"
                min={0}
                step={1000}
                value={trip.budget_cap_inr ?? ""}
                onChange={(e) => set("budget_cap_inr", e.target.value ? Number(e.target.value) : null)}
                disabled={disabled}
                placeholder="45000"
                className={INPUT}
              />
            </Field>
          </Panel>

          <Panel
            title="Who is going"
            summary={summaryOf([...(trip.travelling_with ?? []), trip.occasion ?? ""])}
            open={open === "who"}
            onToggle={() => setOpen(open === "who" ? null : "who")}
          >
            <Field label="Travelling with">
              <Chips options={COMPANIONS} selected={trip.travelling_with ?? []} disabled={disabled} onToggle={(v) => toggle("travelling_with", v)} />
            </Field>
            <Field label="Occasion" hint="Changes what gets suggested more than you would think.">
              <input
                value={trip.occasion ?? ""}
                onChange={(e) => set("occasion", e.target.value)}
                disabled={disabled}
                placeholder="anniversary, first trip abroad, birthday"
                className={INPUT}
              />
            </Field>
          </Panel>

          <Panel
            title="Food and access"
            summary={summaryOf([...(trip.dietary ?? []), ...(trip.accessibility ?? [])])}
            open={open === "needs"}
            onToggle={() => setOpen(open === "needs" ? null : "needs")}
          >
            <Field label="Dietary">
              <Chips options={DIETARY} selected={trip.dietary ?? []} disabled={disabled} onToggle={(v) => toggle("dietary", v)} />
            </Field>
            <Field label="Getting around">
              <Chips options={ACCESSIBILITY} selected={trip.accessibility ?? []} disabled={disabled} onToggle={(v) => toggle("accessibility", v)} />
            </Field>
          </Panel>

          <Panel
            title="Stay and travel"
            summary={summaryOf([trip.stay_type ?? "", ...(trip.transport ?? [])])}
            open={open === "stay"}
            onToggle={() => setOpen(open === "stay" ? null : "stay")}
          >
            <Field label="Kind of place to stay">
              <select
                value={trip.stay_type ?? ""}
                onChange={(e) => set("stay_type", e.target.value)}
                disabled={disabled}
                className={INPUT}
              >
                <option value="">No preference</option>
                {STAY_TYPES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </Field>
            <Field label="How you would rather travel">
              <Chips options={TRANSPORT} selected={trip.transport ?? []} disabled={disabled} onToggle={(v) => toggle("transport", v)} />
            </Field>
          </Panel>

          <Panel
            title="Must include, must avoid"
            summary={summaryOf([trip.must_see ?? "", trip.avoid ?? ""])}
            open={open === "musts"}
            onToggle={() => setOpen(open === "musts" ? null : "musts")}
            wide
          >
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Must include">
                <input
                  value={trip.must_see ?? ""}
                  onChange={(e) => set("must_see", e.target.value)}
                  disabled={disabled}
                  placeholder="Taj Mahal at sunrise, a cooking class"
                  className={INPUT}
                />
              </Field>
              <Field label="Must avoid">
                <input
                  value={trip.avoid ?? ""}
                  onChange={(e) => set("avoid", e.target.value)}
                  disabled={disabled}
                  placeholder="crowded markets, early starts"
                  className={INPUT}
                />
              </Field>
            </div>
            <Field label="Anything else worth knowing">
              <textarea
                value={trip.notes ?? ""}
                onChange={(e) => set("notes", e.target.value)}
                disabled={disabled}
                rows={2}
                placeholder="We have been to Jaipur twice and would rather not repeat it."
                className={INPUT + " resize-none"}
              />
            </Field>
          </Panel>
        </div>
      </section>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={disabled || !ready}
          className="rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-ink transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {disabled ? "Planning…" : "Plan this trip"}
        </button>
        {!ready && (
          <span className="text-xs text-muted">
            A description and a starting point are all it needs.
          </span>
        )}
      </div>
    </form>
  );
}

const INPUT =
  "w-full rounded-lg border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/60 focus:outline-none disabled:opacity-50";

function countExtras(t: TripRequest): number {
  const lists = [t.dietary, t.accessibility, t.transport, t.travelling_with];
  const texts = [t.start_date, t.stay_type, t.must_see, t.avoid, t.occasion, t.notes];
  return (
    lists.reduce((n, l) => n + (l?.length ?? 0), 0) +
    texts.filter((s) => (s ?? "").trim()).length +
    (t.budget_cap_inr ? 1 : 0)
  );
}

function summaryOf(values: (string | undefined)[]): string {
  const set = values.filter((v) => (v ?? "").trim());
  if (set.length === 0) return "";
  return set.slice(0, 2).join(", ") + (set.length > 2 ? ` +${set.length - 2}` : "");
}

function Field({
  label, hint, children,
}: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-medium tracking-wide text-muted uppercase">
        {label}
      </span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-snug text-muted/70">{hint}</span>}
    </label>
  );
}

/** A closed panel that says what is inside it, so nothing set is ever hidden. */
function Panel({
  title, summary, open, onToggle, children, wide,
}: {
  title: string; summary: string; open: boolean; onToggle: () => void;
  children: React.ReactNode; wide?: boolean;
}) {
  return (
    <div className={`rounded-xl border bg-surface ${open ? "border-accent/40" : "border-line"} ${wide ? "md:col-span-2" : ""}`}>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left"
      >
        <span className={`text-[10px] text-muted transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
        <span className="text-sm font-medium text-body">{title}</span>
        {summary && !open && (
          <span className="ml-auto min-w-0 truncate text-xs text-accent-dim">{summary}</span>
        )}
      </button>
      {open && <div className="space-y-3 border-t border-line/60 px-4 py-3">{children}</div>}
    </div>
  );
}

function Chips({
  options, selected, disabled, onToggle,
}: { options: string[]; selected: string[]; disabled?: boolean; onToggle: (v: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onToggle(o)}
          disabled={disabled}
          aria-pressed={selected.includes(o)}
          className={[
            "rounded-full px-2.5 py-1 text-xs transition-colors disabled:opacity-50",
            selected.includes(o)
              ? "bg-accent/20 text-accent ring-1 ring-accent/40"
              : "bg-raised text-muted hover:text-body",
          ].join(" ")}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

function Segmented<T extends string>({
  options, value, disabled, onChange,
}: { options: T[]; value: T; disabled?: boolean; onChange: (v: T) => void }) {
  return (
    <div className="flex gap-1">
      {options.map((o) => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          disabled={disabled}
          aria-pressed={value === o}
          className={[
            "flex-1 rounded-lg border px-2 py-2 text-xs capitalize transition-colors disabled:opacity-50",
            value === o
              ? "border-accent/60 bg-accent/15 text-accent"
              : "border-line bg-raised text-muted hover:text-body",
          ].join(" ")}
        >
          {o}
        </button>
      ))}
    </div>
  );
}

function Num({
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
      className={INPUT}
    />
  );
}
