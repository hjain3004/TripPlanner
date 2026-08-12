"use client";

import { useRef, useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { parsePlanJobStatus } from "@/lib/api/schemas";
import { apiClient } from "@/lib/api/client-config";
import { planPlanPost, getJobStatusPlanJobIdGet } from "@/lib/api/sdk.gen";
import type { PlanJobStatus, TripIntakeRequest } from "@/lib/api/types.gen";
import { composeRawRequest, parseWallet } from "@/lib/wizard/composeRequest";
import type { WizardData } from "@/lib/wizard/types";
import { EMPTY_WIZARD } from "@/lib/wizard/types";
import { StageTracker } from "@/components/product/stage-tracker";
import { QuipRotator } from "@/components/product/quip-rotator";
import { useQuips } from "@/lib/quips/useQuips";
import { ResultsView } from "@/components/product/results-view";

type PagePhase =
  | "form"
  | "submitting"
  | "polling"
  | "complete"
  | "needs_clarification"
  | "failed"
  | "contract_error"
  | "timeout";

const STEPS = [
  { num: 1, label: "Trip basics" },
  { num: 2, label: "Wallet" },
  { num: 3, label: "Preferences" },
  { num: 4, label: "Review" },
  { num: 5, label: "Submit" },
];

const STAGE_LABELS: Record<string, string> = {
  intake: "Understanding your trip",
  itinerary: "Building your itinerary",
  costing: "Calculating costs",
  optimizing: "Optimizing rewards",
  transfer: "Checking transfers",
  critic: "Reviewing the plan",
  explaining: "Preparing your report",
};

const POLL_INTERVAL = 1500;
const TIMEOUT_MS = 120_000;

export default function PlanPage() {
  const [phase, setPhase] = useState<PagePhase>("form");
  const [currentStep, setCurrentStep] = useState(1);
  const [wizard, setWizard] = useState<WizardData>(EMPTY_WIZARD);
  const [unresolvedList, setUnresolvedList] = useState<string[]>([]);
  const [jobStatus, setJobStatus] = useState<PlanJobStatus | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const jobIdRef = useRef<string | null>(null);
  useEffect(() => { if (jobIdRef.current) setJobId(jobIdRef.current); }, []);
  const startTimeRef = useRef(0);
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const phaseRef = useRef<PagePhase>("form");

  useEffect(() => { phaseRef.current = phase; }, [phase]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [phase, currentStep]);

  useEffect(() => {
    return () => { if (pollTimerRef.current) clearTimeout(pollTimerRef.current); };
  }, []);

  const schedulePoll = () => {
    const jid = jobIdRef.current;
    if (!jid) return;
    const pollFn = async () => {
      if (!jobIdRef.current) return;
      const elapsed = Date.now() - startTimeRef.current;
      if (elapsed >= TIMEOUT_MS) {
        if (phaseRef.current === "polling") setPhase("timeout");
        return;
      }
      try {
        const { data, error } = await getJobStatusPlanJobIdGet({
          client: apiClient, path: { job_id: jobIdRef.current },
        });
        if (error) throw new Error("Poll request failed");
        const parsed = parsePlanJobStatus(data) as PlanJobStatus;
        setJobStatus(parsed);
        if (parsed.status === "complete") { setPhase("complete"); return; }
        if (parsed.status === "needs_clarification") {
          setPhase("needs_clarification");
          if (parsed.unresolved) setUnresolvedList(parsed.unresolved);
          return;
        }
        if (parsed.status === "failed") {
          setPhase("failed");
          setErrorMessage(parsed.error?.message ?? "Pipeline failed");
          return;
        }
        schedulePoll();
      } catch {
        setPhase("failed");
        setErrorMessage("Failed to check plan status");
      }
    };
    pollTimerRef.current = setTimeout(pollFn, POLL_INTERVAL);
  };

  const submitMutation = useMutation({
    mutationFn: async (body: TripIntakeRequest) => {
      const { data, error } = await planPlanPost({ client: apiClient, body });
      if (error) throw new Error("Submission failed");
      return data;
    },
    onSuccess: (data) => {
      const jid = data?.job_id;
      if (!jid) { setPhase("failed"); setErrorMessage("No job_id in response"); return; }
      jobIdRef.current = jid;
      startTimeRef.current = Date.now();
      setPhase("polling");
      schedulePoll();
    },
    onError: () => { setPhase("failed"); setErrorMessage("Failed to submit plan request"); },
  });

  const handleSubmit = () => {
    const raw = wizard.editedRawRequest ?? composeRawRequest(wizard);
    if (!raw.trim()) return;
    setPhase("submitting");
    const wallet = parseWallet(wizard);
    submitMutation.mutate({ raw_request: raw, wallet });
  };

  const handleRetry = () => {
    setPhase("form");
    setCurrentStep(unresolvedList.length > 0 ? 4 : 1);
    setJobStatus(null);
    setErrorMessage("");
    setUnresolvedList([]);
    jobIdRef.current = null;
  };

  // ── Step renderers ──────────────────────────────────────────

  const update = (patch: Partial<WizardData>) => setWizard((prev) => ({ ...prev, ...patch }));

  const stepContent = () => {
    switch (currentStep) {
      case 1: return <StepTripBasics wizard={wizard} update={update} />;
      case 2: return <StepWallet wizard={wizard} update={update} />;
      case 3: return <StepPreferences wizard={wizard} update={update} />;
      case 4: return <StepReview wizard={wizard} update={update} composeRawRequest={composeRawRequest} unresolvedList={unresolvedList} />;
      case 5: return <StepSubmit wizard={wizard} composeRawRequest={composeRawRequest} />;
    }
  };

  const canAdvance = () => {
    switch (currentStep) {
      case 1: return wizard.origin.trim().length > 0 && wizard.destination.trim().length > 0 && wizard.startDate.trim().length > 0;
      case 4: return true;
      case 5: {
        const raw = wizard.editedRawRequest ?? composeRawRequest(wizard);
        return raw.trim().length > 0;
      }
      default: return true;
    }
  };

  // ── Render ──────────────────────────────────────────────────

  if (phase === "form" || phase === "submitting") {
    return (
      <div className="min-h-screen bg-bg font-ui text-text">
        <div className="mx-auto max-w-lg px-6 py-12">
          {/* Step indicator */}
          <nav aria-label="Wizard steps" className="flex items-center gap-1 mb-8 text-xs font-medium">
            {STEPS.map((s) => (
              <span key={s.num} className="flex items-center gap-1">
                <span
                  className={`flex size-6 items-center justify-center rounded-full text-xs ${
                    s.num === currentStep
                      ? "bg-primary text-text-on-primary"
                      : s.num < currentStep
                      ? /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity compiles to direct CSS */
                        "bg-primary/20 text-text"
                      : "bg-accent-2 text-text-muted"
                  }`}
                >
                  {s.num < currentStep ? "✓" : s.num}
                </span>
                <span className={`hidden sm:inline ${s.num === currentStep ? "text-text" : "text-text"}`}>
                  {s.label}
                </span>
                {s.num < STEPS.length && <span className="w-4 h-px bg-border mx-1" />}
              </span>
            ))}
          </nav>

          <h1 ref={headingRef} tabIndex={-1} className="font-display display-hero text-h1 mb-6 outline-none">
            {stepHeading(currentStep, unresolvedList)}
          </h1>

          <div role="region" aria-label={`Step ${currentStep}`} aria-live="polite">
            {stepContent()}
          </div>

          <div className="flex items-center justify-between mt-8">
            <div>
              {currentStep > 1 && currentStep <= 5 && (
                <Button variant="outline" onClick={() => setCurrentStep((s) => s - 1)}>
                  Back
                </Button>
              )}
            </div>
            {currentStep < 5 ? (
              <Button onClick={() => setCurrentStep((s) => s + 1)} disabled={!canAdvance()}>
                Next
              </Button>
            ) : (
              <Button onClick={handleSubmit} disabled={!canAdvance() || phase === "submitting"}>
                {phase === "submitting" ? "Submitting..." : "Generate plan"}
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Post-submit states ──────────────────────────────────────

  if (phase === "polling") {
    return (
      <PollingView
        jobStatus={jobStatus}
        headingRef={headingRef}
        destination={wizard.destination || "Singapore"}
         jobId={jobId || "loading"}
      />
    );
  }

  if (phase === "complete" && jobStatus?.report) {
    return <ResultsView report={jobStatus.report} onRetry={handleRetry} />;
  }

  if (phase === "needs_clarification") {
    return (
      <div className="min-h-screen bg-bg font-ui text-text">
        <div className="mx-auto max-w-lg px-6 py-16">
          <h1 ref={headingRef} tabIndex={-1} className="font-display display-hero text-h1 mb-4 outline-none" role="alert">A few details needed</h1>
          <ul className="space-y-2 text-sm mb-8">
            {unresolvedList.map((q, i) => (
              <li key={i} className="flex items-start gap-2"><span className="text-savings-text shrink-0 mt-0.5">&rarr;</span><span>{q}</span></li>
            ))}
          </ul>
          <Button onClick={() => { setPhase("form"); setCurrentStep(4); }}>Return to review</Button>
        </div>
      </div>
    );
  }

  if (phase === "failed" || phase === "contract_error" || phase === "timeout") {
    const m = phase === "failed"
      ? { title: "Something went wrong", msg: errorMessage || "The plan could not be completed." }
      : phase === "contract_error"
      ? { title: "Version mismatch", msg: "The API response does not match the expected format. This may happen after an update." }
      : { title: "Taking longer than expected", msg: "The plan is still being generated. You can wait or try again." };
    return (
      <div className="min-h-screen bg-bg font-ui text-text">
        <div className="mx-auto max-w-lg px-6 py-16">
          <Alert>
            <h2 ref={headingRef} tabIndex={-1} className="font-medium outline-none" role="alert">{m.title}</h2>
            <p className="text-sm mt-1">{m.msg}</p>
            {phase === "contract_error" && jobStatus?.job_id && <p className="text-xs text-text-muted mt-2">Reference: {jobStatus.job_id}</p>}
            {phase === "timeout" && jobStatus?.report?.trace_id && <p className="text-xs text-text-muted mt-2">Reference: {jobStatus.report.trace_id}</p>}
          </Alert>
          <div className="mt-6 flex gap-3">
            <Button onClick={handleRetry}>Try again</Button>
            {phase === "timeout" && <Button variant="outline" onClick={schedulePoll}>Check again</Button>}
          </div>
        </div>
      </div>
    );
  }

  return null;
}

// ── Step components ───────────────────────────────────────────

function StepTripBasics({ wizard, update }: { wizard: WizardData; update: (p: Partial<WizardData>) => void }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="origin">Origin</Label>
          <Input id="origin" placeholder="e.g. DEL" value={wizard.origin} onChange={(e) => update({ origin: e.target.value })} aria-label="Origin airport code" />
        </div>
        <div>
          <Label htmlFor="destination">Destination</Label>
          <Input id="destination" placeholder="e.g. SIN" value={wizard.destination} onChange={(e) => update({ destination: e.target.value })} aria-label="Destination airport code" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="start-date">Start date</Label>
          <Input id="start-date" type="date" value={wizard.startDate} onChange={(e) => update({ startDate: e.target.value })} aria-label="Trip start date" />
        </div>
        <div>
          <Label htmlFor="end-date">End date</Label>
          <Input id="end-date" type="date" value={wizard.endDate} onChange={(e) => update({ endDate: e.target.value })} aria-label="Trip end date" />
        </div>
      </div>
      <div>
        <Label htmlFor="travelers">Travelers</Label>
        <Input id="travelers" type="number" min={1} max={9} value={String(wizard.travelers)} onChange={(e) => update({ travelers: Math.max(1, parseInt(e.target.value) || 1) })} aria-label="Number of travelers" />
      </div>
    </div>
  );
}

function StepWallet({ wizard, update }: { wizard: WizardData; update: (p: Partial<WizardData>) => void }) {
  const [cardInput, setCardInput] = useState(wizard.cardIds.join(", "));
  const [programInput, setProgramInput] = useState(
    Object.entries(wizard.pointsBalances).map(([k, v]) => `${k}:${v}`).join(", ")
  );
  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="card-ids">Your cards</Label>
        <Input id="card-ids" placeholder="e.g. hdfc-infinia, amex-platinum" value={cardInput}
          onChange={(e) => setCardInput(e.target.value)}
          onBlur={() => update({ cardIds: cardInput.split(",").map((s) => s.trim()).filter(Boolean) })}
          aria-label="Credit card IDs (comma-separated)" />
        <p className="text-xs text-text mt-1">Comma-separated card IDs. Leave empty to use demo wallet.</p>
      </div>
      <div>
        <Label htmlFor="points">Points balances</Label>
        <Input id="points" placeholder="e.g. voyager-prime:140000, star-alliance:50000" value={programInput}
          onChange={(e) => setProgramInput(e.target.value)}
          onBlur={() => {
            const balances: Record<string, number> = {};
            for (const pair of programInput.split(",").map((s) => s.trim()).filter(Boolean)) {
              const [k, v] = pair.split(":");
              if (k && v) balances[k.trim()] = parseInt(v.trim()) || 0;
            }
            update({ pointsBalances: balances });
          }}
          aria-label="Points balances (program:amount)" />
        <p className="text-xs text-text mt-1">Format: program:amount, comma-separated.</p>
      </div>
    </div>
  );
}

function StepPreferences({ wizard, update }: { wizard: WizardData; update: (p: Partial<WizardData>) => void }) {
  const [interestInput, setInterestInput] = useState(wizard.interests.join(", "));
  return (
    <div className="space-y-4">
      <div>
        <Label htmlFor="budget-style">Budget style</Label>
        <Select value={wizard.budgetStyle} onValueChange={(v: "budget" | "balanced" | "luxury") => update({ budgetStyle: v })}>
          <SelectTrigger id="budget-style" aria-label="Budget style"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="budget">Budget</SelectItem>
            <SelectItem value="balanced">Balanced</SelectItem>
            <SelectItem value="luxury">Luxury</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label htmlFor="pace">Pace</Label>
        <Select value={wizard.pace} onValueChange={(v: "relaxed" | "moderate" | "packed") => update({ pace: v })}>
          <SelectTrigger id="pace" aria-label="Trip pace"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="relaxed">Relaxed</SelectItem>
            <SelectItem value="moderate">Moderate</SelectItem>
            <SelectItem value="packed">Packed</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div>
        <Label htmlFor="interests">Interests</Label>
        <Input id="interests" placeholder="e.g. nature, food, shopping" value={interestInput}
          onChange={(e) => setInterestInput(e.target.value)}
          onBlur={() => update({ interests: interestInput.split(",").map((s) => s.trim()).filter(Boolean) })}
          aria-label="Interests (comma-separated)" />
      </div>
    </div>
  );
}

function StepReview({ wizard, update, composeRawRequest: compose, unresolvedList }: {
  wizard: WizardData; update: (p: Partial<WizardData>) => void;
  composeRawRequest: (d: WizardData) => string;
  unresolvedList: string[];
}) {
  const composed = wizard.editedRawRequest ?? compose(wizard);
  return (
    <div className="space-y-4">
      {unresolvedList.length > 0 && (
        <Alert>
          <p className="text-xs font-medium">The following details need attention:</p>
          <ul className="list-disc list-inside text-xs mt-1">
            {unresolvedList.map((q, i) => <li key={i}>{q}</li>)}
          </ul>
        </Alert>
      )}
      <div>
        <Label htmlFor="raw-preview">Request that will be sent</Label>
        <textarea
          id="raw-preview"
          /* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values (ring-primary/30, bg-primary/30, etc.) compile to direct CSS values, not class names */
          className="h-24 w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-primary/30 placeholder:text-text-muted resize-none"
          value={wizard.editedRawRequest ?? composed}
          onChange={(e) => update({ editedRawRequest: e.target.value })}
          aria-label="Request preview — edit if needed"
        />
        <p className="text-xs text-text mt-1">Edit the text directly if the auto-composed request needs adjustment.</p>
      </div>
      <div className="text-sm space-y-1">
        <h2 className="font-medium text-sm">Wallet summary</h2>
        {wizard.cardIds.length > 0 ? (
          <p className="text-text">Cards: {wizard.cardIds.join(", ")}</p>
        ) : (
          <p className="text-text">No cards specified — demo wallet will be used.</p>
        )}
        {Object.keys(wizard.pointsBalances).length > 0 && (
          <p className="text-text">Points: {Object.entries(wizard.pointsBalances).map(([k, v]) => `${k}: ${v.toLocaleString()}`).join(", ")}</p>
        )}
      </div>
    </div>
  );
}

function StepSubmit({ wizard, composeRawRequest: compose }: { wizard: WizardData; composeRawRequest: (d: WizardData) => string }) {
  const raw = wizard.editedRawRequest ?? compose(wizard);
  return (
    <div className="space-y-4 text-sm">
      <p>You are about to submit this trip plan request:</p>
      {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
      <div className="rounded-lg border border-border bg-accent-2/30 p-3">
        <p className="font-mono text-xs">{raw}</p>
        {wizard.cardIds.length > 0 && (
          <p className="text-xs text-text-muted mt-2">Wallet: {wizard.cardIds.join(", ")}</p>
        )}
      </div>
    </div>
  );
}

function stepHeading(step: number, unresolved: string[]): string {
  if (step === 1) return "Where are you going?";
  if (step === 2) return "Your cards and points";
  if (step === 3) return "Trip preferences";
  if (step === 4) return unresolved.length > 0 ? "Review & fix details" : "Review your trip";
  return "Ready to generate";
}

// ── Polling view ─────────────────────────────────────────────

function PollingView({ jobStatus, headingRef, destination, jobId }: {
  jobStatus: PlanJobStatus | null;
  headingRef: React.RefObject<HTMLHeadingElement | null>;
  destination: string;
  jobId: string;
}) {
  const stage = jobStatus?.stage ?? null;
  const stageIndex = jobStatus?.stage_index ?? null;
  const stagesTotal = jobStatus?.stages_total ?? 7;
  const indeterminate = stage === null;
  const { quips } = useQuips(destination, stage, jobId);

  return (
    <div className="min-h-screen bg-bg font-ui text-text">
      <div className="mx-auto max-w-lg px-6 py-16">
        <h1 ref={headingRef} tabIndex={-1} className="font-display display-hero text-h1 mb-8 outline-none" role="alert" aria-live="polite">
          {indeterminate ? "Working on your plan" : (stage ? STAGE_LABELS[stage] ?? stage : "Working on your plan")}
        </h1>
        <div className="mb-8">
          <StageTracker stageIndex={stageIndex} stagesTotal={stagesTotal} stage={stage} indeterminate={indeterminate} />
        </div>
        <QuipRotator quips={quips} intervalMs={6000} />
{indeterminate && (
            <div className="mt-8 flex items-center justify-center gap-1.5">
              <span className="inline-block size-1.5 rounded-full bg-primary animate-pulse" />
              {/* token-lint-disable-next-line no-hardcoded-timing no-dead-classes -- animation-delay for stagger; --dur-* tokens don't match pulse interval; arbitrary opacity values compile to direct CSS */}
              <span className="inline-block size-1.5 rounded-full bg-primary/60 animate-pulse [animation-delay:0.2s]" />
              {/* token-lint-disable-next-line no-hardcoded-timing no-dead-classes -- animation-delay for stagger; --dur-* tokens don't match pulse interval; arbitrary opacity values compile to direct CSS */}
              <span className="inline-block size-1.5 rounded-full bg-primary/30 animate-pulse [animation-delay:0.4s]" />
            </div>
          )}
      </div>
    </div>
  );
}
