"use client";

import { Check, ChevronRight, CircleAlert, Pencil, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { answerSourceLabel, type AnswerSource, type PendingProfileChange, type TripBriefPresentation } from "./conversational-types";

interface ReviewTripBriefProps {
  brief: TripBriefPresentation;
  isReady: boolean;
  readinessMessage?: string;
  onAmend: (sectionId: string) => void;
  onApproveProfileChange?: (changeId: string) => void;
  onConfirm: () => void;
  confirming?: boolean;
  error?: string;
}

function SourceTag({ source, delegated }: { source: AnswerSource; delegated?: boolean }) {
  const label = answerSourceLabel(source, delegated);
  const tone = source === "profile" ? "border-accent-3 text-text" : source === "delegated" || delegated ? "border-primary text-primary" : "border-border text-text-muted";
  return <span className={`inline-flex min-h-[28px] items-center rounded-full border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.05em] ${tone}`}>{label}</span>;
}

function ProfileChangeRow({ change, onApprove }: { change: PendingProfileChange; onApprove?: () => void }) {
  return (
    <li className="flex flex-col gap-3 border-b border-border py-4 last:border-b-0 sm:flex-row sm:items-start sm:justify-between">
      <div>
        <p className="font-medium text-text">{change.label}</p>
        <p className="mt-1 text-sm text-text-muted">{change.value}</p>
        {change.reason ? <p className="mt-1 text-xs text-text-muted">{change.reason}</p> : null}
      </div>
      {change.approved ? (
        <span className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] text-success-text"><Check aria-hidden="true" className="h-4 w-4" /> Approved</span>
      ) : onApprove ? (
        <Button type="button" variant="outline" size="sm" className="min-h-[44px]" onClick={onApprove}>Save to profile</Button>
      ) : (
        <span className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-muted">Review before saving</span>
      )}
    </li>
  );
}

export function ReviewTripBrief({
  brief,
  isReady,
  readinessMessage,
  onAmend,
  onApproveProfileChange,
  onConfirm,
  confirming = false,
  error,
}: ReviewTripBriefProps) {
  const unresolved = brief.unresolvedRequirements ?? [];
  const profileChanges = brief.pendingProfileChanges ?? [];

  return (
    <section className="mx-auto w-full max-w-4xl space-y-8" aria-labelledby="trip-brief-heading">
      <header className="space-y-3">
        <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent-4">Your trip brief</p>
        <h1 id="trip-brief-heading" className="font-display text-h1 leading-[1.04] tracking-[-0.025em] text-primary">{brief.title ?? "A clear brief for a better trip"}</h1>
        <p className="max-w-2xl text-sm leading-6 text-text-muted">{brief.subtitle ?? "Check the details, amend anything that feels off, then confirm when you’re ready."}</p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[1fr_18rem] lg:items-start">
        <div className="space-y-5">
          {brief.sections.map((section) => (
            <article key={section.id} className="overflow-hidden rounded-lg border-2 border-border bg-surface shadow-1">
              <div className="flex items-start justify-between gap-4 border-b border-border bg-accent-2/60 px-5 py-4">
                <div>
                  <h2 className="font-ui text-lg font-semibold text-primary">{section.title}</h2>
                  {section.description ? <p className="mt-1 text-xs leading-5 text-text-muted">{section.description}</p> : null}
                </div>
                {section.amendable !== false ? (
                  <Button type="button" variant="ghost" size="sm" className="min-h-[44px]" onClick={() => onAmend(section.id)} aria-label={`Amend ${section.title}`}>
                    <Pencil aria-hidden="true" /> Amend
                  </Button>
                ) : null}
              </div>
              <dl className="divide-y divide-border px-5">
                {section.items.map((item) => (
                  <div key={item.id} className="grid gap-2 py-4 sm:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] sm:items-start">
                    <dt className="text-xs font-medium uppercase tracking-[0.06em] text-text-muted">{item.label}</dt>
                    <dd className="space-y-2 text-sm text-text">
                      <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{item.value}</span><SourceTag source={item.source} delegated={item.source === "delegated"} /></div>
                      {item.detail ? <p className="text-xs leading-5 text-text-muted">{item.detail}</p> : null}
                    </dd>
                  </div>
                ))}
              </dl>
            </article>
          ))}

          {profileChanges.length > 0 ? (
            <article className="rounded-lg border-2 border-accent-3 bg-surface px-5 py-4" data-testid="pending-profile-changes">
              <div className="flex items-start gap-3">
                <ShieldCheck aria-hidden="true" className="mt-0.5 h-5 w-5 shrink-0 text-accent-3" />
                <div>
                  <h2 className="font-semibold text-text">Save these as profile defaults?</h2>
                  <p className="mt-1 text-sm leading-5 text-text-muted">Nothing changes in your saved profile until you approve it.</p>
                </div>
              </div>
              <ul className="mt-3"><>{profileChanges.map((change) => <ProfileChangeRow key={change.id} change={change} onApprove={onApproveProfileChange ? () => onApproveProfileChange(change.id) : undefined} />)}</></ul>
            </article>
          ) : null}

          {brief.assumptions && brief.assumptions.length > 0 ? (
            <article className="rounded-lg border border-border bg-accent-2/40 px-5 py-4">
              <h2 className="font-mono text-[11px] uppercase tracking-[0.1em] text-text-muted">Assumptions</h2>
              <ul className="mt-3 space-y-2 text-sm leading-5 text-text-muted">{brief.assumptions.map((assumption) => <li key={assumption} className="flex gap-2"><ChevronRight aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-accent-4" />{assumption}</li>)}</ul>
            </article>
          ) : null}
        </div>

        <aside className="rounded-lg border-2 border-border bg-surface p-5 shadow-2 lg:sticky lg:top-6" aria-label="Trip brief confirmation">
          <div className="flex items-start gap-3">
            {isReady ? <Check aria-hidden="true" className="h-5 w-5 shrink-0 text-success-text" /> : <CircleAlert aria-hidden="true" className="h-5 w-5 shrink-0 text-warning-text" />}
            <div>
              <h2 className="font-semibold text-text">{isReady ? "Ready to build" : "One more detail needed"}</h2>
              <p className="mt-1 text-sm leading-5 text-text-muted">{readinessMessage ?? (isReady ? "This is the last review before planning starts." : "Complete the required answers before planning can start.")}</p>
            </div>
          </div>
          {unresolved.length > 0 ? <ul className="mt-4 space-y-2 border-t border-border pt-4 text-xs text-text-muted">{unresolved.map((item) => <li key={item}>• {item}</li>)}</ul> : null}
          {error ? <p className="mt-4 border-t border-border pt-4 text-sm text-danger" role="alert">{error}</p> : null}
          <Button type="button" size="lg" className="mt-5 min-h-[48px] w-full" disabled={!isReady || confirming} onClick={onConfirm}>
            {confirming ? "Confirming…" : "Build my trip"}
          </Button>
          <p className="mt-3 text-center font-mono text-[10px] uppercase tracking-[0.07em] text-text-faint">Planning starts only after confirmation</p>
        </aside>
      </div>
    </section>
  );
}
