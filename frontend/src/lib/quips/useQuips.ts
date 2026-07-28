"use client";

import { useState, useEffect, useMemo } from "react";
import type { Quip, QuipPack, PipelineStage } from "./types";

function seededShuffle(arr: Quip[], seed: string): Quip[] {
  const copy = [...arr];
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    const c = seed.charCodeAt(i);
    hash = ((hash << 5) - hash) + c;
    hash = hash & hash;
  }
  const s = Math.abs(hash) || 1;
  for (let i = copy.length - 1; i > 0; i--) {
    const si = s * (i + 1) * 9301 + 49297;
    const j = si % (i + 1);
    const tmp = copy[i] as Quip;
    copy[i] = copy[j] as Quip;
    copy[j] = tmp;
  }
  return copy;
}

function loadPack(destination: string): Promise<QuipPack | null> {
  return import(`@/content/quips/${destination}.json`)
    .then((m) => m.default as QuipPack)
    .catch(() => import(`@/content/quips/_generic.json`)
      .then((m) => m.default as QuipPack)
      .catch(() => null)
    );
}

const STAGE_CATEGORIES: Record<PipelineStage, string> = {
  intake: "intake",
  itinerary: "itinerary",
  costing: "costing",
  optimizing: "optimizing",
  transfer: "transfer",
  critic: "critic",
  explaining: "explaining",
};

function selectQuips(pack: QuipPack | null, stage: PipelineStage | null, jobId: string): Quip[] {
  if (!pack) return [];

  const approved = pack.quips.filter((q) => q.approved);
  const stageCat = stage ? STAGE_CATEGORIES[stage] : null;
  let candidates = stageCat
    ? approved.filter((q) => q.categories.includes(stageCat) || q.categories.includes("generic"))
    : approved.filter((q) => q.categories.includes("generic"));

  if (candidates.length === 0) {
    candidates = approved.filter((q) => q.categories.includes("generic"));
  }
  if (candidates.length === 0) {
    candidates = approved;
  }

  const seeded = seededShuffle(candidates, jobId);
  return seeded.slice(0, 5);
}

export function useQuips(destination: string, stage: PipelineStage | null, jobId: string): { quips: Quip[]; isLoading: boolean } {
  const [pack, setPack] = useState<QuipPack | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    loadPack(destination).then((p) => {
      if (!cancelled) {
        setPack(p);
        setIsLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [destination]);

  const quips = useMemo(
    () => selectQuips(pack, stage, jobId),
    [pack, stage, jobId]
  );

  return { quips, isLoading };
}
