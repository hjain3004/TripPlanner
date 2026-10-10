"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { SiteHeader } from "@/components/product/site-header";
import { ProfilePreferences } from "@/components/product/profile";
import type { PreferenceDraft, ProfilePreferenceGroup } from "@/components/product/profile";
import { emptyPreferencePatch, projectTravelPreferences, buildPreferencePatch } from "@/components/product/profile/profile-projection";
import {
  getPreferencesPlanningPreferencesGet,
  patchPreferencesPlanningPreferencesPatch,
  removePreferencesPlanningPreferencesSectionDelete,
  type TravelPreferenceProfile,
} from "@/lib/api";
import { apiClient, csrfHeaders } from "@/lib/api/client-config";

type LoadState = "loading" | "ready" | "error";
export default function ProfilePage() {
  const [groups, setGroups] = useState<readonly ProfilePreferenceGroup[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [error, setError] = useState("");

  const applyProfile = useCallback((profile: TravelPreferenceProfile) => {
    setGroups(projectTravelPreferences(profile));
    setLoadState("ready");
    setError("");
  }, []);

  const load = useCallback(async () => {
    setLoadState("loading");
    const result = await getPreferencesPlanningPreferencesGet({ client: apiClient });
    if (result.error || !result.data) throw new Error("Sign in to view your saved travel preferences.");
    applyProfile(result.data.profile);
  }, [applyProfile]);

  useEffect(() => {
    void Promise.resolve().then(load).catch((cause: unknown) => {
      setLoadState("error");
      setError(cause instanceof Error ? cause.message : "Could not load your saved preferences.");
    });
  }, [load]);

  const save = async (groupId: string, values: PreferenceDraft): Promise<boolean> => {
    setError("");
    const result = await patchPreferencesPlanningPreferencesPatch({ client: apiClient, body: buildPreferencePatch(groupId, values, new Date().toISOString()), headers: csrfHeaders() });
    if (result.error || !result.data) {
      setError("We couldn’t save that group. Your draft is still open; try again.");
      return false;
    }
    applyProfile(result.data.profile);
    return true;
  };

  const resetGroup = async (groupId: string): Promise<boolean> => {
    setError("");
    const result = await patchPreferencesPlanningPreferencesPatch({
      client: apiClient,
      body: emptyPreferencePatch(groupId),
      headers: csrfHeaders(),
    });
    if (result.error || !result.data) {
      setError("We couldn’t update that preference group. Nothing was changed.");
      return false;
    }
    applyProfile(result.data.profile);
    return true;
  };

  const removeGroup = async (groupId: string): Promise<boolean> => {
    setError("");
    const result = await removePreferencesPlanningPreferencesSectionDelete({
      client: apiClient,
      path: { section: groupId as "flight" | "stay" | "rhythm" | "experiences" | "constraints" | "optimization" },
      headers: csrfHeaders(),
    });
    if (result.error || !result.data) {
      setError("We couldn’t update that preference group. Nothing was changed.");
      return false;
    }
    applyProfile(result.data.profile);
    return true;
  };

  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <SiteHeader />
      <div className="mx-auto w-full max-w-[1180px] bg-surface px-[62px] py-12 shadow-3 max-[650px]:px-[22px] max-[650px]:py-8">
        <nav aria-label="Breadcrumb" className="mb-7 text-[11px] font-mono uppercase tracking-[.08em] text-text-muted">
          <Link href="/" className="underline decoration-border underline-offset-4 hover:text-text">TripPlanner</Link>
          <span className="mx-2" aria-hidden="true">/</span>
          <span aria-current="page">Your preferences</span>
        </nav>
        {loadState === "loading" ? <p className="py-16 text-center text-text-muted" role="status">Loading your saved preferences…</p> : null}
        {loadState === "error" ? <div className="border-2 border-warning bg-accent-2 px-5 py-4" role="alert"><p>{error}</p><button type="button" className="mt-4 min-h-11 border-2 border-border bg-surface px-4 font-medium" onClick={() => void load().catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load your saved preferences."))}>Try again</button></div> : null}
        {loadState === "ready" ? <>
          {error ? <p className="mb-5 border border-warning bg-accent-2 px-4 py-3 text-sm text-text-muted" role="alert">{error}</p> : null}
          <ProfilePreferences groups={groups} onSave={save} onReset={resetGroup} onRemove={removeGroup} />
        </> : null}
      </div>
    </div>
  );
}
