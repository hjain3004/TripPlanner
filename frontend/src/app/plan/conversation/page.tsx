"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { interpretSessionPlanningSessionsSessionIdInterpretPost } from "@/lib/api/generated/sdk.gen";
import { payloadForValue, supportsInterpretation, valueFromPayload } from "@/components/product/conversational/answer-payload";
import { AssistanceStatus, ContradictionReview, InterpretationControl } from "@/components/product/conversational/interview-assistance";
import { apiClient, csrfHeaders } from "@/lib/api/client-config";

type Structured = Record<string, unknown>;
function hasPendingAssistance(session: SessionOut | null | undefined): boolean {
  return session?.status === "awaiting_assistant" || session?.assistance_pending === true;
}
function valueForAnswer(session: SessionOut, questionId: string): AnswerValue {
  const answer = session.answers[questionId as keyof typeof session.answers];
  if (!answer || answer.delegated || !answer.payload) return answer?.delegated ? "no_preference" : null;
  const definition = (session.question_catalog ?? []).find((item) => item.id === questionId);
  return definition ? valueFromPayload(definition, answer.payload) : null;
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
  const [draftPayload, setDraftPayload] = useState<AnswerRequest["payload"]>(null);
  const mutationInFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [jobStatus, setJobStatus] = useState("");
  const [amendId, setAmendId] = useState<string | null>(null);
  const [assistancePollError, setAssistancePollError] = useState(false);
  const [resumeAttempt, setResumeAttempt] = useState(0);

  const hydrate = useCallback((next: SessionOut, answerId?: string) => {
    setSession(next);
    const id = answerId ?? next.current_question?.id;
    setValue(id ? valueForAnswer(next, id) : null);
    setDraftPayload(id ? next.answers[id as keyof typeof next.answers]?.payload ?? null : null);
  }, []);
  const load = useCallback(async (id?: string, answerId?: string) => {
    const result = id ? await readSessionPlanningSessionsSessionIdGet({ client: apiClient, path: { session_id: id } }) : await createSessionPlanningSessionsPost({ client: apiClient, headers: csrfHeaders() });
    if (result.error || !result.data) throw new Error("Sign in to start your trip consultation.");
    hydrate(result.data, answerId);
    if (!id && typeof window !== "undefined") window.history.replaceState(null, "", `/plan/conversation?session=${result.data.id}`);
  }, [hydrate]);
  useEffect(() => { void Promise.resolve().then(() => load(typeof window === "undefined" ? undefined : new URLSearchParams(window.location.search).get("session") ?? undefined)).catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Could not load the consultation.")); }, [load]);
  const question = useMemo(() => session ? questionView(session, value) : null, [session, value]);
  const awaitingAssistance = hasPendingAssistance(session);
  const assistanceSessionId = session?.id;
  useEffect(() => {
    if (!assistanceSessionId || !awaitingAssistance) return;
    let active = true;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const result = await readSessionPlanningSessionsSessionIdGet({ client: apiClient, path: { session_id: assistanceSessionId } });
        if (!active) return;
        if (result.error || !result.data) throw new Error("resume");
        setAssistancePollError(false);
        // Only hydrate once assistance finishes, so repeated reads do not
        // overwrite any locally edited controls or remount a live region.
        if (!hasPendingAssistance(result.data)) {
          hydrate(result.data, amendId ?? undefined);
          return;
        }
      } catch {
        if (active) setAssistancePollError(true);
      }
      if (active) timer = window.setTimeout(() => void poll(), 1500);
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [assistanceSessionId, awaitingAssistance, hydrate, resumeAttempt, amendId]);
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
  }, [session, load]);
  // A synchronous guard covers double clicks before React has rendered busy.
  const mutate = async (action: () => Promise<void>, failureMessage: string) => {
    if (mutationInFlight.current || awaitingAssistance) return;
    mutationInFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await action();
    } catch {
      setError(failureMessage);
    } finally {
      mutationInFlight.current = false;
      setBusy(false);
    }
  };

  const submit = async (delegated = false) => {
    if (!session || !question) return;
    await mutate(async () => {
      const delegate = delegated || (value === "no_preference" && !draftPayload);
      const body: AnswerRequest = {
        question_id: question.id as AnswerRequest["question_id"],
        expected_version: session.version,
        delegated: delegate,
        payload: delegate ? null : payloadForValue(question.id, value, draftPayload),
        client_event_id: crypto.randomUUID(),
      };
      const result = await answerSessionPlanningSessionsSessionIdAnswersPost({ client: apiClient, path: { session_id: session.id }, body, headers: csrfHeaders() });
      if (result.error || !result.data) throw new Error("answer");
      hydrate(result.data);
    }, "That answer could not be saved. Reload the consultation and try again.");
  };
  const goBack = async () => {
    if (!session) return;
    await mutate(async () => {
      const result = await backSessionPlanningSessionsSessionIdBackPost({ client: apiClient, path: { session_id: session.id }, body: { expected_version: session.version, client_event_id: crypto.randomUUID() }, headers: csrfHeaders() });
      if (result.error || !result.data) throw new Error("back");
      hydrate(result.data);
    }, "We could not go back. Reload to use the latest session.");
  };
  const openAmendment = (id: string) => {
    if (!session || busy || awaitingAssistance) return;
    setError("");
    setAmendId(id);
    setValue(valueForAnswer(session, id));
    setDraftPayload(session.answers[id as keyof typeof session.answers]?.payload ?? null);
  };
  const amend = async () => {
    if (!session || !amendId) return;
    await mutate(async () => {
      const delegated = value === "no_preference" && !draftPayload;
      const result = await amendSessionPlanningSessionsSessionIdAmendPost({
        client: apiClient, path: { session_id: session.id },
        body: { question_id: amendId as AnswerRequest["question_id"], expected_version: session.version, delegated, payload: delegated ? null : payloadForValue(amendId, value, draftPayload), client_event_id: crypto.randomUUID() },
        headers: csrfHeaders(),
      });
      if (result.error || !result.data) throw new Error("amend");
      setAmendId(null);
      hydrate(result.data);
    }, "That change could not be saved. Your brief is unchanged.");
  };
  const confirm = async () => {
    if (!session?.brief || (session.contradictions ?? []).length > 0) return;
    const brief = session.brief;
    await mutate(async () => {
      const result = await confirmSessionPlanningSessionsSessionIdConfirmPost({ client: apiClient, path: { session_id: session.id }, body: { expected_version: session.version, brief, client_event_id: crypto.randomUUID() }, headers: csrfHeaders() });
      if (result.error || !result.data) {
        try { await load(session.id); } catch { /* retain the confirmation error */ }
        throw new Error("confirm");
      }
      hydrate(result.data);
    }, "Confirmation could not be completed. Your brief is still safe; retry when the session reloads.");
  };
  const approve = async (proposalId: string) => {
    if (!session) return;
    await mutate(async () => {
      const result = await approveProfileUpdatePlanningSessionsSessionIdProfileUpdatesProposalIdApprovePost({ client: apiClient, path: { session_id: session.id, proposal_id: proposalId }, body: { expected_version: session.version }, headers: csrfHeaders() });
      if (result.error || !result.data) throw new Error("approve");
      hydrate(result.data);
    }, "That profile suggestion could not be saved.");
  };
  const interpret = async (text: string, questionId: string) => {
    if (!session) return;
    await mutate(async () => {
      const result = await interpretSessionPlanningSessionsSessionIdInterpretPost({
        client: apiClient, path: { session_id: session.id },
        body: { question_id: questionId as AnswerRequest["question_id"], expected_version: session.version, text, client_event_id: crypto.randomUUID() },
        headers: csrfHeaders(),
      });
      if (result.error || !result.data) {
        // The server may have reserved a call before interruption. Read its
        // persisted diagnostics/budget before allowing another request.
        try { await load(session.id, amendId ?? undefined); } catch { /* keep typed controls available */ }
        throw new Error("interpret");
      }
      if ((amendId && result.data.status === "reviewing") || result.data.current_question?.id === questionId) {
        // A proposal changes session metadata, not the user's typed draft.
        setSession(result.data);
      } else {
        hydrate(result.data, amendId ?? undefined);
      }
    }, "Interpretation could not be completed. Use the answer controls, or reload to check your session.");
  };
  const useCandidate = () => {
    const pending = session?.pending_answer;
    const definition = amendId ? session?.question_catalog?.find((item) => item.id === amendId) : session?.current_question;
    if (!definition || pending?.question_id !== definition.id || busy || awaitingAssistance) return;
    setDraftPayload(pending.payload);
    setValue(valueFromPayload(definition, pending.payload));
  };

  const changeValue = (next: AnswerValue) => {
    if (awaitingAssistance) return;
    setValue(next);
    if (next === "no_preference") setDraftPayload(null);
  };

  const inReview = session?.status === "reviewing" || session?.status === "planning" || session?.status === "failed";
  const hasContradictions = Boolean(session?.contradictions?.length);
  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <SiteHeader />
      <div className="mx-auto w-full max-w-[1180px] bg-surface px-[62px] py-12 shadow-3 max-[650px]:px-[22px] max-[650px]:py-8">
        <nav aria-label="Breadcrumb" className="mb-7 text-[11px] font-mono uppercase tracking-[.08em] text-text-muted">
          <Link href="/" className="underline">TripPlanner</Link><span className="mx-2" aria-hidden="true">/</span><span>Plan a trip</span>
        </nav>
        {error ? <p role="alert" className="mb-5 border-2 border-warning bg-accent-2 px-4 py-3">{error}</p> : null}
        {session ? <AssistanceStatus session={session} pending={awaitingAssistance} /> : null}
        {awaitingAssistance ? <section className="mx-auto mb-6 max-w-3xl space-y-3 border-2 border-border bg-accent-2 p-5" aria-label="Assistance in progress">
          <p role="status" className="text-sm text-text">Your interview assistance is in progress. This consultation will resume automatically when it finishes.</p>
          {assistancePollError ? <div className="space-y-3"><p role="alert" className="text-sm text-text">We could not check assistance progress. Your saved answers are safe; we will keep trying.</p><button type="button" className="min-h-[44px] rounded-md border-2 border-border px-4 py-2 font-semibold text-text" onClick={() => setResumeAttempt((attempt) => attempt + 1)}>Check progress again</button></div> : null}
        </section> : null}
        {session && !amendId ? <ContradictionReview session={session} busy={busy || awaitingAssistance} onAmend={openAmendment} /> : null}
        {session?.status === "reviewing" && session.pending_answer && !amendId ? <section className="mx-auto mb-6 max-w-3xl space-y-3 border-2 border-border bg-accent-2 p-5" aria-label="Pending answer suggestion">
          <p className="text-sm text-text">A suggested answer is waiting for your review. It has not changed your trip brief.</p>
          <button type="button" className="min-h-[44px] rounded-md border-2 border-border px-4 py-2 font-semibold text-text" disabled={busy || awaitingAssistance} onClick={() => openAmendment(session.pending_answer!.question_id)}>Review suggested answer</button>
        </section> : null}
        {session && amendId && amendQuestion ? (
          <InterviewPanel question={amendQuestion} value={value} onChange={changeValue} onContinue={() => void amend()} continueLabel="Save answer" onBack={() => { setAmendId(null); hydrate(session); }} canGoBack onReview={() => { setAmendId(null); hydrate(session); }} canContinue={value !== null && value !== ""} isSubmitting={busy} actionsDisabled={awaitingAssistance} controlsDisabled={awaitingAssistance} assistance={supportsInterpretation(amendQuestion.id) ? <InterpretationControl key={amendQuestion.id} session={session} questionId={amendQuestion.id} busy={busy || awaitingAssistance} onInterpret={(text) => void interpret(text, amendQuestion.id)} onUseCandidate={useCandidate} /> : undefined} />
        ) : session && inReview && !amendId ? (
          session.status === "planning" ? (
            <section className="mx-auto max-w-3xl space-y-5 py-12">
              <p className="font-mono text-[11px] uppercase tracking-[.14em] text-accent-4">Planning in progress</p>
              <h1 className="font-display text-h2 text-primary">Your confirmed brief is on its way.</h1>
              <p className="text-sm text-text-muted">Current status: <strong>{jobStatus || "queued"}</strong>.</p>
              <Link href={`/plan?session=${session.id}`} className="inline-flex min-h-12 items-center border-2 border-border bg-primary px-5 font-semibold text-text-on-primary">Open plan workspace →</Link>
            </section>
          ) : (
            <ReviewTripBrief brief={presentation(session)} actionsDisabled={awaitingAssistance} isReady={!awaitingAssistance && !hasContradictions && (session.status === "reviewing" || session.status === "failed")} readinessMessage={awaitingAssistance ? "Interview assistance is in progress. Your saved brief will be available when it finishes." : hasContradictions ? "Review and save an affected answer to resolve conflicting preferences before confirmation." : session.status === "failed" ? (session.planning_error ?? "Planning did not start. Review and retry confirmation.") : "Review every assumption, then confirm when you are ready."} onAmend={openAmendment} onApproveProfileChange={(id) => void approve(id)} onConfirm={() => void confirm()} confirming={busy} />
          )
        ) : session && question ? (
          <InterviewPanel question={question} value={value} onChange={changeValue} onContinue={() => void submit()} onBack={() => void goBack()} canGoBack={session.progress.completed > 0} onSkip={question.canSkip ? () => void submit(true) : undefined} onReview={() => setError("Finish the required questions before review.")} canContinue={!busy && value !== null && value !== ""} isSubmitting={busy} actionsDisabled={awaitingAssistance} controlsDisabled={awaitingAssistance} assistance={supportsInterpretation(question.id) ? <InterpretationControl key={question.id} session={session} questionId={question.id} busy={busy || awaitingAssistance} onInterpret={(text) => void interpret(text, question.id)} onUseCandidate={useCandidate} /> : undefined} />
        ) : awaitingAssistance ? null : <p className="py-20 text-center text-text-muted">Loading your consultation…</p>}
      </div>
    </div>
  );
}
