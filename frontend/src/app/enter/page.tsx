"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** Where the middleware sends anyone without a valid access cookie. */
export default function EnterPage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(undefined);
    const res = await fetch("/api/enter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code }),
    });
    if (res.ok) {
      // replace() rather than push() so Back does not return to a sign-in page
      // that will now just bounce; refresh() re-runs the middleware with the
      // cookie the response just set.
      router.replace("/");
      router.refresh();
    } else {
      setError("That code is not right.");
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-5">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-line bg-surface p-6">
        <div>
          <h1 className="text-base font-semibold text-bright">Travel Planner Agent</h1>
          <p className="mt-1 text-xs text-muted">
            This instance is shared with an access code. Ask whoever sent you the link.
          </p>
        </div>

        <input
          type="password"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          autoFocus
          placeholder="Access code"
          className="w-full rounded-md border border-line bg-ink px-3 py-2 text-sm text-body placeholder:text-muted/50 focus:border-accent/50 focus:outline-none"
        />

        {error && <p className="text-xs text-danger">{error}</p>}

        <button
          type="submit"
          disabled={busy || !code.trim()}
          className="w-full rounded-md bg-accent px-4 py-2 text-sm font-semibold text-ink transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Checking…" : "Enter"}
        </button>
      </form>
    </div>
  );
}
