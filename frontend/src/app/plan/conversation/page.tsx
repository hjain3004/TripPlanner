"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { SiteHeader } from "@/components/product/site-header";
import {
  InterviewPanel,
  ReviewTripBrief,
  controlFromServer,
  type AnswerValue,
  type InterviewQuestion,
  type TripBriefPresentation,
} from "@/components/product/conversational";
import {
  amendSessionPlanningSessionsSessionIdAmendPost,
  answerSessionPlanningSessionsSessionIdAnswersPost,
  approveProfileUpdatePlanningSessionsSessionIdProfileUpdatesProposalIdApprovePost,
  backSessionPlanningSessionsSessionIdBackPost,
  confirmSessionPlanningSessionsSessionIdConfirmPost,
  createSessionPlanningSessionsPost,
  readSessionPlanningSessionsSessionIdGet,
  sessionJobPlanningSessionsSessionIdJobGet,
  type AnswerRequest,
  type SessionOut,
} from "@/lib/api";
import { apiClient, csrfHeaders } from "@/lib/api/client-config";

type Structured = Record<string, unknown>;
function valueForAnswer(session: SessionOut, questionId: string): AnswerValue {
  const answer = session.answers[questionId as keyof typeof session.answers];
  if (!answer || answer.delegated || !answer.payload) return answer?.delegated ? "no_preference" : null;
  const payload = answer.payload as unknown as Structured;
  const definition = (session.question_catalog ?? []).find((item) => item.id === questionId);
  if (!definition) return null;
  const control = controlFromServer(definition.control, Number(payload.adults ?? 1));
  if (control.kind === "trip-essentials" || control.kind === "party" || control.kind === "hard-constraints") return payload as AnswerValue;
  if (control.kind === "single-select") {
    const key = definition.answer_kind === "budget_objective" ? "objective" : definition.answer_kind === "flight" ? "cabin" : definition.answer_kind === "stay" ? "location_price_tradeoff" : definition.answer_kind === "rhythm" ? "pace" : "iconic_local_balance";
    return typeof payload[key] === "string" ? payload[key] as string : null;
  }
  if (control.kind === "text") return typeof payload.detail === "string" ? payload.detail : null;
  return null;
}

function toPayload(questionId: string, value: AnswerValue): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null && !Array.isArray(value)) return value;
  const text = typeof value === "string" ? value : "";
  switch (questionId) {
    case "purpose_and_party": return { purpose: text || "leisure", adults: 1, children_ages: [] };
    case "budget_and_objective": return { budget_minor: null, currency: "INR", travel_style: "balanced", objective: text || "balanced", points_priority: "best_value" };
    case "flight_preferences": return { cabin: text || "no_preference", max_stops: null, schedule: "no_preference", checked_baggage: null, airport_flexible: null, seat: "no_preference" };
    case "stay_preferences": return { lodging_styles: [], neighborhood_priorities: [], room_count: 1, room_needs: [], location_price_tradeoff: text || "no_preference" };
    case "daily_rhythm": return { pace: text || "no_preference", day_start: "no_preference", evening_style: "no_preference", downtime_minutes: null, transit_tolerance_minutes: null, day_trip_appetite: "no_preference" };
    case "experiences_and_food": return { interests: text && text !== "no_preference" ? [text] : [], food_interests: [], iconic_local_balance: text || "no_preference", nightlife: null, shopping: null };
    default: return { detail: text };
  }
}

function questionView(session: SessionOut, value: AnswerValue): InterviewQuestion | null {
  const current = session.current_question;
  if (!current) return null;
  return {
    id: current.id,
    title: current.prompt,
    description: current.required ? "A required part of your trip brief." : "Optional — skip it and let TripPlanner choose.",
    step: session.progress.completed + 1,
    totalSteps: session.progress.maximum_total,
    required: current.required,
    canSkip: current.allow_delegate,
    control: controlFromServer(current.control),
    answer: { value, source: session.answers[current.id]?.delegated ? "delegated" : "trip" },
  };
}

