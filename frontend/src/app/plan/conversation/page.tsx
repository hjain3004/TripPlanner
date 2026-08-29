"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SiteHeader } from "@/components/product/site-header";
import { Input } from "@/components/ui/input";
import {
  InterviewPanel,
  ReviewTripBrief,
  type AnswerValue,
  type ControlDefinition,
  type InterviewQuestion,
  type TripBriefPresentation,
} from "@/components/product/conversational";
import {
  amendSessionPlanningSessionsSessionIdAmendPost,
  answerSessionPlanningSessionsSessionIdAnswersPost,
  approveProfileUpdatePlanningSessionsSessionIdProfileUpdatesProposalIdApprovePost,
  confirmSessionPlanningSessionsSessionIdConfirmPost,
  createSessionPlanningSessionsPost,
  readSessionPlanningSessionsSessionIdGet,
  sessionJobPlanningSessionsSessionIdJobGet,
  type AnswerRequest,
  type SessionOut,
} from "@/lib/api";
import { apiClient, csrfHeaders } from "@/lib/api/client-config";

type TripEssentialsDraft = {
  origin: string;
  destination: string;
  start_date: string;
  end_date: string;
  travelers: number;
};

const emptyEssentials: TripEssentialsDraft = {
  origin: "",
  destination: "",
  start_date: "",
  end_date: "",
  travelers: 1,
};

function options(values: Array<[string, string]>): { value: string; label: string }[] {
  return values.map(([value, label]) => ({ value, label }));
}

function controlFor(kind: string, allowDelegate: boolean): ControlDefinition {
  if (kind === "trip_essentials") return { kind: "text", placeholder: "Origin, destination and dates" };
  if (kind === "purpose_party") return { kind: "single-select", options: options([["leisure", "Leisure"], ["work", "Work"], ["celebration", "Celebration"], ["family", "Family"], ["mixed", "A mix"]]), allowNoPreference: allowDelegate };
  if (kind === "budget_objective") return { kind: "single-select", options: options([["lowest_cash", "Lowest cash"], ["highest_value", "Best value"], ["convenience", "Convenience"], ["balanced", "Balanced"]]), allowNoPreference: allowDelegate };
  if (kind === "flight") return { kind: "single-select", options: options([["economy", "Economy"], ["premium_economy", "Premium economy"], ["business", "Business"], ["first", "First"]]), allowNoPreference: allowDelegate };
  if (kind === "stay") return { kind: "single-select", options: options([["location", "Location first"], ["price", "Price first"], ["balanced", "Balanced"], ["no_preference", "No preference"]]), allowNoPreference: allowDelegate };
  if (kind === "rhythm") return { kind: "single-select", options: options([["relaxed", "Relaxed"], ["moderate", "Moderate"], ["packed", "Packed"], ["no_preference", "No preference"]]), allowNoPreference: allowDelegate };
  if (kind === "experiences_food") return { kind: "single-select", options: options([["iconic", "Iconic highlights"], ["balanced", "A considered mix"], ["local", "Local and hidden"], ["no_preference", "No preference"]]), allowNoPreference: allowDelegate };
  if (kind === "hard_constraints") return { kind: "single-select", options: options([["none", "None"], ["accessibility", "Accessibility needs"], ["dietary", "Dietary needs"], ["fixed_event", "A fixed event"]]) };
  return { kind: "text", placeholder: "Anything useful for this trip?", maxLength: 1000 };
}

function displayQuestion(session: SessionOut): InterviewQuestion | null {
  const question = session.current_question;
  if (!question) return null;
  return {
    id: question.id,
    title: question.prompt,
    description: question.required ? "A required part of your trip brief." : "Optional — skip it and let TripPlanner choose.",
    step: session.progress.completed + 1,
    totalSteps: session.progress.maximum_total,
    required: question.required,
    canSkip: question.allow_delegate,
    control: controlFor(question.answer_kind, question.allow_delegate),
    tripOnly: question.phase === "core" && question.id !== "budget_and_objective",
  };
}

