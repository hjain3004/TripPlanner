"use client";

import { PreferenceGroupCard } from "./preference-group-card";
import type { ProfilePreferenceGroup, ProfilePreferencesHandlers } from "./types";

interface ProfilePreferencesProps extends ProfilePreferencesHandlers {
  groups: readonly ProfilePreferenceGroup[];
  heading?: string;
  description?: string;
}

export function ProfilePreferences({
  groups,
  heading = "Your travel memory",
  description = "Keep the choices that matter to you close. TripPlanner uses these saved preferences as defaults, and always shows when a trip answer is only for this journey.",
  onSave,
  onReset,
  onRemove,
}: ProfilePreferencesProps) {
  return (
    <section aria-labelledby="profile-preferences-heading" className="bg-surface">
      <div className="border-b border-border pb-6">
        <span className="flex items-center gap-2 text-[10px] font-mono font-medium uppercase tracking-[.1em] text-text-muted">
          <span className="h-0.5 w-7 bg-accent-4" aria-hidden="true" />
          Account / preferences
        </span>
        <h1
          id="profile-preferences-heading"
          className="mt-5 font-display text-h2 leading-[1.05] tracking-[-0.015em] text-primary"
        >
          {heading}
        </h1>
        <p className="mt-4 max-w-[650px] text-[15px] leading-[1.65] text-text-muted">{description}</p>
      </div>

      {groups.length > 0 ? (
        <div>
          {groups.map((group) => (
            <PreferenceGroupCard
              key={group.id}
              group={group}
              onSave={onSave}
              onReset={onReset}
              onRemove={onRemove}
            />
          ))}
        </div>
      ) : (
        <div className="border-b border-border py-12 text-center">
          <h3 className="text-h3 font-ui font-semibold text-primary">No saved preferences yet</h3>
          <p className="mx-auto mt-2 max-w-md text-sm leading-[1.6] text-text-muted">
            Answer a few questions during your next trip and you can save the choices that should follow you.
          </p>
        </div>
      )}

      <div className="mt-6 flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-5 text-[11px] leading-[1.5] text-text-muted">
        <span>
          <b className="font-medium text-text">Saved preference</b> is a profile default.
        </span>
        <span>
          <b className="font-medium text-text">This trip only</b> never changes your profile.
        </span>
        <span>Wallet, cards and points remain in your separate account projection.</span>
      </div>
    </section>
  );
}

export type { PreferenceDraft, ProfilePreferenceGroup, ProfilePreferencesHandlers } from "./types";