function presentation(session: SessionOut): TripBriefPresentation {
  if (!session.brief) return { sections: [], unresolvedRequirements: ["Complete the interview first."] };
  const sectionIds = ["trip_essentials", "purpose_and_party", "budget_and_objective", "flight_preferences", "stay_preferences", "daily_rhythm", "experiences_and_food", "hard_constraints"];
  const profileSections = new Set(session.brief.applied_profile_sections ?? []);
  const sections = sectionIds.flatMap((id) => {
    const value = session.brief?.[id as keyof typeof session.brief];
    if (!value || typeof value !== "object" || Array.isArray(value)) return [];
    const answer = session.answers[id as keyof typeof session.answers];
    const source = answer?.delegated ? "delegated" : profileSections.has(id.replace("_preferences", "")) ? "profile" : "trip";
    return [{ id, title: id.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase()), items: Object.entries(value as Structured).map(([label, item]) => ({ id: `${id}-${label}`, label: label.replaceAll("_", " "), value: Array.isArray(item) ? item.join(", ") || "None" : String(item ?? "Not specified"), source: source as "trip" | "profile" | "delegated" })) }];
  });
  return {
    title: "Your trip brief",
    sections,
    assumptions: session.brief.assumptions ?? [],
    pendingProfileChanges: session.pending_profile_updates.map((proposal) => ({ id: proposal.proposal_id, label: `${proposal.section} preference`, value: "Suggested from this trip", reason: "Save only if you want this to become a future default." })),
  };
}

