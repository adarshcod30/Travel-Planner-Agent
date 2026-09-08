"use client";

import type { VersionMeta } from "@/lib/types";

/**
 * What this is, and how it works.
 *
 * Written for someone who has just been sent the link, in the order they will
 * ask: what am I looking at, what happens when I press the button, why are
 * there five of these, and what will it not do. The version cards come from
 * the server's own `/versions` route rather than being restated here, so this
 * page cannot drift from what is actually running.
 */
export function AboutView({ versions }: { versions: VersionMeta[] }) {
  return (
    <div className="max-w-4xl space-y-10 pb-12">
      <header className="space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight text-bright">
          Five ways to plan the same trip
        </h1>
        <p className="text-base leading-relaxed text-body">
          This is one travel planner built five times over. Each version is a working
          system that adds exactly one idea to the one before it, and all five run side by
          side behind a single server — so you can put the same request through two of them
          and see what the idea actually bought, rather than take anyone&apos;s word for it.
        </p>
        <p className="text-sm leading-relaxed text-muted">
          Trips start from India and everything is priced in rupees. The models run on AWS
          Bedrock; the browsing is a real Chromium you can watch and take over.
        </p>
      </header>

      <Section title="What happens when you press Plan">
        <ol className="space-y-3">
          {[
            ["Intake", "Your brief is normalised — day counts clamped, budget level checked, interests split into a list. Nothing is interpreted here; that is a specialist's job."],
            ["Research", "Only in the later versions. Reference data first — station codes, hotel GST slabs, festival dates, today's exchange rate — and in v5, a real browser reading real pages."],
            ["Specialists", "Up to seven of them, several at once: destination, weather, attractions, budget, hotels, local customs, packing. Each returns a structured object, not prose."],
            ["Assembly", "An itinerary agent turns all of that into days, and a reviewer audits the result against the brief — is the budget realistic, is the pacing sane."],
            ["You", "From v4 the plan comes to you as sections you can comment on. From v5 it can then open real booking pages while you watch."],
          ].map(([step, body], i) => (
            <li key={step} className="flex gap-3">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-raised font-mono text-[11px] text-accent">
                {i + 1}
              </span>
              <div className="min-w-0">
                <h3 className="text-sm font-medium text-bright">{step}</h3>
                <p className="mt-0.5 text-sm leading-relaxed text-muted">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section title="The five versions">
        <div className="space-y-2">
          {versions.map((v) => (
            <article key={v.graph_id} className="rounded-xl border border-line bg-surface p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold text-accent">{v.label}</h3>
                <span className="font-mono text-[10px] text-muted">
                  {v.graph_id} · {v.agents.length} agents
                </span>
              </div>
              <p className="mt-1 text-sm text-body">{v.headline}</p>
              <p className="mt-2 text-sm leading-relaxed text-muted">{v.notes}</p>
            </article>
          ))}
        </div>
      </Section>

      <Section title="Watching it work, and taking over">
        <p className="text-sm leading-relaxed text-body">
          v5 opens a real browser. Every navigation, refusal and click arrives as an event
          and captures a screenshot, streamed on the same connection as the plan — so the
          browsing is something you watch rather than a summary you are handed afterwards.
        </p>
        <p className="text-sm leading-relaxed text-body">
          When a site wants a login, the run stops and offers you the browser. Clicking the
          screenshot clicks the real page; there are controls for typing, Enter, Tab,
          scrolling and Back. When you say you are done, the run picks up where it was.
        </p>
        <Aside title="Why that is harder than it sounds">
          Pausing for a plan review is easy: the run checkpoints and stops, and can be
          answered days later. A browser handover cannot work that way — stopping the run
          would close the Chromium you were about to take over. So the run stays alive and
          blocks, holding the browser open, which is why a handover expires after a few
          minutes and a plan review does not.
        </Aside>
      </Section>

      <Section title="What it will not do">
        <p className="text-sm leading-relaxed text-body">
          It never enters card, UPI or bank details, and never completes a purchase — on
          any setting. A page asking for payment ends the automated part and hands you the
          browser for good.
        </p>
        <p className="text-sm leading-relaxed text-muted">
          Two smaller rules follow from that one. Text you type during a handover is never
          written to the activity log — it records &ldquo;12 characters into
          Password&rdquo;, never the characters. And the browser only accepts a fixed set
          of instructions, so anything unexpected is refused rather than interpreted.
        </p>
      </Section>

      <Section title="Under it">
        <dl className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          {[
            ["Orchestration", "LangGraph — five topologies over one shared state"],
            ["Serving", "Aegra, the Agent Protocol, running natively"],
            ["Models", "Amazon Nova on Bedrock, tiered by how hard the agent's job is"],
            ["Memory", "A knowledge graph over MCP, so a second trip starts better than the first"],
            ["Browsing", "Playwright over MCP, headed — headless is refused by the booking sites"],
            ["Storage", "PostgreSQL. A finished trip keeps its plan and deletes everything that produced it"],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] font-medium tracking-wide text-muted uppercase">{k}</dt>
              <dd className="text-sm text-body">{v}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <Section title="A note on what it costs you">
        <p className="text-sm leading-relaxed text-muted">
          This is a shared instance: everyone using it shares one memory, so what your
          trips teach it, the next person&apos;s plans inherit. Finishing a plan keeps it in
          History and reclaims the run behind it — around 110 KB per run that nothing will
          ever read again.
        </p>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="border-b border-line pb-2 text-lg font-semibold text-bright">{title}</h2>
      {children}
    </section>
  );
}

function Aside({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <h4 className="text-xs font-medium tracking-wide text-accent-dim uppercase">{title}</h4>
      <p className="mt-1.5 text-sm leading-relaxed text-muted">{children}</p>
    </div>
  );
}
