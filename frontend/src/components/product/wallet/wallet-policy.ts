/**
 * Pure display and request-shaping logic for the wallet surface (A3).
 *
 * Extracted from `wallet-panel.tsx` so it is unit-testable without a DOM, which
 * is this project's existing pattern (see `profile-policy.ts`). Nothing here
 * computes a reward, a fee, or a points valuation — balances are rendered as the
 * server stored them.
 */

export type ApiFailure = { code: string; message: string };

export const WALLET_CONFLICT_CODES = [
  "wallet_version_conflict",
  "wallet_event_conflict",
] as const;

/** Pull the server's typed `{code, message}` out of a FastAPI error envelope. */
export function failureOf(error: unknown): ApiFailure {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (detail !== null && typeof detail === "object" && "code" in detail) {
    const typed = detail as { code?: unknown; message?: unknown };
    return {
      code: typeof typed.code === "string" ? typed.code : "unknown",
      message:
        typeof typed.message === "string"
          ? typed.message
          : "That request could not be completed.",
    };
  }
  return {
    code: "unknown",
    message: "That request could not be completed. Please try again.",
  };
}

export function isConflict(failure: ApiFailure | null): boolean {
  if (failure === null) return false;
  return (WALLET_CONFLICT_CODES as readonly string[]).includes(failure.code);
}

/**
 * Render a stored balance map as text.
 *
 * Values are printed, never summed or converted — the optimizer owns every
 * points calculation.
 */
export function balanceSummary(balances: Record<string, number>): string {
  const parts = Object.keys(balances)
    .sort()
    .map((currency) => `${(balances[currency] ?? 0).toLocaleString()} ${currency}`);
  return parts.length > 0 ? parts.join(" · ") : "No balance recorded";
}

/** Build a `points_balances` map from the two free-text inputs. */
export function balancesFromInput(
  currency: string,
  amount: string,
): Record<string, number> {
  const key = currency.trim();
  if (key === "") return {};
  const parsed = Number.parseInt(amount, 10);
  if (!Number.isFinite(parsed)) return {};
  return { [key]: parsed };
}

/** Normalise the optional last4 input: blank means "not provided", not "". */
export function last4FromInput(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** A nickname always has a value; blank falls back rather than failing. */
export function nicknameOr(value: string, fallback: string): string {
  const trimmed = value.trim();
  return trimmed === "" ? fallback : trimmed;
}
