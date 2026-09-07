/**
 * A shared access code for the whole app.
 *
 * Off by default: with `APP_ACCESS_CODE` unset there is no gate at all, so
 * local development and LAN sharing on a trusted network are unchanged. Set it
 * and every page and every API route requires the code.
 *
 * This is deliberately modest — one shared secret, not accounts. It exists
 * because a public tunnel puts the planner on the open internet, where every
 * run spends from the operator's AWS account and an unauthenticated URL is a
 * standing invitation. A shared code is the proportionate answer for a demo
 * link; a real deployment wants an identity provider in the reverse proxy.
 */

export const COOKIE_NAME = "tp_access";

export function accessCode(): string | undefined {
  const code = process.env.APP_ACCESS_CODE?.trim();
  return code ? code : undefined;
}

export function gateEnabled(): boolean {
  return accessCode() !== undefined;
}

/**
 * Compare in constant time.
 *
 * A `===` on a secret leaks its length and, in principle, its prefix through
 * timing. The cost of avoiding that here is nil, and the habit is worth more
 * than the specific risk.
 */
export function codeMatches(candidate: string | undefined): boolean {
  const expected = accessCode();
  if (!expected) return true;
  if (!candidate) return false;

  const a = new TextEncoder().encode(candidate);
  const b = new TextEncoder().encode(expected);
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  }
  return diff === 0;
}
