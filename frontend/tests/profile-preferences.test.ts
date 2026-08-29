import { describe, expect, it } from "vitest";
import {
  getPreferenceSourceLabel,
  getPreferenceStatusLabel,
} from "../src/components/product/profile/profile-policy";

describe("profile preference display policy", () => {
  it("names where a saved preference came from", () => {
    expect(getPreferenceSourceLabel("profile")).toBe("Saved preference");
    expect(getPreferenceSourceLabel("trip")).toBe("This trip only");
    expect(getPreferenceSourceLabel("default")).toBe("TripPlanner default");
  });

  it("uses actionable labels for update state", () => {
    expect(getPreferenceStatusLabel("saved")).toBe("Saved");
    expect(getPreferenceStatusLabel("pending")).toBe("Changes pending");
    expect(getPreferenceStatusLabel("needs-review")).toBe("Review suggested");
  });
});
