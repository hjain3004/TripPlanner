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
              
              {day.unmet_needs && day.unmet_needs.length > 0 && (
                <div className="mb-2" data-testid="day-unmet">
                  <span className="text-xs font-semibold text-warning-text uppercase tracking-wider">Unmet needs</span>
                  <ul className="text-sm mt-0.5 space-y-0.5">
                    {day.unmet_needs.map((need, idx) => (
                      <li key={idx} className="text-text-muted">- {need}</li>
                    ))}
                  </ul>
                </div>
              )}
              
              {day.rejections && day.rejections.length > 0 && (
                <div className="mb-2">
                  <span className="text-xs font-semibold text-warning-text uppercase tracking-wider">Rejections</span>
                  <ul className="text-sm mt-0.5 space-y-0.5">
                    {day.rejections.map((rej, idx) => (
                      <li key={idx} className="text-text-muted">
                        - {rej.place_id}: {rej.detail} ({rej.code})
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {day.items && day.items.length > 0 ? (
                <ol className="itinerary-list space-y-1.5">
                  {day.items.map((item, j) => (
                    <li key={j} className="flex flex-col gap-1 pb-2">
                      {item.travel_from_previous && (
                        <div className="text-xs text-text-muted mb-1 pl-2 border-l border-dashed border-border py-1" data-testid={`travel-${j}`}>
                          ↳ Travel: {item.travel_from_previous.duration_min} min ({item.travel_from_previous.status}) via {item.travel_from_previous.source}
                        </div>
                      )}
                      <div className="flex items-center gap-2 text-sm">
                        <span className="text-text font-medium">{item.name || item.poi_id}</span>
                        {item.category && (
                          <span className="text-xs text-text-muted uppercase tracking-wider border px-1 rounded-sm">{item.category}</span>
                        )}
                        {item.start_hint && (
                          <span className="text-xs text-text-muted">({item.start_hint})</span>
                        )}
                        {item.evidence && (
                          <span data-testid="evidence-badge">
                            <TrustChip
                              variant={item.evidence.needs_verification ? "needs-verification" : "verified"}
                              label={item.evidence.needs_verification ? "Needs verification" : item.evidence.status}
                            />
                          </span>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
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