function payloadFor(kind: string, value: AnswerValue, essentials: TripEssentialsDraft): Record<string, unknown> {
  const text = typeof value === "string" ? value : "";
  if (kind === "trip_essentials") return essentials;
  if (kind === "purpose_party") return { purpose: text || "leisure", adults: Math.max(1, essentials.travelers), children_ages: [] };
  if (kind === "budget_objective") return { budget_minor: null, currency: "INR", travel_style: "balanced", objective: text || "balanced", points_priority: "best_value" };
  if (kind === "flight") return { cabin: text || "no_preference", max_stops: null, schedule: "no_preference", checked_baggage: null, airport_flexible: null, seat: "no_preference" };
  if (kind === "stay") return { lodging_styles: [], neighborhood_priorities: [], room_count: 1, room_needs: [], location_price_tradeoff: text || "no_preference" };
  if (kind === "rhythm") return { pace: text || "no_preference", day_start: "no_preference", evening_style: "no_preference", downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: "no_preference" };
  if (kind === "experiences_food") return { interests: text && text !== "no_preference" ? [text] : [], food_interests: [], iconic_local_balance: text || "no_preference", nightlife: null, shopping: null };
  if (kind === "hard_constraints") return text === "none" ? { has_constraints: false, dietary: [], accessibility: [], exclusions: [], immovable_events: [] } : { has_constraints: true, dietary: text === "dietary" ? ["Tell us more during review"] : [], accessibility: text === "accessibility" ? ["Tell us more during review"] : [], exclusions: [], immovable_events: text === "fixed_event" ? ["Tell us more during review"] : [] };
  return { detail: text };
}

function briefPresentation(session: SessionOut): TripBriefPresentation {
  const brief = session.brief;
  if (!brief) return { sections: [], unresolvedRequirements: ["Complete the interview first."] };
  const questionForSection: Record<string, string> = { budget_and_objective: "budget_and_objective", flight_preferences: "flight_preferences", stay_preferences: "stay_preferences", daily_rhythm: "daily_rhythm", experiences_and_food: "experiences_and_food", hard_constraints: "hard_constraints" };
  const sections = Object.entries(brief).filter(([key, value]) => value && ["trip_essentials", "purpose_and_party", "budget_and_objective", "flight_preferences", "stay_preferences", "daily_rhythm", "experiences_and_food", "hard_constraints"].includes(key)).map(([key, value]) => ({
    id: key,
    title: key.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()),
    items: Object.entries(value as Record<string, unknown>).map(([label, item]) => ({ id: `${key}-${label}`, label: label.replaceAll("_", " "), value: Array.isArray(item) ? item.join(", ") || "None" : String(item ?? "Not specified"), source: session.answers[questionForSection[key] as keyof typeof session.answers]?.delegated ? "delegated" as const : brief.applied_profile_sections?.includes(key.replace("_preferences", "")) ? "profile" as const : "trip" as const })),
  }));
  return {
    title: "Your trip brief",
    sections,
    assumptions: brief.assumptions ?? [],
    pendingProfileChanges: session.pending_profile_updates.map((proposal) => ({
      id: proposal.proposal_id,
      label: `${proposal.section} preference`,
      value: "Suggested from this trip",
      reason: "Save only if you want this to become a future default.",
    })),
  };
}

