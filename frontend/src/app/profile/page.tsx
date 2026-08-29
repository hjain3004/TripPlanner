"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { SiteHeader } from "@/components/product/site-header";
import { ProfilePreferences } from "@/components/product/profile";
import type {
  PreferenceDraft,
  ProfilePreferenceGroup,
} from "@/components/product/profile";
import { getPreferencesPlanningPreferencesGet, patchPreferencesPlanningPreferencesPatch, removePreferencesPlanningPreferencesSectionDelete } from "@/lib/api";
import { apiClient, csrfHeaders } from "@/lib/api/client-config";

const NO_PREFERENCE = "No preference — choose for me";

const DEFAULT_GROUPS: readonly ProfilePreferenceGroup[] = [
  {
    id: "travel-style",
    title: "Travel style",
    description: "The pace and shape of a trip you usually enjoy.",
    source: "profile",
    updateStatus: "saved",
    updatedAt: "28 Aug 2026",
    fields: [
      {
        id: "pace",
        label: "Typical pace",
        value: "Balanced",
        type: "select",
        options: ["Slow", "Balanced", "Full days", NO_PREFERENCE],
        description: "Used as a starting point, never a hard rule.",
      },
      {
        id: "planning_style",
        label: "Planning style",
        value: "A considered mix of landmarks and local places",
        type: "text",
      },
    ],
  },
  {
    id: "comfort-accessibility",
    title: "Comfort & accessibility",
    description: "Needs that should be visible before an itinerary is built.",
    source: "profile",
    updateStatus: "needs-review",
    updatedAt: "12 Aug 2026",
    fields: [
      {
        id: "mobility",
        label: "Mobility support",
        value: NO_PREFERENCE,
        type: "select",
        options: [NO_PREFERENCE, "Step-free routes", "Limited walking", "Wheelchair access"],
      },
      {
        id: "dietary",
        label: "Dietary notes",
        value: NO_PREFERENCE,
        type: "text",
        description: "Only add what you want considered during planning.",
      },
    ],
  },
  {
    id: "rewards-objective",
    title: "Rewards objective",
    description: "The trade-off you want the planner to make explicit.",
    source: "imported",
    updateStatus: "pending",
    updatedAt: "From your wallet",
    fields: [
      {
        id: "points_priority",
        label: "Points priority",
        value: "Best overall value",
        type: "select",
        options: ["Best overall value", "Lowest cash today", "Keep my points"],
      },
      {
        id: "cabin",
        label: "Preferred cabin",
        value: NO_PREFERENCE,
        type: "select",
        options: [NO_PREFERENCE, "Economy", "Premium economy", "Business"],
      },
    ],
  },
];

const defaultValues = new Map(
  DEFAULT_GROUPS.map((group) => [
    group.id,
    Object.fromEntries(group.fields.map((field) => [field.id, NO_PREFERENCE])),
  ])
);

function updateGroup(
  groups: readonly ProfilePreferenceGroup[],
  groupId: string,
  values: PreferenceDraft,
  status: ProfilePreferenceGroup["updateStatus"] = "saved",
  source?: ProfilePreferenceGroup["source"],
  updatedAt?: string,
): ProfilePreferenceGroup[] {
  return groups.map((group) =>
    group.id === groupId
      ? {
          ...group,
          updateStatus: status,
          source: source ?? group.source,
          updatedAt: updatedAt ?? group.updatedAt,
          fields: group.fields.map((field) =>
            Object.prototype.hasOwnProperty.call(values, field.id)
              ? { ...field, value: values[field.id]! }
              : field
          ),
        }
      : group
  );
}

