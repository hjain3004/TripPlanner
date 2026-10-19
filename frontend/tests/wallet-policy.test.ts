import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  balanceSummary,
  balancesFromInput,
  failureOf,
  isConflict,
  last4FromInput,
  nicknameOr,
} from "../src/components/product/wallet/wallet-policy";

describe("wallet failure decoding", () => {
  it("reads the server's typed code and message", () => {
    const failure = failureOf({
      detail: { code: "wallet_version_conflict", message: "Reload and retry." },
    });
    expect(failure).toEqual({
      code: "wallet_version_conflict",
      message: "Reload and retry.",
    });
  });

  it("degrades safely on an unrecognised error shape", () => {
    for (const weird of [null, undefined, "boom", 42, {}, { detail: "nope" }]) {
      const failure = failureOf(weird);
      expect(failure.code).toBe("unknown");
      expect(failure.message.length).toBeGreaterThan(0);
    }
  });

  it("treats both conflict codes as conflicts and nothing else", () => {
    expect(isConflict({ code: "wallet_version_conflict", message: "" })).toBe(true);
    expect(isConflict({ code: "wallet_event_conflict", message: "" })).toBe(true);
    expect(isConflict({ code: "wallet_entry_not_found", message: "" })).toBe(false);
    expect(isConflict({ code: "unknown", message: "" })).toBe(false);
    expect(isConflict(null)).toBe(false);
  });
});

describe("wallet balance rendering", () => {
  it("prints stored balances without summing or converting them", () => {
    // Two currencies stay separate; the optimizer owns all points math.
    expect(balanceSummary({ "hdfc-reward-points": 1000, lionmiles: 250 })).toBe(
      "1,000 hdfc-reward-points · 250 lionmiles",
    );
  });

  it("is deterministic regardless of key insertion order", () => {
    expect(balanceSummary({ b: 2, a: 1 })).toBe(balanceSummary({ a: 1, b: 2 }));
  });

  it("says so plainly when nothing is recorded", () => {
    expect(balanceSummary({})).toBe("No balance recorded");
  });
});

describe("wallet input shaping", () => {
  it("omits a balance unless both currency and a real number are given", () => {
    expect(balancesFromInput("", "100")).toEqual({});
    expect(balancesFromInput("  ", "100")).toEqual({});
    expect(balancesFromInput("pts", "")).toEqual({});
    expect(balancesFromInput("pts", "abc")).toEqual({});
    expect(balancesFromInput(" pts ", "100")).toEqual({ pts: 100 });
  });

  it("sends null rather than an empty string for an omitted last4", () => {
    expect(last4FromInput("")).toBeNull();
    expect(last4FromInput("   ")).toBeNull();
    expect(last4FromInput(" 1234 ")).toBe("1234");
  });

  it("falls back rather than submitting a blank nickname", () => {
    expect(nicknameOr("", "My card")).toBe("My card");
    expect(nicknameOr("   ", "Existing")).toBe("Existing");
    expect(nicknameOr(" Travel card ", "My card")).toBe("Travel card");
  });
});

describe("the wallet surface performs no financial arithmetic", () => {
  // CLAUDE.md non-negotiable 1: the frontend renders server fields and never
  // computes a reward, fee or points value. A structural check is worth more
  // than a behavioural one here, because a regression would be a *new*
  // calculation that no existing assertion would happen to cover.
  const sources = [
    "src/components/product/wallet/wallet-policy.ts",
    "src/components/product/wallet/wallet-panel.tsx",
  ];

  it.each(sources)("%s contains no multiplication or division", (file) => {
    const body = readFileSync(file, "utf8")
      .split("\n")
      // Ignore comments and JSX/TS path-ish lines where * and / are structural.
      .filter((line) => {
        const trimmed = line.trim();
        return !trimmed.startsWith("*") && !trimmed.startsWith("//") && !trimmed.startsWith("/*");
      })
      .join("\n")
      // Strip import specifiers and JSX closing slashes before scanning.
      .replace(/^import[\s\S]*?;$/gm, "")
      .replace(/<\//g, "")
      .replace(/\/>/g, "");

    expect(body).not.toMatch(/[a-zA-Z0-9_)\]]\s*\*\s*[a-zA-Z0-9_(]/);
    expect(body).not.toMatch(/[a-zA-Z0-9_)\]]\s*\/\s*[a-zA-Z0-9_(]/);
  });

  it.each(sources)("%s uses no rounding or float coercion helpers", (file) => {
    const body = readFileSync(file, "utf8");
    for (const banned of ["toFixed", "Math.round", "Math.floor", "Math.ceil", "parseFloat", "Number("]) {
      expect(body).not.toContain(banned);
    }
  });
});
