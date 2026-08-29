"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  getPreferenceSourceLabel,
  getPreferenceStatusLabel,
} from "./profile-policy";
import { PreferenceConfirmationDialog } from "./preference-confirmation-dialog";
import type {
  PreferenceDraft,
  ProfilePreferenceField,
  ProfilePreferenceGroup,
  PreferenceValue,
} from "./types";

interface PreferenceGroupCardProps {
  group: ProfilePreferenceGroup;
  onSave: (groupId: string, values: PreferenceDraft) => void;
  onReset: (groupId: string) => void;
  onRemove: (groupId: string) => void;
}

const statusClasses: Record<ProfilePreferenceGroup["updateStatus"], string> = {
  saved: "bg-success/15 text-success-text",
  pending: "bg-warning/20 text-warning-text",
  "needs-review": "bg-accent-2 text-text",
};

function initialDraft(group: ProfilePreferenceGroup): PreferenceDraft {
  return Object.fromEntries(group.fields.map((field) => [field.id, field.value]));
}

function displayValue(field: ProfilePreferenceField): string {
  if (typeof field.value === "number") return field.value.toLocaleString();
  return field.value;
}

function FieldValue({ field }: { field: ProfilePreferenceField }) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-[.08em] text-text-muted">
        {field.label}
      </dt>
      <dd className="mt-1 text-[15px] leading-[1.45] text-text">
        {displayValue(field)}
      </dd>
      {field.description && (
        <dd className="mt-1 text-[12px] leading-[1.5] text-text-muted">
          {field.description}
        </dd>
      )}
    </div>
  );
}

function EditableField({
  field,
  value,
  onChange,
}: {
  field: ProfilePreferenceField;
  value: PreferenceValue;
  onChange: (value: string | number) => void;
}) {
  const inputId = `preference-${field.id}`;
  const descriptionId = field.description ? `${inputId}-description` : undefined;
  const commonProps = {
    id: inputId,
    name: field.id,
    "aria-describedby": descriptionId,
  };

  return (
    <div className="grid gap-2">
      <Label htmlFor={inputId} className="text-[12px] text-text">
        {field.label}
      </Label>
      {field.type === "select" ? (
        <select
          {...commonProps}
          value={String(value)}
          onChange={(event) => onChange(event.target.value)}
          className="min-h-11 w-full rounded-md border-2 border-border bg-bg px-3 text-sm text-text outline-none transition-colors focus-visible:border-primary focus-visible:ring-3 focus-visible:ring-primary/50"
        >
          {(field.options ?? []).map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      ) : (
        <Input
          {...commonProps}
          type={field.type}
          value={value}
          onChange={(event) =>
            onChange(field.type === "number" ? Number(event.target.value) : event.target.value)
          }
          className="min-h-11"
        />
      )}
      {field.description && (
        <p id={descriptionId} className="text-[12px] leading-[1.5] text-text-muted">
          {field.description}
        </p>
      )}
    </div>
  );
}

export function PreferenceGroupCard({
  group,
  onSave,
  onReset,
  onRemove,
}: PreferenceGroupCardProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<PreferenceDraft>(() => initialDraft(group));
  const [confirmation, setConfirmation] = useState<"reset" | "remove" | null>(null);

  const startEditing = () => {
    setDraft(initialDraft(group));
    setEditing(true);
  };

  const cancelEditing = () => {
    setDraft(initialDraft(group));
    setEditing(false);
  };

  const confirmAction = () => {
    if (confirmation === "reset") onReset(group.id);
    if (confirmation === "remove") onRemove(group.id);
    setConfirmation(null);
    setEditing(false);
  };

  return (
    <article
      aria-labelledby={`${group.id}-title`}
      className="border-b border-border py-7 first:border-t first:border-border"
    >
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(280px,1.15fr)_auto] lg:items-start">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`${group.id}-title`} className="text-h3 font-ui font-semibold leading-[1.15] text-primary">
              {group.title}
            </h3>
            <span
              className="rounded-full border border-border px-2 py-1 text-[11px] font-medium text-text"
              aria-label={`Source: ${getPreferenceSourceLabel(group.source)}`}
            >
              {getPreferenceSourceLabel(group.source)}
            </span>
          </div>
          <p className="mt-2 max-w-[330px] text-[13px] leading-[1.55] text-text-muted">
            {group.description}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] font-mono text-text-muted">
            <span
              className={cn("rounded-full px-2 py-1", statusClasses[group.updateStatus])}
              aria-label={`Update status: ${getPreferenceStatusLabel(group.updateStatus)}`}
            >
              {getPreferenceStatusLabel(group.updateStatus)}
            </span>
            {group.updatedAt && <span>Updated {group.updatedAt}</span>}
          </div>
        </div>

        {editing ? (
          <div className="grid gap-4 rounded-md border border-border bg-accent-2/35 p-4 sm:grid-cols-2">
            {group.fields.map((field) => (
              <EditableField
                key={field.id}
                field={field}
                value={draft[field.id] ?? ""}
                onChange={(value) => setDraft((current) => ({ ...current, [field.id]: value }))}
              />
            ))}
          </div>
        ) : (
          <dl className="grid gap-5 sm:grid-cols-2">
            {group.fields.map((field) => (
              <FieldValue key={field.id} field={field} />
            ))}
          </dl>
        )}

        <div className="flex flex-wrap gap-2 lg:justify-end">
          {editing ? (
            <>
              <Button type="button" variant="outline" className="min-h-11" onClick={cancelEditing}>
                Cancel
              </Button>
              <Button
                type="button"
                className="min-h-11"
                onClick={() => {
                  onSave(group.id, draft);
                  setEditing(false);
                }}
              >
                Save changes
              </Button>
            </>
          ) : (
            <Button type="button" variant="outline" className="min-h-11" onClick={startEditing}>
              Edit group
            </Button>
          )}
          {!editing && (
            <Button
              type="button"
              variant="ghost"
              className="min-h-11"
              aria-label={`Reset ${group.title}`}
              onClick={() => setConfirmation("reset")}
            >
              Reset
            </Button>
          )}
          {!editing && group.canRemove !== false && (
            <Button
              type="button"
              variant="ghost"
              className="min-h-11"
              aria-label={`Remove ${group.title}`}
              onClick={() => setConfirmation("remove")}
            >
              Remove
            </Button>
          )}
        </div>
      </div>
      <PreferenceConfirmationDialog
        action={confirmation}
        groupTitle={group.title}
        onCancel={() => setConfirmation(null)}
        onConfirm={confirmAction}
      />
    </article>
  );
}
