import { describe, expect, it } from "vitest";
import {
  getPreferenceSourceLabel,
  getPreferenceStatusLabel,
} from "../src/components/product/profile/profile-policy";
import { buildPreferencePatch, emptyPreferencePatch, projectTravelPreferences } from "../src/components/product/profile/profile-projection";
import type { TravelPreferenceProfile } from "../src/lib/api";

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

  it("projects every persisted group without inventing values", () => {
    const profile = {
      user_id: "user-1",
      updated_at: "2026-08-29T00:00:00Z",
      flight: {
        cabin: { value: "business", source: "user_profile_edit", updated_at: "2026-08-28T00:00:00Z" },
      },
      stay: {},
      rhythm: {},
      experiences: {},
      constraints: {},
      optimization: {},
    } as TravelPreferenceProfile;
    const groups = projectTravelPreferences(profile);
    expect(groups).toHaveLength(6);
    expect(groups.map((group) => group.id)).toEqual([
      "flight", "stay", "rhythm", "experiences", "constraints", "optimization",
    ]);
    expect(groups[0]?.fields.find((field) => field.id === "cabin")).toMatchObject({
      value: "business",
      source: "profile",
    });
    expect(groups[1]?.updateStatus).toBe("not-set");
    expect(groups[1]?.fields[0]?.value).toBe("Not set");
  });

  it("keeps trip-confirmed provenance distinguishable from an edit", () => {
    const profile = {
      user_id: "user-1",
      updated_at: "2026-08-29T00:00:00Z",
      flight: {},
      stay: {},
      rhythm: {},
      experiences: {
        interests: { value: ["culture", "food"], source: "user_confirmed_from_trip", updated_at: "2026-08-20T00:00:00Z" },
      },
      constraints: {},
      optimization: {},
    } as TravelPreferenceProfile;
    const interests = projectTravelPreferences(profile)[3]?.fields.find((field) => field.id === "interests");
    expect(interests).toMatchObject({ value: "culture, food", source: "confirmed" });
    expect(getPreferenceSourceLabel("confirmed")).toBe("Saved from a trip");
  });

  it("serializes list and labelled values into the typed profile patch", () => {
    const patch = buildPreferencePatch("flight", {
      cabin: "Business",
      max_stops: 1,
      schedule: "Morning",
      checked_baggage: "Yes",
      airport_flexible: "No",
      seat: "Window",
    }, "2026-08-29T00:00:00Z");
    expect(patch.flight?.cabin?.value).toBe("business");
    expect(patch.flight?.checked_baggage?.value).toBe(true);
    expect(patch.flight?.seat?.value).toBe("window");
  });

  it("uses explicit empty leaves for reset, rather than fake defaults", () => {
    const patch = emptyPreferencePatch("optimization");
    expect(patch.optimization).toEqual({ objective: null, points_priority: null });
  });
});
