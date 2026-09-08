import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Travel Planner Agent",
  description:
    "Five generations of a multi-agent travel planner — linear, parallel, orchestrated, human-in-the-loop and MCP browser automation — running side by side behind one Aegra server.",
};

/**
 * Nothing but the document.
 *
 * The chrome used to live here — a header and a max-width main — which meant
 * the planner had two headers once it grew its own view switcher, and the
 * access page inherited navigation it had no business showing. Each page now
 * brings its own frame: the planner has `Shell`, and the others say what they
 * need in one wrapper.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
