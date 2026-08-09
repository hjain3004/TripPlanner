"use client";

import type { DraftItinerary } from "@/lib/api/types.gen";
import { TrustChip } from "./trust-chip";

interface ItineraryTimelineProps {
  itinerary: DraftItinerary;
}

export function ItineraryTimeline({ itinerary }: ItineraryTimelineProps) {
  return (
    <div className="relative">
      {itinerary.itinerary_quality === "fallback" && (
        <div className="mb-4">
          <TrustChip variant="warning" label="Best-effort itinerary — review before booking" />
        </div>
      )}
      <div className="relative">
        <div className="absolute left-3.5 top-2 bottom-2 w-0.5 bg-border" />
        <div className="space-y-6">
          {itinerary.days.map((day, i) => (
            <div key={i} className="relative pl-10">
              <div className="absolute left-0 top-1.5 w-7 h-7 rounded-full bg-surface border border-border flex items-center justify-center">
                <span className="text-xs font-mono tabular-nums text-text-muted">{i + 1}</span>
              </div>
              <div className="text-xs text-text-muted font-mono mb-1">{day.date}</div>
              {day.items && day.items.length > 0 ? (
                <div className="space-y-1.5">
                  {day.items.map((item, j) => (
                    <div key={j} className="flex items-center gap-2 text-sm">
                      <span className="text-text">{item.poi_id}</span>
                      {item.start_hint && (
                        <span className="text-xs text-text-muted">({item.start_hint})</span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-text-muted italic">Free / unscheduled</p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
