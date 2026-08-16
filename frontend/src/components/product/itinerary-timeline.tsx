"use client";

import React, { useState } from "react";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, CreditCard, GripVertical, Trash2 } from "lucide-react";
import type { DraftItineraryOutput, LineAssignment, MoveItem, RemoveItem, ReorderDay } from "@/lib/api/types.gen";
import { TrustChip } from "./trust-chip";

interface ItineraryTimelineProps {
  itinerary: DraftItineraryOutput;
  assignments?: LineAssignment[];
  onEdit?: (edit: ({ op: "move_item" } & MoveItem) | ({ op: "remove_item" } & RemoveItem) | ({ op: "reorder_day" } & ReorderDay)) => void;
  isRecomputing?: boolean;
}

export function ItineraryTimeline({ itinerary, assignments, onEdit, isRecomputing }: ItineraryTimelineProps) {
  const [draggedItem, setDraggedItem] = useState<{ poi_id: string; day_index: number; item_index: number } | null>(null);

  const handleDragStart = (e: React.DragEvent, poi_id: string, day_index: number, item_index: number) => {
    setDraggedItem({ poi_id, day_index, item_index });
    e.dataTransfer.setData("text/plain", JSON.stringify({ poi_id, day_index, item_index }));
    e.dataTransfer.effectAllowed = "move";
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };

  const handleDropOnDay = (e: React.DragEvent, targetDayIndex: number, targetPosition: number) => {
    e.preventDefault();
    if (!draggedItem || !onEdit) return;

    if (draggedItem.day_index === targetDayIndex && draggedItem.item_index === targetPosition) {
      setDraggedItem(null);
      return;
    }

    onEdit({
      op: "move_item",
      poi_id: draggedItem.poi_id,
      from_day_index: draggedItem.day_index,
      to_day_index: targetDayIndex,
      position: targetPosition,
    });
    setDraggedItem(null);
  };

  const handleMoveWithinDay = (dayIndex: number, itemIndex: number, direction: "up" | "down") => {
    if (!onEdit) return;
    const day = itinerary.days[dayIndex];
    if (!day || !day.items) return;
    const targetIndex = direction === "up" ? itemIndex - 1 : itemIndex + 1;
    if (targetIndex < 0 || targetIndex >= day.items.length) return;

    const item = day.items[itemIndex];
    if (!item) return;

    onEdit({
      op: "move_item",
      poi_id: item.poi_id,
      from_day_index: dayIndex,
      to_day_index: dayIndex,
      position: targetIndex,
    });
  };

  const handleMoveBetweenDays = (fromDayIndex: number, itemIndex: number, direction: "prev" | "next") => {
    if (!onEdit) return;
    const toDayIndex = direction === "prev" ? fromDayIndex - 1 : fromDayIndex + 1;
    if (toDayIndex < 0 || toDayIndex >= itinerary.days.length) return;

    const sourceDay = itinerary.days[fromDayIndex];
    const targetDay = itinerary.days[toDayIndex];
    if (!sourceDay?.items || !targetDay) return;

    const item = sourceDay.items[itemIndex];
    if (!item) return;

    const targetPos = targetDay.items?.length ?? 0;
    onEdit({
      op: "move_item",
      poi_id: item.poi_id,
      from_day_index: fromDayIndex,
      to_day_index: toDayIndex,
      position: targetPos,
    });
  };

  const handleRemove = (dayIndex: number, itemIndex: number) => {
    if (!onEdit) return;
    const day = itinerary.days[dayIndex];
    if (!day?.items) return;
    const item = day.items[itemIndex];
    if (!item) return;

    onEdit({
      op: "remove_item",
      poi_id: item.poi_id,
      day_index: dayIndex,
    });
  };

  return (
    <div className="relative">
      {itinerary.itinerary_quality === "fallback" && (
        <div className="mb-4">
          <TrustChip variant="warning" label="Best-effort itinerary — review before booking" />
        </div>
      )}

      {isRecomputing && (
        <div className="mb-3 p-2 bg-surface border border-border rounded-sm text-xs font-mono text-text-muted animate-pulse flex items-center justify-between">
          <span>Recomputing budget & payment strategy...</span>
        </div>
      )}

      <div className="relative">
        <div className="absolute left-3.5 top-2 bottom-2 w-0.5 bg-border" />
        <div className="space-y-6">
          {itinerary.days.map((day, i) => (
            <div
              key={i}
              className="relative pl-10"
              onDragOver={handleDragOver}
              onDrop={(e) => handleDropOnDay(e, i, day.items?.length ?? 0)}
            >
              <div className="absolute left-0 top-1.5 w-7 h-7 rounded-full bg-surface border border-border flex items-center justify-center">
                <span className="text-xs font-mono tabular-nums text-text-muted">{i + 1}</span>
              </div>
              <div className="text-xs text-text-muted font-mono mb-1">{day.date}</div>

              {day.unmet_needs && day.unmet_needs.length > 0 && (
                <div className="mb-2" data-testid="day-unmet">
                  <span className="text-xs font-semibold text-warning-text uppercase tracking-wider">Unmet needs</span>
                  <ul className="text-sm mt-0.5 space-y-0.5">
                    {day.unmet_needs.map((need, idx) => (
                      <li key={idx} className="text-text-muted">
                        - {need}
                      </li>
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
                <ol className="itinerary-list space-y-2">
                  {day.items.map((item, j) => {
                    const assignment = assignments?.find(
                      (a) => a.line.id === item.poi_id || a.line.id === `poi:${item.poi_id}`
                    );

                    return (
                      <li
                        key={item.poi_id || j}
                        draggable={Boolean(onEdit)}
                        onDragStart={(e) => handleDragStart(e, item.poi_id, i, j)}
                        onDragOver={handleDragOver}
                        onDrop={(e) => {
                          e.stopPropagation();
                          handleDropOnDay(e, i, j);
                        }}
                        className="flex flex-col gap-1 p-2 rounded-sm border border-border/60 bg-surface/50 hover:bg-surface transition-colors"
                      >
                        {item.travel_from_previous && (
                          <div
                            className="text-xs text-text-muted mb-1 pl-2 border-l border-dashed border-border py-0.5"
                            data-testid={`travel-${j}`}
                          >
                            ↳ Travel: {item.travel_from_previous.duration_min} min ({item.travel_from_previous.status}) via {item.travel_from_previous.source}
                          </div>
                        )}
                        <div className="flex items-center justify-between gap-2 flex-wrap text-sm">
                          <div className="flex items-center gap-2 flex-wrap">
                            {onEdit && (
                              <span className="cursor-grab active:cursor-grabbing text-text-muted p-0.5" title="Drag to reorder or move across days">
                                <GripVertical className="w-3.5 h-3.5" />
                              </span>
                            )}
                            <span className="text-text font-medium">{item.name || item.poi_id}</span>
                            {item.category && (
                              <span className="text-[11px] text-text-muted uppercase tracking-wider border border-border px-1 rounded-sm">
                                {item.category}
                              </span>
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
                            {assignment && (
                              <span
                                data-testid="card-badge"
                                className="inline-flex items-center gap-1 text-[11px] font-mono font-medium px-1.5 py-0.5 rounded-sm bg-accent-1/10 text-accent-1 border border-accent-1/30"
                                title={`Optimized card: ${assignment.card_id}`}
                              >
                                <CreditCard className="w-3 h-3" />
                                <span>{assignment.card_id}</span>
                              </span>
                            )}
                          </div>

                          {onEdit && (
                            <div className="flex items-center gap-1 shrink-0 ml-auto">
                              {j > 0 && (
                                <button
                                  type="button"
                                  onClick={() => handleMoveWithinDay(i, j, "up")}
                                  className="p-1 rounded text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
                                  aria-label={`Move ${item.name || item.poi_id} up`}
                                  title="Move up"
                                >
                                  <ArrowUp className="w-3.5 h-3.5" />
                                </button>
                              )}
                              {day.items && j < day.items.length - 1 && (
                                <button
                                  type="button"
                                  onClick={() => handleMoveWithinDay(i, j, "down")}
                                  className="p-1 rounded text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
                                  aria-label={`Move ${item.name || item.poi_id} down`}
                                  title="Move down"
                                >
                                  <ArrowDown className="w-3.5 h-3.5" />
                                </button>
                              )}
                              {i > 0 && (
                                <button
                                  type="button"
                                  onClick={() => handleMoveBetweenDays(i, j, "prev")}
                                  className="p-1 rounded text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
                                  aria-label={`Move ${item.name || item.poi_id} to day ${i}`}
                                  title={`Move to day ${i}`}
                                >
                                  <ChevronLeft className="w-3.5 h-3.5" />
                                </button>
                              )}
                              {i < itinerary.days.length - 1 && (
                                <button
                                  type="button"
                                  onClick={() => handleMoveBetweenDays(i, j, "next")}
                                  className="p-1 rounded text-text-muted hover:text-text hover:bg-surface-elevated transition-colors"
                                  aria-label={`Move ${item.name || item.poi_id} to day ${i + 2}`}
                                  title={`Move to day ${i + 2}`}
                                >
                                  <ChevronRight className="w-3.5 h-3.5" />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => handleRemove(i, j)}
                                className="p-1 rounded text-error-text hover:bg-error-surface/40 transition-colors"
                                aria-label={`Remove ${item.name || item.poi_id}`}
                                title="Remove item"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          )}
                        </div>
                      </li>
                    );
                  })}
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