export default function ConversationalPlanPage() {
  const [session, setSession] = useState<SessionOut | null>(null);
  const [value, setValue] = useState<AnswerValue>(null);
  const [essentials, setEssentials] = useState<TripEssentialsDraft>(emptyEssentials);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [jobStatus, setJobStatus] = useState<string>("");
  const [amendQuestionId, setAmendQuestionId] = useState<string | null>(null);

  const load = useCallback(async (id?: string) => {
    const result = id
      ? await readSessionPlanningSessionsSessionIdGet({ client: apiClient, path: { session_id: id } })
      : await createSessionPlanningSessionsPost({ client: apiClient, headers: csrfHeaders() });
    if (result.error || !result.data) throw new Error("Please sign in before starting a trip consultation.");
    setSession(result.data);
    if (!id && typeof window !== "undefined") window.history.replaceState(null, "", `/plan/conversation?session=${result.data.id}`);
    setValue(null);
  }, []);

  useEffect(() => {
    let active = true;
    const resumeId = typeof window === "undefined" ? undefined : new URLSearchParams(window.location.search).get("session") ?? undefined;
    void Promise.resolve().then(() => load(resumeId)).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not start the consultation.");
    });
    return () => { active = false; };
  }, [load]);

  const question = useMemo(() => (session ? displayQuestion(session) : null), [session]);
  const inReview = session?.status === "reviewing" || session?.status === "confirmed" || session?.status === "planning";

  useEffect(() => {
    if (session?.status !== "planning" || !session.planning_job_id) return;
    let active = true;
    const poll = async () => {
      const result = await sessionJobPlanningSessionsSessionIdJobGet({ client: apiClient, path: { session_id: session.id } });
      if (!active || !result.data) return;
      setJobStatus(String((result.data as { status?: string }).status ?? "queued"));
      if (String((result.data as { status?: string }).status) !== "complete") window.setTimeout(() => void poll(), 1500);
    };
    void Promise.resolve().then(() => poll());
    return () => { active = false; };
  }, [session]);

  const submit = async (delegated = false) => {
    if (!session || !question) return;
    setBusy(true); setError("");
    const chooseForMe = value === "no_preference" || (Array.isArray(value) && value.includes("no_preference"));
    const isDelegated = delegated || chooseForMe;
    const body: AnswerRequest = {
      question_id: question.id as AnswerRequest["question_id"],
      expected_version: session.version,
      delegated: isDelegated,
      client_event_id: crypto.randomUUID(),
      ...(isDelegated ? { payload: null } : { payload: payloadFor(session.current_question?.answer_kind ?? "adaptive_detail", value, essentials) as AnswerRequest["payload"] }),
    };
    const result = await answerSessionPlanningSessionsSessionIdAnswersPost({ client: apiClient, path: { session_id: session.id }, body, headers: csrfHeaders() });
    if (result.error || !result.data) setError("That answer could not be saved. Refresh and try again."); else { setSession(result.data); setValue(null); }
    setBusy(false);
  };

  const confirm = async () => {
    if (!session?.brief) return;
    setBusy(true); setError("");
    const result = await confirmSessionPlanningSessionsSessionIdConfirmPost({ client: apiClient, path: { session_id: session.id }, body: { expected_version: session.version, brief: session.brief, client_event_id: crypto.randomUUID() }, headers: csrfHeaders() });
    if (result.error || !result.data) setError("Confirmation could not be completed. Your brief is still safe."); else setSession(result.data);
    setBusy(false);
  };

  const approveProfileChange = async (proposalId: string) => {
    if (!session) return;
    setBusy(true);
    const result = await approveProfileUpdatePlanningSessionsSessionIdProfileUpdatesProposalIdApprovePost({ client: apiClient, path: { session_id: session.id, proposal_id: proposalId }, body: { expected_version: session.version }, headers: csrfHeaders() });
    if (result.error || !result.data) setError("That profile change could not be saved."); else setSession(result.data);
    setBusy(false);
  };

  const amend = async () => {
    if (!session || !amendQuestionId) return;
    const answer = session.answers[amendQuestionId as keyof typeof session.answers];
    if (!answer) return;
    setBusy(true); setError("");
    const result = await amendSessionPlanningSessionsSessionIdAmendPost({ client: apiClient, path: { session_id: session.id }, body: { question_id: amendQuestionId as AnswerRequest["question_id"], expected_version: session.version, payload: payloadFor(answer.question_id, value, essentials) as AnswerRequest["payload"], client_event_id: crypto.randomUUID() }, headers: csrfHeaders() });
    if (result.error || !result.data) setError("That amendment could not be saved."); else { setSession(result.data); setAmendQuestionId(null); setValue(null); }
    setBusy(false);
  };

  const beginAmend = (sectionId: string) => {
    const questionId = sectionId;
    if (!session?.answers[questionId as keyof typeof session.answers]) { setError("This section is not editable in the current brief."); return; }
    setAmendQuestionId(questionId);
    setError("");
  };

  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <SiteHeader />
      <main className="mx-auto w-full max-w-[1180px] bg-surface px-6 py-10 shadow-3 sm:px-12 lg:px-[62px]">
        <div className="mb-8 flex items-center justify-between gap-4 border-b border-border pb-5">
          <div><Link href="/" className="font-mono text-[10px] uppercase tracking-[.1em] text-text-muted underline">TripPlanner</Link><p className="mt-2 font-mono text-[10px] uppercase tracking-[.1em] text-accent-4">A trip brief, one decision at a time</p></div>
          <Link href="/profile" className="min-h-[44px] border-b border-primary px-2 py-3 text-sm text-primary">View profile</Link>
        </div>
        {error ? <p className="mb-6 border-2 border-warning bg-accent-2 px-4 py-3 text-sm" role="alert">{error}</p> : null}
        {inReview && session ? session.status === "planning" ? <section className="mx-auto max-w-3xl space-y-6 py-12" aria-live="polite"><p className="font-mono text-[11px] uppercase tracking-[.14em] text-accent-4">Planning in progress</p><h1 className="font-display text-h1 text-primary">Your confirmed brief is on its way.</h1><p className="text-sm leading-6 text-text-muted">The existing planner is working from the brief you approved. Current status: <strong className="text-text">{jobStatus || "queued"}</strong>.</p><Link href={`/plan?job_id=${session.planning_job_id ?? ""}`} className="inline-flex min-h-[48px] items-center border-2 border-border bg-primary px-5 font-semibold text-text-on-primary shadow-1">Open plan workspace →</Link></section> : amendQuestionId ? <InterviewPanel question={{ id: amendQuestionId, title: "Update this choice", description: "Your trip remains in review until you confirm the amended brief.", step: 1, totalSteps: 1, required: true, control: controlFor(session.answers[amendQuestionId as keyof typeof session.answers]?.question_id ?? "adaptive_detail", true) }} value={value} onChange={setValue} onContinue={() => void amend()} onBack={() => setAmendQuestionId(null)} onReview={() => undefined} canGoBack canContinue={!busy && value !== null && value !== ""} isSubmitting={busy} error={error} /> : <ReviewTripBrief brief={briefPresentation(session)} isReady={session.status === "reviewing"} readinessMessage="Review every assumption, then confirm when you are ready." onAmend={beginAmend} onApproveProfileChange={approveProfileChange} onConfirm={confirm} confirming={busy} error={error} /> : session && question ? (
          question.id === "trip_essentials" ? (
            <section className="mx-auto w-full max-w-3xl space-y-7" aria-labelledby="essentials-heading">
              <div><p className="font-mono text-[11px] uppercase tracking-[.14em] text-accent-4">Trip essentials · required</p><h1 id="essentials-heading" className="mt-3 font-display text-h1 leading-[1.05] text-primary">{question.title}</h1><p className="mt-3 text-sm leading-6 text-text-muted">We’ll ask the important questions first, before any search begins.</p></div>
              <div className="grid gap-4 rounded-lg border-2 border-border bg-surface p-6 shadow-2 sm:grid-cols-2">
                {(["origin", "destination", "start_date", "end_date"] as const).map((field) => <label key={field} className="grid gap-2 text-xs font-medium uppercase tracking-[.08em] text-text-muted">{field.replace("_", " ")}<Input className="min-h-[48px] text-base normal-case tracking-normal" type={field.includes("date") ? "date" : "text"} value={essentials[field]} onChange={(event) => setEssentials((current) => ({ ...current, [field]: event.target.value.toUpperCase() }))} /></label>)}
                <label className="grid gap-2 text-xs font-medium uppercase tracking-[.08em] text-text-muted">Travelers<Input className="min-h-[48px] text-base normal-case tracking-normal" type="number" min={1} max={20} value={essentials.travelers} onChange={(event) => setEssentials((current) => ({ ...current, travelers: Number(event.target.value) || 1 }))} /></label>
              </div>
              <div className="flex justify-end"><button type="button" className="min-h-[48px] border-2 border-border bg-primary px-6 font-semibold text-text-on-primary shadow-1 disabled:cursor-not-allowed disabled:opacity-50" disabled={busy || !essentials.origin || !essentials.destination || !essentials.start_date || !essentials.end_date} onClick={() => void submit(false)}>Continue →</button></div>
            </section>
          ) : (
            <InterviewPanel question={question} value={value} onChange={setValue} onContinue={() => void submit(false)} onSkip={question.canSkip ? () => void submit(true) : undefined} onReview={() => setError("Finish the required questions before review.")} canContinue={!busy && value !== null && value !== ""} isSubmitting={busy} error={error} announcement={session.assistance_status === "degraded" ? "Tailored follow-up assistance is unavailable; you can still continue." : undefined} />
          )
        ) : <p className="py-20 text-center text-text-muted">Loading your consultation…</p>}
      </main>
    </div>
  );
}
