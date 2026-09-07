import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 writes AGENTS.md and TOOLING.md into the project on every dev
  // start. They are assistant scratch files, not part of this project, and
  // this repository is read as its author's own work — so they are turned off
  // at the source rather than deleted after the fact and re-created on the
  // next `npm run dev`. `tests/unit/test_repo_hygiene.py` holds the line.
  agentRules: false,
};

export default nextConfig;