export default function ProfilePage() {
  const [groups, setGroups] = useState<readonly ProfilePreferenceGroup[]>(DEFAULT_GROUPS);
  const [profileState, setProfileState] = useState<"loading" | "connected" | "offline">("loading");

  useEffect(() => {
    let active = true;
    void getPreferencesPlanningPreferencesGet({ client: apiClient }).then((result) => {
      if (!active) return;
      if (!result.data) { setProfileState("offline"); return; }
      const profile = result.data.profile;
      const leaf = (section: keyof typeof profile, field: string): unknown => {
        const group = profile[section] as Record<string, { value?: unknown }> | null | undefined;
        return group?.[field]?.value;
      };
      const pace = leaf("rhythm", "pace");
      const accessibility = leaf("constraints", "accessibility");
      const points = leaf("optimization", "points_priority");
      setGroups((current) => current.map((group) => {
        if (group.id === "travel-style" && pace) return updateGroup(current, group.id, { pace: String(pace).replace("moderate", "Balanced").replace("relaxed", "Slow").replace("packed", "Full days") }, "saved", "profile")[0] ?? group;
        if (group.id === "comfort-accessibility" && accessibility) return updateGroup(current, group.id, { mobility: Array.isArray(accessibility) ? accessibility.join(", ") : String(accessibility) }, "saved", "profile")[1] ?? group;
        if (group.id === "rewards-objective" && points) return updateGroup(current, group.id, { points_priority: String(points).replaceAll("_", " ") }, "saved", "profile")[2] ?? group;
        return group;
      }));
      setProfileState("connected");
    }).catch(() => { if (active) setProfileState("offline"); });
    return () => { active = false; };
  }, []);

  const handleSave = (groupId: string, values: PreferenceDraft) => {
    setGroups((current) => updateGroup(current, groupId, values));
    const now = new Date().toISOString();
    const leaf = (value: unknown) => ({ value, source: "user_profile_edit" as const, updated_at: now });
    const patch = (groupId === "travel-style"
      ? { rhythm: { pace: leaf(String(values.pace ?? "moderate").toLowerCase().replace("full days", "packed").replace("slow", "relaxed").replace("balanced", "moderate")) } }
      : groupId === "rewards-objective"
        ? { optimization: { points_priority: leaf(String(values.points_priority ?? "best_value").toLowerCase().replaceAll(" ", "_")) } }
        : { constraints: { accessibility: leaf(String(values.mobility ?? "" ).split(",").filter(Boolean)) } }) as Parameters<typeof patchPreferencesPlanningPreferencesPatch>[0]["body"];
    void patchPreferencesPlanningPreferencesPatch({ client: apiClient, body: patch, headers: csrfHeaders() }).then((result) => {
      if (!result.error) setProfileState("connected");
    });
  };

  const handleReset = (groupId: string) => {
    const values = defaultValues.get(groupId);
    if (values) {
      setGroups((current) => updateGroup(current, groupId, values, "saved", "default", "Just now"));
    }
    const section = groupId === "travel-style" ? "rhythm" : groupId === "rewards-objective" ? "optimization" : "constraints";
    void patchPreferencesPlanningPreferencesPatch({ client: apiClient, body: { [section]: null } as Parameters<typeof patchPreferencesPlanningPreferencesPatch>[0]["body"], headers: csrfHeaders() });
  };

  const handleRemove = (groupId: string) => {
    setGroups((current) => current.filter((group) => group.id !== groupId));
    const section = groupId === "travel-style" ? "rhythm" : groupId === "rewards-objective" ? "optimization" : "constraints";
    void removePreferencesPlanningPreferencesSectionDelete({ client: apiClient, path: { section }, headers: csrfHeaders() });
  };

  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1180px] bg-surface px-[62px] py-12 shadow-3 max-[650px]:px-[22px] max-[650px]:py-8">
        <nav aria-label="Breadcrumb" className="mb-7 text-[11px] font-mono uppercase tracking-[.08em] text-text-muted">
          <Link href="/" className="underline decoration-border underline-offset-4 hover:text-text">TripPlanner</Link>
          <span className="mx-2" aria-hidden="true">/</span>
          <span aria-current="page">Your preferences</span>
        </nav>
          {profileState === "offline" ? <p className="mb-5 border border-warning bg-accent-2 px-4 py-3 text-sm text-text-muted" role="status">Sign in to persist profile changes. You can still preview the preference controls.</p> : null}
          <ProfilePreferences
          groups={groups}
          onSave={handleSave}
          onReset={handleReset}
          onRemove={handleRemove}
        />
      </main>
    </div>
  );
}