export default function ConversationalPlanPage() {
  const [session, setSession] = useState<SessionOut | null>(null);
  const [value, setValue] = useState<AnswerValue>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [amendId, setAmendId] = useState<string | null>(null);

  const hydrate = useCallback((next: SessionOut) => {
    setSession(next);
    setValue(next.current_question ? valueForAnswer(next, next.current_question.id) : null);
  }, []);
  const load = useCallback(async (id?: string) => {
    const result = id ? await readSessionPlanningSessionsSessionIdGet({ client: apiClient, path: { session_id: id } }) : await createSessionPlanningSessionsPost({ client: apiClient, headers: csrfHeaders() });
    if (result.error || !result.data) throw new Error("Sign in to start your trip consultation.");
    hydrate(result.data);
    if (!id && typeof window !== "undefined") window.history.replaceState(null, "", `/plan/conversation?session=${result.data.id}`);
  }, [hydrate]);
  useEffect(() => { void Promise.resolve().then(() => load(typeof window === "undefined" ? undefined : new URLSearchParams(window.location.search).get("session") ?? undefined)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load the consultation.")); }, [load]);
  const question = useMemo(() => session ? questionView(session, value) : null, [session, value]);
  const amendQuestion = useMemo(() => {
    if (!session || !amendId) return null;
    const definition = (session.question_catalog ?? []).find((item) => item.id === amendId);
    if (!definition) return null;
    return { id: definition.id, title: definition.prompt, description: "Your brief stays in review until you save this change.", step: 1, totalSteps: 1, required: definition.required, canSkip: false, control: controlFromServer(definition.control), answer: { value, source: "trip" as const } };
  }, [session, amendId, value]);
  useEffect(() => {
    if (session?.status !== "planning" || !session.planning_job_id) return;
    let active = true;
    const poll = async () => { const result = await sessionJobPlanningSessionsSessionIdJobGet({ client: apiClient, path: { session_id: session.id } }); if (!active || !result.data) return; const status = String((result.data as { status?: string }).status ?? "queued"); setJobStatus(status); if (status === "failed") { await load(session.id); return; } if (status !== "complete") window.setTimeout(() => void poll(), 1500); };
    void poll();
    return () => { active = false; };
  }, [session]);
  const submit = async (delegated = false) => {
    if (!session || !question) return;
    setBusy(true); setError("");
    const body: AnswerRequest = { question_id: question.id as AnswerRequest["question_id"], expected_version: session.version, delegated: delegated || value === "no_preference", payload: delegated || value === "no_preference" ? null : toPayload(question.id, value) as AnswerRequest["payload"], client_event_id: crypto.randomUUID() };
    const result = await answerSessionPlanningSessionsSessionIdAnswersPost({ client: apiClient, path: { session_id: session.id }, body, headers: csrfHeaders() });
    if (result.error || !result.data) { setError("That answer could not be saved. Reload the consultation and try again."); } else hydrate(result.data);
    setBusy(false);
  };
  const goBack = async () => { if (!session) return; setBusy(true); setError(""); const result = await backSessionPlanningSessionsSessionIdBackPost({ client: apiClient, path: { session_id: session.id }, body: { expected_version: session.version, client_event_id: crypto.randomUUID() }, headers: csrfHeaders() }); if (result.error || !result.data) setError("We could not go back. Reload to use the latest session."); else hydrate(result.data); setBusy(false); };
  const amend = async () => { if (!session || !amendId) return; setBusy(true); const result = await amendSessionPlanningSessionsSessionIdAmendPost({ client: apiClient, path: { session_id: session.id }, body: { question_id: amendId as AnswerRequest["question_id"], expected_version: session.version, payload: toPayload(amendId, value) as AnswerRequest["payload"], client_event_id: crypto.randomUUID() }, headers: csrfHeaders() }); if (result.error || !result.data) setError("That change could not be saved. Your brief is unchanged."); else { setAmendId(null); hydrate(result.data); } setBusy(false); };
  const confirm = async () => { if (!session?.brief) return; setBusy(true); const result = await confirmSessionPlanningSessionsSessionIdConfirmPost({ client: apiClient, path: { session_id: session.id }, body: { expected_version: session.version, brief: session.brief, client_event_id: crypto.randomUUID() }, headers: csrfHeaders() }); if (result.error || !result.data) { setError("Confirmation could not be completed. Your brief is still safe; retry when the session reloads."); try { await load(session.id); } catch { /* keep the original error visible */ } } else hydrate(result.data); setBusy(false); };
  const approve = async (proposalId: string) => { if (!session) return; setBusy(true); const result = await approveProfileUpdatePlanningSessionsSessionIdProfileUpdatesProposalIdApprovePost({ client: apiClient, path: { session_id: session.id, proposal_id: proposalId }, body: { expected_version: session.version }, headers: csrfHeaders() }); if (result.error || !result.data) setError("That profile suggestion could not be saved."); else hydrate(result.data); setBusy(false); };

  const inReview = session?.status === "reviewing" || session?.status === "planning" || session?.status === "failed";
  return <div className="min-h-screen bg-bg font-ui text-text"><SiteHeader /><main className="mx-auto w-full max-w-[1180px] bg-surface px-[62px] py-12 shadow-3 max-[650px]:px-[22px] max-[650px]:py-8"><nav aria-label="Breadcrumb" className="mb-7 text-[11px] font-mono uppercase tracking-[.08em] text-text-muted"><Link href="/" className="underline">TripPlanner</Link><span className="mx-2" aria-hidden="true">/</span><span>Plan a trip</span></nav>{error ? <p role="alert" className="mb-5 border-2 border-warning bg-accent-2 px-4 py-3">{error}</p> : null}{session && amendId && amendQuestion ? <InterviewPanel question={amendQuestion} value={value} onChange={setValue} onContinue={() => void amend()} onBack={() => setAmendId(null)} canGoBack onReview={() => undefined} canContinue={value !== null && value !== ""} isSubmitting={busy} error={error} /> : session && inReview && !amendId ? <>{session.status === "planning" ? <section className="mx-auto max-w-3xl space-y-5 py-12"><p className="font-mono text-[11px] uppercase tracking-[.14em] text-accent-4">Planning in progress</p><h1 className="font-display text-h2 text-primary">Your confirmed brief is on its way.</h1><p className="text-sm text-text-muted">Current status: <strong>{jobStatus || "queued"}</strong>.</p><Link href={`/plan?job_id=${session.planning_job_id ?? ""}`} className="inline-flex min-h-12 items-center border-2 border-border bg-primary px-5 font-semibold text-text-on-primary">Open plan workspace →</Link></section> : <ReviewTripBrief brief={presentation(session)} isReady={session.status === "reviewing" || session.status === "failed"} readinessMessage={session.status === "failed" ? (session.planning_error ?? "Planning did not start. Review and retry confirmation.") : "Review every assumption, then confirm when you are ready."} onAmend={(id) => { setAmendId(id); setValue(valueForAnswer(session, id)); }} onApproveProfileChange={(id) => void approve(id)} onConfirm={() => void confirm()} confirming={busy} error={error} />}</> : session && question ? <InterviewPanel question={question} value={value} onChange={setValue} onContinue={() => void submit()} onBack={() => void goBack()} canGoBack={session.progress.completed > 0} onSkip={question.canSkip ? () => void submit(true) : undefined} onReview={() => setError("Finish the required questions before review.")} canContinue={!busy && (value !== null && value !== "")} isSubmitting={busy} error={error} /> : <p className="py-20 text-center text-text-muted">Loading your consultation…</p>}</main></div>;
}
