"use client";

import { useEffect, useRef, useState } from "react";
import { frameUrl, getHandover, releaseBrowser, sendAction } from "@/lib/aegra";
import type { Frame, HandoverState } from "@/lib/types";

/**
 * The browser, as you would watch it over someone's shoulder — and take from
 * them when it gets stuck.
 *
 * The frames are screenshots streamed from the run, newest first, with the
 * filmstrip beneath. Nothing here polls the browser for a picture: the run
 * pushes each frame as it takes it, so what you see is what it saw when it
 * made its decision.
 *
 * When the run hits a login wall it stops and offers you the browser. Clicking
 * the screenshot is a real click on the real page — the screenshots are
 * viewport-sized at devicePixelRatio 1, so a click at (x, y) in the image is a
 * click at (x, y) on the page, and the only translation needed is for the
 * image being scaled to fit this panel.
 */
const PAGE_WIDTH = 1280;
const PAGE_HEIGHT = 720;

export function BrowserStage({
  frames,
  threadId,
  compact,
}: {
  frames: Frame[];
  threadId: string | null;
  compact?: boolean;
}) {
  const [index, setIndex] = useState<number | null>(null);
  const [handover, setHandover] = useState<HandoverState | null>(null);
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState<string>();
  const [typed, setTyped] = useState("");
  const imgRef = useRef<HTMLImageElement>(null);

  const live = index === null;
  const shown = live ? frames[frames.length - 1] : frames[index];

  // Whether a person is wanted is the run's business, so it is polled rather
  // than inferred from the event stream — a client that reconnected mid-run
  // would otherwise never learn a handover was already open.
  useEffect(() => {
    if (!threadId) return;
    let alive = true;
    const tick = async () => {
      try {
        const h = await getHandover(threadId);
        if (alive) setHandover(h);
      } catch {
        /* the run may have moved on; the next tick will say so */
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [threadId]);

  const act = async (action: Parameters<typeof sendAction>[1]) => {
    if (!threadId) return;
    setSending(true);
    setNote(undefined);
    try {
      const res = await sendAction(threadId, action);
      if (!res.ok) setNote(res.error ?? "That did not work.");
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  const clickImage = (e: React.MouseEvent<HTMLImageElement>) => {
    if (!handover || !imgRef.current) return;
    const box = imgRef.current.getBoundingClientRect();
    // The image is scaled to fit; the page is not. Undo the fit.
    const x = Math.round(((e.clientX - box.left) / box.width) * PAGE_WIDTH);
    const y = Math.round(((e.clientY - box.top) / box.height) * PAGE_HEIGHT);
    void act({ kind: "click_at", x, y });
  };

  if (frames.length === 0 && !handover) {
    return (
      <Empty>
        Screenshots appear here while v5 browses. The earlier versions do not open a
        browser, so there is nothing to watch.
      </Empty>
    );
  }

  return (
    <section className="overflow-hidden rounded-lg border border-line bg-surface">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
        <h2 className="text-xs font-medium tracking-wide text-muted uppercase">Browser</h2>
        {shown?.url && (
          <a
            href={shown.url}
            target="_blank"
            rel="noreferrer noopener"
            className="max-w-md truncate font-mono text-[11px] text-info hover:underline"
            title={shown.url}
          >
            {shown.url}
          </a>
        )}
        <span className="ml-auto flex items-center gap-2 font-mono text-[11px] text-muted">
          {frames.length > 0 && (
            <>
              frame {(live ? frames.length : index + 1)} / {frames.length}
              {!live && (
                <button
                  onClick={() => setIndex(null)}
                  className="rounded border border-line px-1.5 py-0.5 text-[10px] text-body hover:border-muted/50"
                >
                  back to live
                </button>
              )}
            </>
          )}
        </span>
      </header>

      {handover && <TakeoverBar handover={handover} threadId={threadId!} onDone={() => setHandover(null)} />}

      <div className="relative bg-ink">
        {shown ? (
          /* A live screenshot from our own API, already a small viewport
             JPEG. Routing it through the Next image optimiser would add a hop
             to something that changes every second and is never usefully
             cached — and would need remotePatterns for a run-local URL. */
          // eslint-disable-next-line @next/next/no-img-element
          <img
            ref={imgRef}
            src={frameUrl(shown.path)}
            alt={shown.note || "browser screenshot"}
            onClick={clickImage}
            className={[
              "w-full object-contain",
              compact ? "max-h-[340px]" : "max-h-[62vh]",
              handover ? "cursor-crosshair" : "",
            ].join(" ")}
          />
        ) : (
          <div className="flex h-48 items-center justify-center text-xs text-muted">
            waiting for the first screenshot…
          </div>
        )}
        {shown?.note && (
          <p className="absolute bottom-0 left-0 right-0 truncate bg-ink/80 px-3 py-1 text-[11px] text-muted">
            {shown.note}
          </p>
        )}
      </div>

      {handover && (
        <Controls
          handover={handover}
          typed={typed}
          setTyped={setTyped}
          sending={sending}
          note={note}
          act={act}
          onRelease={async () => {
            await releaseBrowser(threadId!);
            setHandover(null);
          }}
        />
      )}

      {frames.length > 1 && (
        <div className="flex gap-1.5 overflow-x-auto border-t border-line px-3 py-2">
          {frames.map((f, i) => (
            <button
              key={f.path}
              onClick={() => setIndex(i === frames.length - 1 ? null : i)}
              title={f.note || f.url || ""}
              className={[
                "h-12 w-20 shrink-0 overflow-hidden rounded border transition-colors",
                (live ? i === frames.length - 1 : i === index)
                  ? "border-accent"
                  : "border-line hover:border-muted/50",
              ].join(" ")}
            >
              {/* Same run-local screenshots as the stage above. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={frameUrl(f.path)} alt="" className="h-full w-full object-cover" />
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

function TakeoverBar({
  handover,
  onDone,
}: {
  handover: HandoverState;
  threadId: string;
  onDone: () => void;
}) {
  const left = Math.max(0, 300 - handover.waited_seconds);
  return (
    <div
      className={[
        "border-b px-3 py-2",
        handover.terminal ? "border-danger/40 bg-danger/10" : "border-warn/40 bg-warn/10",
      ].join(" ")}
    >
      <p className={`text-xs font-medium ${handover.terminal ? "text-danger" : "text-warn"}`}>
        {handover.terminal ? "This is the payment page — it is yours" : "The browser needs you"}
      </p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-muted">
        {handover.terminal
          ? "Card, UPI and bank details are yours to enter. The planner does not touch them and will not take the browser back."
          : "Click the screenshot to click the page, or use the controls below. The run is paused and holding this browser open."}
        {!handover.terminal && left > 0 && (
          <span className="text-muted/70"> It closes on its own in {Math.round(left)}s.</span>
        )}
      </p>
      {handover.released && (
        <button onClick={onDone} className="mt-1 text-[11px] text-accent underline">
          dismiss
        </button>
      )}
    </div>
  );
}

function Controls({
  handover,
  typed,
  setTyped,
  sending,
  note,
  act,
  onRelease,
}: {
  handover: HandoverState;
  typed: string;
  setTyped: (v: string) => void;
  sending: boolean;
  note?: string;
  act: (a: Parameters<typeof sendAction>[1]) => Promise<void>;
  onRelease: () => Promise<void>;
}) {
  const fields = handover.elements.filter((e) =>
    ["textbox", "searchbox", "combobox"].includes(e.role),
  );
  const buttons = handover.elements.filter((e) => ["button", "link"].includes(e.role) && e.name);

  return (
    <div className="space-y-2.5 border-b border-line px-3 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder="Type into the focused field…"
          className="min-w-48 flex-1 rounded border border-line bg-ink px-2.5 py-1.5 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none"
          onKeyDown={(e) => {
            if (e.key !== "Enter" || !typed) return;
            void act({ kind: "type_at", text: typed }).then(() => setTyped(""));
          }}
        />
        <Btn disabled={sending || !typed} onClick={() => act({ kind: "type_at", text: typed }).then(() => setTyped(""))}>
          Type
        </Btn>
        <Btn disabled={sending} onClick={() => act({ kind: "press", key: "Enter" })}>
          Enter
        </Btn>
        <Btn disabled={sending} onClick={() => act({ kind: "press", key: "Tab" })}>
          Tab
        </Btn>
        <Btn disabled={sending} onClick={() => act({ kind: "scroll", y: 500 })}>
          Scroll ↓
        </Btn>
        <Btn disabled={sending} onClick={() => act({ kind: "scroll", y: -500 })}>
          Scroll ↑
        </Btn>
        <Btn disabled={sending} onClick={() => act({ kind: "back" })}>
          Back
        </Btn>
        <Btn primary disabled={sending} onClick={onRelease}>
          {handover.terminal ? "Close the browser" : "I'm done — continue"}
        </Btn>
      </div>

      {(fields.length > 0 || buttons.length > 0) && (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted hover:text-body">
            Or pick an element by name ({handover.elements.length} on this page)
          </summary>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {[...fields, ...buttons].slice(0, 24).map((el) => (
              <button
                key={el.ref}
                disabled={sending}
                onClick={() =>
                  act(
                    fields.includes(el) && typed
                      ? { kind: "type", ref: el.ref, label: el.name, text: typed }
                      : { kind: "click", ref: el.ref, label: el.name },
                  )
                }
                className="rounded border border-line bg-raised px-2 py-1 text-[11px] text-body hover:border-muted/50 disabled:opacity-40"
                title={`${el.role} — ${el.ref}`}
              >
                {el.name.slice(0, 40)}
              </button>
            ))}
          </div>
        </details>
      )}

      {note && <p className="text-[11px] text-danger">{note}</p>}
    </div>
  );
}

function Btn({
  children,
  onClick,
  disabled,
  primary,
}: {
  children: React.ReactNode;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  primary?: boolean;
}) {
  return (
    <button
      onClick={() => void onClick()}
      disabled={disabled}
      className={[
        "rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40",
        primary
          ? "bg-accent text-ink hover:opacity-90"
          : "border border-line bg-raised text-body hover:border-muted/50",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-40 items-center justify-center rounded-lg border border-dashed border-line px-6 py-10 text-center">
      <p className="max-w-sm text-xs leading-relaxed text-muted">{children}</p>
    </div>
  );
}
