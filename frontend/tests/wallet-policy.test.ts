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
