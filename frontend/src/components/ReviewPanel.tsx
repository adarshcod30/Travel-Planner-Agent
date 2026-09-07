"use client";

import { useState } from "react";
import { Markdown } from "@/lib/markdown";
import type { PlanReviewInterrupt, Revision, SectionComment } from "@/lib/types";

/**
 * v4's review gate — the draft as a document you mark up.
 *
 * The panel exists because of one property of the payload: every section
 * arrives with the specialist that produced it. So a comment does not have to
 * be interpreted before it can be acted on — pinning it to a section is
 * already the routing decision, and the panel can tell you which agent will
 * re-run before you send it.
 *
 * The run is paused at a checkpoint in Postgres while this is on screen.
 * Answering minutes or days later resumes from precisely this point and
 * re-runs nothing that came before.
 */
export function ReviewPanel({
  interrupt,
  onResume,
  busy,
}: {
  interrupt: PlanReviewInterrupt;
  onResume: (payload: { type: string; args?: unknown }) => void;
  busy?: boolean;
}) {
  const [comments, setComments] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [mode, setMode] = useState<"sections" | "respond" | "edit">("sections");
  const [feedback, setFeedback] = useState("");
  const [edited, setEdited] = useState(interrupt.draft);

  const { review, config } = interrupt;
  const pending = Object.entries(comments).filter(([, v]) => v.trim());
  const willRerun = [
    ...new Set(
      pending
        .map(([key]) => interrupt.sections.find((s) => s.key === key)?.owner)
        .filter((x): x is NonNullable<typeof x> => Boolean(x)),
    ),
  ].sort();

  const send = () =>
    onResume({
      type: "comments",
      args: pending.map(([section, comment]) => ({ section, comment: comment.trim() })),
    });

  return (
    <section className="rounded-lg border border-warn/50 bg-warn/5">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-warn/25 px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="running-dot h-1.5 w-1.5 rounded-full bg-warn" />
          <h2 className="text-sm font-semibold text-warn">Your review</h2>
        </div>
        <span className="font-mono text-[11px] text-muted">
          draft {interrupt.iteration + 1} · checkpointed ·{" "}
          {config.revision_rounds_left} revision{config.revision_rounds_left === 1 ? "" : "s"} left
        </span>
      </header>

      {review && <Audit review={review} />}
      {interrupt.revisions.length > 0 && <History revisions={interrupt.revisions} />}

      {mode === "sections" && (
        <div className="divide-y divide-line/60 border-b border-warn/20">
          {interrupt.sections.map((s) => (
            <Section
              key={s.key}
              section={s}
              value={comments[s.key] ?? ""}
              expanded={open === s.key}
              onToggle={() => setOpen(open === s.key ? null : s.key)}
              onComment={(v) => setComments({ ...comments, [s.key]: v })}
              commentable={config.allow_comments}
            />
          ))}
        </div>
      )}

      {mode === "edit" && (
        <div className="border-b border-warn/20 px-4 py-3">
          <textarea
            value={edited}
            onChange={(e) => setEdited(e.target.value)}
            rows={22}
            className="w-full resize-y rounded border border-line bg-ink p-3 font-mono text-xs text-body focus:border-accent/50 focus:outline-none"
          />
        </div>
      )}

      {mode === "respond" && (
        <div className="border-b border-warn/20 px-4 py-3">
          <textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            rows={3}
            autoFocus
            placeholder="Something about the plan as a whole — it feels rushed, the days do not flow…"
            className="w-full resize-none rounded border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none"
          />
          <p className="mt-1.5 text-[11px] text-muted/70">
            For anything that is not about one section. The orchestrator reads this and decides
            what to re-run — the one path here where a model still makes that call.
          </p>
        </div>
      )}

      <footer className="space-y-2.5 px-4 py-3">
        {mode === "sections" && pending.length > 0 && (
          <div className="rounded border border-accent/30 bg-accent/5 px-3 py-2 text-xs">
            <span className="text-bright">
              {pending.length} comment{pending.length === 1 ? "" : "s"}
            </span>
            <span className="text-muted"> · will re-run </span>
            {willRerun.map((a) => (
              <code key={a} className="mr-1 rounded bg-raised px-1 py-0.5 text-accent">
                {a}
              </code>
            ))}
            <span className="text-muted">— no orchestrator call needed</span>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          {mode === "sections" && (
            <>
              {pending.length > 0 ? (
                <Action primary disabled={busy} onClick={send}>
                  Send {pending.length} comment{pending.length === 1 ? "" : "s"}
                </Action>
              ) : (
                <Action primary disabled={busy} onClick={() => onResume({ type: "accept" })}>
                  Accept this plan
                </Action>
              )}
              {config.allow_respond && (
                <Action disabled={busy} onClick={() => setMode("respond")}>
                  Comment on the whole plan
                </Action>
              )}
              {config.allow_edit && (
                <Action disabled={busy} onClick={() => setMode("edit")}>
                  Edit directly
                </Action>
              )}
              {config.allow_ignore && (
                <Action danger disabled={busy} onClick={() => onResume({ type: "ignore" })}>
                  Discard
                </Action>
              )}
            </>
          )}

          {mode === "respond" && (
            <>
              <Action
                primary
                disabled={busy || !feedback.trim()}
                onClick={() => onResume({ type: "response", args: feedback.trim() })}
              >
                Send to the orchestrator
              </Action>
              <Action disabled={busy} onClick={() => setMode("sections")}>
                Back
              </Action>
            </>
          )}

          {mode === "edit" && (
            <>
              <Action
                primary
                disabled={busy || !edited.trim()}
                onClick={() => onResume({ type: "edit", args: { final_plan: edited } })}
              >
                Save as final
              </Action>
              <Action disabled={busy} onClick={() => setMode("sections")}>
                Back
              </Action>
            </>
          )}
        </div>

        <p className="text-[11px] text-muted/70">
          {mode === "edit"
            ? "Your text becomes the final plan verbatim; no agent runs again."
            : "Comment on the sections you want changed, or accept as-is. Everything you leave alone stays as it is."}
        </p>
      </footer>
    </section>
  );
}

/** One section, collapsed to its title until you open it. */
function Section({
  section,
  value,
  expanded,
  onToggle,
  onComment,
  commentable,
}: {
  section: PlanReviewInterrupt["sections"][number];
  value: string;
  expanded: boolean;
  onToggle: () => void;
  onComment: (v: string) => void;
  commentable: boolean;
}) {
  const canComment = commentable && Boolean(section.owner);
  return (
    <div className={value.trim() ? "bg-accent/5" : undefined}>
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-4 py-2 text-left hover:bg-raised/40"
      >
        <span className={`text-[10px] text-muted transition-transform ${expanded ? "rotate-90" : ""}`}>
          ▶
        </span>
        <span className="text-sm text-bright">{section.title}</span>
        {section.owner ? (
          <code className="rounded bg-raised px-1 py-0.5 text-[10px] text-muted">
            {section.owner}
          </code>
        ) : (
          <span className="text-[10px] text-muted/60">not revisable</span>
        )}
        {value.trim() && <span className="ml-auto text-[10px] text-accent">commented</span>}
      </button>

      {expanded && (
        <div className="space-y-2 px-4 pb-3 pl-9">
          <div className="max-h-64 overflow-y-auto rounded border border-line/60 bg-ink/40 px-3 py-2">
            <Markdown source={section.body} />
          </div>
          {canComment ? (
            <textarea
              value={value}
              onChange={(e) => onComment(e.target.value)}
              rows={2}
              placeholder={`What should change about ${section.title.toLowerCase()}? This re-runs ${section.owner}.`}
              className="w-full resize-none rounded border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none"
            />
          ) : (
            <p className="text-[11px] text-muted/70">
              No single specialist owns this section, so there is nothing to re-run for it.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function Audit({ review }: { review: NonNullable<PlanReviewInterrupt["review"]> }) {
  return (
    <div className="border-b border-warn/20 px-4 py-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span
          className={[
            "rounded px-2 py-0.5 font-medium",
            review.verdict === "approved" ? "bg-accent/15 text-accent" : "bg-warn/20 text-warn",
          ].join(" ")}
        >
          auditor: {review.verdict.replace("_", " ")}
        </span>
        <Check ok={review.budget_realistic} label="budget realistic" />
        <Check ok={review.pacing_reasonable} label="pacing reasonable" />
      </div>
      {review.issues.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {review.issues.map((issue, i) => (
            <li key={i} className="text-xs text-muted">
              • {issue}
              {review.suggestions[i] && (
                <span className="text-accent-dim"> → {review.suggestions[i]}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** What has already happened to this plan, so a fourth draft does not read like a first. */
function History({ revisions }: { revisions: Revision[] }) {
  return (
    <div className="border-b border-warn/20 px-4 py-2.5">
      <p className="mb-1.5 text-[11px] uppercase tracking-wide text-muted/70">
        {revisions.length} earlier round{revisions.length === 1 ? "" : "s"}
      </p>
      <ol className="space-y-1">
        {revisions.map((r, i) => (
          <li key={i} className="text-xs text-muted">
            <span className="font-mono text-[10px] text-muted/60">#{r.iteration + 1}</span>{" "}
            {describe(r)}
            {r.agents_rerun.length > 0 && (
              <span className="text-accent-dim"> → re-ran {r.agents_rerun.join(", ")}</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

function describe(r: Revision): string {
  if (r.decision === "comments") return summarise(r.comments);
  if (r.decision === "response") return `asked for: ${r.feedback ?? ""}`;
  return r.decision;
}

function summarise(comments: SectionComment[]): string {
  if (comments.length === 0) return "commented";
  const first = comments[0];
  const rest = comments.length - 1;
  return `${first.section}: ${first.comment}${rest > 0 ? ` (+${rest} more)` : ""}`;
}

function Check({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={ok ? "text-accent-dim" : "text-danger"}>
      {ok ? "✓" : "✕"} {label}
    </span>
  );
}

function Action({
  children,
  onClick,
  disabled,
  primary,
  danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={[
        "rounded-md px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        primary
          ? "bg-accent text-ink hover:opacity-90"
          : danger
            ? "border border-danger/40 text-danger hover:bg-danger/10"
            : "border border-line bg-raised text-body hover:border-muted/50",
      ].join(" ")}
    >
      {children}
    </button>
  );
}
