import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Travel Planner Agent",
  description:
    "Five generations of a multi-agent travel planner — linear, parallel, orchestrated, human-in-the-loop and MCP browser automation — running side by side behind one Aegra server.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <header className="sticky top-0 z-10 border-b border-line bg-ink/80 backdrop-blur">
          <div className="mx-auto flex max-w-[1600px] items-center justify-between px-5 py-3">
            <div className="flex items-baseline gap-3">
              <Link href="/" className="text-sm font-semibold text-bright">
                Travel Planner Agent
              </Link>
              <span className="hidden text-xs text-muted sm:inline">
                five architectures, one Aegra server
              </span>
            </div>
            <nav className="flex gap-1 text-xs">
              <NavLink href="/">Planner</NavLink>
              <NavLink href="/compare">Compare</NavLink>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-5 py-5">{children}</main>
      </body>
    </html>
  );
}

function NavLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="rounded px-2.5 py-1 text-muted transition-colors hover:bg-raised hover:text-body"
    >
      {children}
    </Link>
  );
}
