"use client";

import { useState } from "react";
import type { SessionOut } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { answerTitle, interpretationLimit } from "./answer-payload";

interface InterpretationProps {
  session: SessionOut;
  questionId: string;
  busy: boolean;
  onInterpret: (text: string) => void;
  onUseCandidate: () => void;
}

export function InterpretationControl({ session, questionId, busy, onInterpret, onUseCandidate }: InterpretationProps) {
  const [text, setText] = useState("");
  const [dismissed, setDismissed] = useState<string | null>(null);
  const [used, setUsed] = useState(false);
  const proposalKey = `${session.version}:${questionId}`;
  const candidate = session.pending_answer?.question_id === questionId && dismissed !== proposalKey ? session.pending_answer : null;
  const limit = interpretationLimit(session.interview_llm_calls ?? 0, session.answers);
  return <section className="space-y-4 border-t border-border pt-5" aria-label="Preference interpretation">
    <div className="space-y-2">
      <label htmlFor={`interpret-${questionId}`} className="block text-sm font-semibold text-text">Describe your preference</label>
      <p id={`interpret-help-${questionId}`} className="text-sm leading-6 text-text-muted">Optional: put your preference into words. Review the suggestion before saving. Use the answer controls for dates, quantities, budgets, and financial facts.</p>
      <Textarea id={`interpret-${questionId}`} value={text} onChange={(event) => setText(event.target.value)} disabled={busy || Boolean(limit)} maxLength={1000} aria-describedby={`interpret-help-${questionId} interpret-limit-${questionId}`} className="min-h-[112px] bg-surface text-base" />
      <p id={`interpret-limit-${questionId}`} className="text-sm text-text-muted">{limit ?? "Interview assistance is limited to two calls, including a required trip review."}</p>
      <Button type="button" variant="outline" className="min-h-[44px]" disabled={busy || Boolean(limit) || !text.trim()} onClick={() => { setUsed(false); onInterpret(text.trim()); }}>Interpret preference</Button>
    </div>
    {candidate ? <section aria-label="Suggested answer" className="space-y-3 rounded-lg border-2 border-border bg-accent-2 p-4">
      <h2 className="font-semibold text-primary">Suggested answer</h2>
      <p className="text-sm text-text-muted">This suggestion has not been saved. Check every field before using it.</p>
      <dl className="space-y-2 text-sm">{Object.entries(candidate.payload).map(([field, item]) => <div key={field} className="grid min-w-0 gap-1 sm:grid-cols-2"><dt className="text-text-muted">{field.replaceAll("_", " ")}</dt><dd className="break-words text-text">{Array.isArray(item) ? item.join(", ") || "None" : item === null ? "Not specified" : typeof item === "boolean" ? item ? "Yes" : "No" : String(item)}</dd></div>)}</dl>
      <div className="flex flex-wrap gap-2">
        <Button type="button" className="min-h-[44px]" disabled={busy} onClick={() => { onUseCandidate(); setUsed(true); }}>Use suggested answer</Button>
        <Button type="button" variant="outline" className="min-h-[44px]" disabled={busy} onClick={() => { setDismissed(proposalKey); setUsed(false); }}>Dismiss suggestion</Button>
      </div>
      <p role="status" className="text-sm text-text-muted">{used ? "Suggestion copied to your answer controls. Continue to save, or edit your answer first." : "You can also choose a different answer using the controls above."}</p>
    </section> : null}
  </section>;
}

const DIAGNOSTIC_COPY: Record<string, string> = {
  unavailable: "Tailored assistance was unavailable.",
  invalid_response: "The assistance response could not be validated.",
  budget_exhausted: "The interview assistance limit was reached.",
  interrupted: "An assistance request was interrupted.",
};

export function AssistanceStatus({ session, pending = false }: { session: SessionOut; pending?: boolean }) {
  const diagnostics = Array.from(new Set(session.assistance_diagnostics ?? []));
  const acknowledgements = session.events.filter((event) => event.kind === "assistant_acknowledgement");
  return <div className="mx-auto mb-6 max-w-3xl space-y-4">
    {!pending && (session.assistance_status === "degraded" || diagnostics.length > 0) ? <div role="status" className="space-y-2 border-2 border-warning bg-accent-2 p-4 text-sm text-text">
      <p className="font-semibold">Assistance is limited. Your answer controls are still available.</p>
      <p>Tailored follow-ups may be unavailable; you can continue with the standard questions.</p>
      {diagnostics.map((diagnostic) => <p key={diagnostic}>{DIAGNOSTIC_COPY[diagnostic]}</p>)}
    </div> : null}
    {acknowledgements.length > 0 ? <section aria-label="Consultation acknowledgements" aria-live="polite" aria-relevant="additions" className="space-y-3 border-l-4 border-primary pl-4 text-sm leading-6 text-text">{acknowledgements.map((event) => <p key={event.id}>{event.text}</p>)}</section> : null}
  </div>;
}

export function ContradictionReview({ session, busy, onAmend }: { session: SessionOut; busy: boolean; onAmend: (id: string) => void }) {
  if (!session.contradictions?.length) return null;
  const canAmend = session.status === "reviewing";
  return <section aria-labelledby="contradictions-heading" className="mx-auto mb-6 max-w-3xl space-y-4 border-2 border-warning bg-accent-2 p-5">
    <h2 id="contradictions-heading" className="font-semibold text-text">Review conflicting answers before building your trip</h2>
    <p className="text-sm text-text-muted">Open an affected answer, check it, and save it explicitly. This reviews your trip answer; profile changes require their own approval.</p>
    {!canAmend ? <p className="text-sm text-text-muted">Finish the remaining questions to amend these answers in your trip review.</p> : null}
    {session.contradictions.map((contradiction, index) => <div key={index} className="space-y-3">
      <p className="break-words text-sm text-text">{contradiction.clarification}</p>
      <div className="flex flex-wrap gap-2">{contradiction.answer_ids.map((id) => <Button key={id} type="button" variant="outline" className="min-h-[44px]" disabled={busy || !canAmend || !session.answers[id] || !session.question_catalog?.some((question) => question.id === id)} onClick={() => onAmend(id)}>Review {answerTitle(id)}</Button>)}</div>
    </div>)}
  </section>;
}
