"use client";

import { useEffect, useRef } from "react";
import { ArrowLeft, ArrowRight, ClipboardList } from "lucide-react";
import { Button } from "@/components/ui/button";
import { progressLabel, type AnswerValue, type InterviewQuestion } from "./conversational-types";
import { QuestionProgress } from "./question-progress";
import { TypedAnswerControl } from "./typed-answer-control";

interface InterviewPanelProps {
  question: InterviewQuestion;
  value?: AnswerValue;
  onChange: (value: AnswerValue) => void;
  onContinue: () => void;
  onBack?: () => void;
  onSkip?: () => void;
  onReview: () => void;
  canContinue?: boolean;
  canGoBack?: boolean;
  isSubmitting?: boolean;
  error?: string;
  announcement?: string;
}

export function InterviewPanel({
  question,
  value = question.answer?.value ?? null,
  onChange,
  onContinue,
  onBack,
  onSkip,
  onReview,
  canContinue = false,
  canGoBack = Boolean(onBack),
  isSubmitting = false,
  error,
  announcement,
}: InterviewPanelProps) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  const headingId = `question-heading-${question.id}`;
  const descriptionId = `question-description-${question.id}`;

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [question.id]);

  return (
    <section className="mx-auto w-full max-w-3xl space-y-7" aria-labelledby={headingId}>
      <div className="space-y-5">
        <QuestionProgress current={question.step} total={question.totalSteps} context="A trip brief, one decision at a time" />
        <div className="flex items-center justify-between gap-4 font-mono text-[10px] uppercase tracking-[0.13em] text-text-muted">
          <span>Travel consultation</span>
          <span>{progressLabel(question.step, question.totalSteps)}</span>
        </div>
      </div>

      <div className="relative overflow-hidden rounded-lg border-2 border-border bg-surface shadow-2">
        <div className="h-2 bg-primary" aria-hidden="true" />
        <div className="space-y-7 p-6 sm:p-9">
          <div className="space-y-3">
            {question.eyebrow ? <p className="font-mono text-[11px] uppercase tracking-[0.14em] text-accent-4">{question.eyebrow}</p> : null}
            <h1 ref={headingRef} id={headingId} tabIndex={-1} className="font-display text-h2 leading-[1.08] tracking-[-0.02em] text-primary outline-none">
              {question.title}
            </h1>
            {question.description ? <p id={descriptionId} className="max-w-2xl text-sm leading-6 text-text-muted">{question.description}</p> : null}
          </div>

          {question.profileDerived ? (
            <div className="flex items-start gap-3 border-l-4 border-accent-3 bg-accent-2 px-4 py-3 text-sm text-text" data-testid="profile-derived-note">
              <span className="mt-0.5 font-mono text-[10px] uppercase tracking-[0.08em] text-primary">Profile</span>
              <p>{question.profileDerived}</p>
            </div>
          ) : null}
          {question.tripOnly ? (
            <p className="font-mono text-[10px] uppercase tracking-[0.08em] text-text-muted">This choice applies to this trip only</p>
          ) : null}

          <TypedAnswerControl
            control={question.control}
            value={value}
            onChange={onChange}
            disabled={isSubmitting}
            label={question.title}
            describedBy={question.description ? descriptionId : undefined}
          />

          <div className="min-h-6" aria-live="polite" aria-atomic="true">
            {announcement ? <p className="text-xs text-text-muted">{announcement}</p> : null}
            {error ? <p className="text-sm font-medium text-danger" role="alert">{error}</p> : null}
          </div>
        </div>

        <div className="flex flex-col gap-3 border-t-2 border-border bg-accent-2/60 p-5 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-2">
            <Button type="button" variant="ghost" size="lg" className="min-h-[44px]" onClick={onBack} disabled={!canGoBack || isSubmitting} aria-label="Go back to the previous question">
              <ArrowLeft aria-hidden="true" /> Back
            </Button>
            {question.canSkip && onSkip ? (
              <Button type="button" variant="ghost" size="lg" className="min-h-[44px]" onClick={onSkip} disabled={isSubmitting}>
                No preference
              </Button>
            ) : null}
          </div>
          <div className="flex flex-wrap gap-2 sm:justify-end">
            <Button type="button" variant="outline" size="lg" className="min-h-[44px]" onClick={onReview} disabled={isSubmitting}>
              <ClipboardList aria-hidden="true" /> Review answers
            </Button>
            <Button type="button" size="lg" className="min-h-[44px]" onClick={onContinue} disabled={!canContinue || isSubmitting}>
              {isSubmitting ? "Saving…" : question.step === question.totalSteps ? "Review trip brief" : "Continue"}
              {!isSubmitting ? <ArrowRight aria-hidden="true" /> : null}
            </Button>
          </div>
        </div>
      </div>
      <p className="text-center font-mono text-[10px] uppercase tracking-[0.1em] text-text-faint">Your answers stay in your account so you can resume on another device</p>
    </section>
  );
}
