"use client";

import React, { useState, useId } from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CreditCard,
  GripVertical,
  Plus,
  Replace,
  Trash2,
} from "lucide-react";
import {
  DndContext,
  DragOverlay,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

import type {
  AddItem,
  DraftItineraryOutput,
  ItineraryItemOutput,
  LineAssignment,
  MoveItem,
  RemoveItem,
  ReorderDay,
  ReplaceItem,
} from "@/lib/api";
import { TrustChip } from "./trust-chip";
import { ActivityPickerDialog } from "./activity-picker-dialog";

const CARD_NAMES: Record<string, string> = {
  "hdfc-infinia": "HDFC Infinia",
  "amex-plat-travel": "Amex Platinum Travel",
  "axis-atlas": "Axis Atlas",
  "icici-emeralde-pvt": "ICICI Emeralde Private",
  "sbi-cashback": "SBI Cashback",
  "axis-magnus": "Axis Magnus",
  "hsbc-travel": "HSBC Travel",
  "standard-chartered-ultimate": "Standard Chartered Ultimate",
};

function getCardLabel(cardId: string): string {
  return CARD_NAMES[cardId] || cardId;
}

interface ItineraryTimelineProps {
  itinerary: DraftItineraryOutput;
  assignments?: LineAssignment[];
  destination?: string;
  onEdit?: (
    edit:
      | ({ op: "move_item" } & MoveItem)
      | ({ op: "remove_item" } & RemoveItem)
      | ({ op: "reorder_day" } & ReorderDay)
      | ({ op: "add_item" } & AddItem)
      | ({ op: "replace_item" } & ReplaceItem)
  ) => void;
  isRecomputing?: boolean;
}

interface SortableTimelineItemProps {
  item: ItineraryItemOutput;
  dayIndex: number;
  itemIndex: number;
  totalDays: number;
  totalItemsInDay: number;
  assignment?: LineAssignment;
  isRecomputing?: boolean;
  onMoveWithinDay: (dayIndex: number, itemIndex: number, direction: "up" | "down") => void;
  onMoveBetweenDays: (fromDayIndex: number, itemIndex: number, direction: "prev" | "next") => void;
  onRemove: (dayIndex: number, itemIndex: number) => void;
  onOpenReplace: (dayIndex: number, poiId: string) => void;
  expandedExplanation: string | null;
  onToggleExplanation: (poiId: string) => void;
}

function SortableTimelineItem({
  item,
  dayIndex,
  itemIndex,
  totalDays,
  totalItemsInDay,
  assignment,
  isRecomputing,
  onMoveWithinDay,
  onMoveBetweenDays,
  onRemove,
  onOpenReplace,
  expandedExplanation,
  onToggleExplanation,
}: SortableTimelineItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: `${dayIndex}:${item.poi_id}`,
    disabled: isRecomputing,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const isExpanded = expandedExplanation === item.poi_id;
  const isPayable = assignment && assignment.line.amount_minor > 0;

  return (
    <li
      ref={setNodeRef}
      style={style}
      className={`flex flex-col gap-1 p-3 rounded border border-border bg-surface transition-all ${
        isDragging ? "opacity-30 border-primary" : ""
      }`}
    >
      {item.travel_from_previous && (
        <div
          className="text-xs text-text-muted mb-1 pl-2 border-l border-dashed border-border py-0.5"
          data-testid={`travel-${itemIndex}`}
        >
          ↳ Travel: {item.travel_from_previous.duration_min} min ({item.travel_from_previous.status}) via{" "}
          {item.travel_from_previous.source}
        </div>
      )}

      <div className="flex items-start justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap flex-1 min-w-0">
          <button
            type="button"
            {...attributes}
            {...listeners}
            disabled={isRecomputing}
            className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center cursor-grab active:cursor-grabbing text-text-muted hover:text-text p-1 -ml-1 rounded focus-visible:outline-none disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label={`Drag handle for ${item.name || item.poi_id}`}
            title="Drag to reorder"
          >
            <GripVertical className="w-4 h-4" />
          </button>

          <span className="text-text font-medium text-sm truncate">{item.name || item.poi_id}</span>

          {item.category && (
            <span className="text-[11px] text-text-muted uppercase tracking-wider border border-border px-1.5 py-0.5 rounded">
              {item.category}
            </span>
          )}

          {item.start_hint && (
            <span className="text-xs text-text-muted font-mono">({item.start_hint})</span>
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

        <div className="flex items-center gap-1 shrink-0 ml-auto flex-wrap">
          {itemIndex > 0 && (
            <button
              type="button"
              disabled={isRecomputing}
              onClick={() => onMoveWithinDay(dayIndex, itemIndex, "up")}
              className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-text-muted hover:text-text hover:bg-surface-raised focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={`Move ${item.name || item.poi_id} up`}
              title="Move up"
            >
              <ArrowUp className="w-4 h-4" />
            </button>
          )}

          {itemIndex < totalItemsInDay - 1 && (
            <button
              type="button"
              disabled={isRecomputing}
              onClick={() => onMoveWithinDay(dayIndex, itemIndex, "down")}
              className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-text-muted hover:text-text hover:bg-surface-raised focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={`Move ${item.name || item.poi_id} down`}
              title="Move down"
            >
              <ArrowDown className="w-4 h-4" />
            </button>
          )}

          {dayIndex > 0 && (
            <button
              type="button"
              disabled={isRecomputing}
              onClick={() => onMoveBetweenDays(dayIndex, itemIndex, "prev")}
              className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-text-muted hover:text-text hover:bg-surface-raised focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={`Move ${item.name || item.poi_id} to day ${dayIndex}`}
              title={`Move to day ${dayIndex}`}
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}

          {dayIndex < totalDays - 1 && (
            <button
              type="button"
              disabled={isRecomputing}
              onClick={() => onMoveBetweenDays(dayIndex, itemIndex, "next")}
              className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-text-muted hover:text-text hover:bg-surface-raised focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              aria-label={`Move ${item.name || item.poi_id} to day ${dayIndex + 2}`}
              title={`Move to day ${dayIndex + 2}`}
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          )}

          <button
            type="button"
            disabled={isRecomputing}
            onClick={() => onOpenReplace(dayIndex, item.poi_id)}
            className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-text-muted hover:text-text hover:bg-surface-raised focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label={`Replace ${item.name || item.poi_id}`}
            title="Replace activity"
          >
            <Replace className="w-4 h-4" />
          </button>

          <button
            type="button"
            disabled={isRecomputing}
            onClick={() => onRemove(dayIndex, itemIndex)}
            className="min-h-[44px] min-w-[44px] inline-flex items-center justify-center p-2 rounded text-danger hover:bg-accent-2 focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            aria-label={`Remove ${item.name || item.poi_id}`}
            title="Remove activity"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </div>

      {isPayable && assignment && (
        <div className="mt-2 pt-2 border-t border-border" data-testid="attached-payment-guidance">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="flex items-center gap-1.5 text-xs text-primary font-medium">
              <CreditCard className="w-3.5 h-3.5 shrink-0" />
              <span data-testid="card-badge">Use {getCardLabel(assignment.card_id)} here</span>
              <span className="text-[11px] font-mono text-text-muted">({assignment.card_id})</span>
            </div>

            <button
              type="button"
              onClick={() => onToggleExplanation(item.poi_id)}
              className="text-xs text-text-muted hover:text-text inline-flex items-center gap-0.5 min-h-[36px] px-2 rounded focus-visible:outline-none cursor-pointer"
              aria-expanded={isExpanded}
              aria-label={`Why use ${getCardLabel(assignment.card_id)} for ${item.name || item.poi_id}`}
            >
              <span>Why this card?</span>
              {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
          </div>

          {isExpanded && (
            <div className="mt-2 p-2.5 rounded bg-surface-raised border border-border text-xs space-y-1.5">
              {(assignment.explanation || []).map((exp, idx) => (
                <p key={idx} className="text-text-muted">
                  • {exp}
                </p>
              ))}
              {assignment.forex_fee_minor > 0 && (
                <p className="text-text-muted font-mono">
                  • Forex fee accounted: ₹{(assignment.forex_fee_minor / 100).toFixed(2)}
                </p>
              )}
              <div className="pt-1">
                <TrustChip variant="verified" label="Optimized via deterministic rules" />
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

export function ItineraryTimeline({
  itinerary,
  assignments,
  destination = "SIN",
  onEdit,
  isRecomputing,
}: ItineraryTimelineProps) {
  const dndContextId = useId();
  const [activeDragId, setActiveDragId] = useState<string | null>(null);
  const [expandedExplanation, setExpandedExplanation] = useState<string | null>(null);

  // Activity Picker Dialog state
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerMode, setPickerMode] = useState<"add" | "replace">("add");
  const [pickerDayIndex, setPickerDayIndex] = useState(0);
  const [pickerReplaceOldPoiId, setPickerReplaceOldPoiId] = useState<string | undefined>(undefined);

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 5 },
    }),
    useSensor(TouchSensor, {
      activationConstraint: { delay: 250, tolerance: 5 },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragStart = (event: DragStartEvent) => {
    setActiveDragId(String(event.active.id));
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveDragId(null);
    if (!over || active.id === over.id || !onEdit) return;

    const [activeDayStr, activePoiId] = String(active.id).split(":");
    const [overDayStr] = String(over.id).split(":");

    const activeDayIdx = parseInt(activeDayStr || "0", 10);
    const overDayIdx = parseInt(overDayStr || "0", 10);

    const targetDay = itinerary.days[overDayIdx];
    if (!targetDay || !targetDay.items) return;

    const targetPos = targetDay.items.findIndex(
      (item) => `${overDayIdx}:${item.poi_id}` === String(over.id)
    );

    if (targetPos === -1) return;

    onEdit({
      op: "move_item",
      poi_id: activePoiId || "",
      from_day_index: activeDayIdx,
      to_day_index: overDayIdx,
      position: targetPos,
    });
  };

  const handleMoveWithinDay = (dayIndex: number, itemIndex: number, direction: "up" | "down") => {
    if (!onEdit) return;
    const day = itinerary.days[dayIndex];
    if (!day?.items) return;
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

  const handleOpenAdd = (dayIndex: number) => {
    setPickerMode("add");
    setPickerDayIndex(dayIndex);
    setPickerReplaceOldPoiId(undefined);
    setPickerOpen(true);
  };

  const handleOpenReplace = (dayIndex: number, oldPoiId: string) => {
    setPickerMode("replace");
    setPickerDayIndex(dayIndex);
    setPickerReplaceOldPoiId(oldPoiId);
    setPickerOpen(true);
  };

  const handlePickerSelect = (selectedPoiId: string) => {
    if (!onEdit) return;

    if (pickerMode === "add") {
      const day = itinerary.days[pickerDayIndex];
      const position = day?.items?.length ?? 0;
      onEdit({
        op: "add_item",
        poi_id: selectedPoiId,
        day_index: pickerDayIndex,
        position,
      });
    } else if (pickerMode === "replace" && pickerReplaceOldPoiId) {
      onEdit({
        op: "replace_item",
        old_poi_id: pickerReplaceOldPoiId,
        new_poi_id: selectedPoiId,
        day_index: pickerDayIndex,
      });
    }
  };

  const toggleExplanation = (poiId: string) => {
    setExpandedExplanation((prev) => (prev === poiId ? null : poiId));
  };

  // Find dragged item for overlay
  let draggedItem: ItineraryItemOutput | null = null;
  if (activeDragId) {
    const [dStr, pId] = activeDragId.split(":");
    const dIdx = parseInt(dStr || "0", 10);
    draggedItem = itinerary.days[dIdx]?.items?.find((it) => it.poi_id === pId) || null;
  }

  return (
    <div className="relative">
      {itinerary.itinerary_quality === "fallback" && (
        <div className="mb-4">
          <TrustChip variant="warning" label="Best-effort itinerary — review before booking" />
        </div>
      )}

      {isRecomputing && (
        <div className="mb-3 p-2.5 bg-surface border border-border rounded text-xs font-mono text-text-muted animate-pulse flex items-center justify-between">
          <span>Recomputing itinerary & payment strategy...</span>
        </div>
      )}

      <DndContext
        id={dndContextId}
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
      >
        <div className="relative">
          <div className="absolute left-3.5 top-2 bottom-2 w-0.5 bg-border" />
          <div className="space-y-6">
            {itinerary.days.map((day, dayIndex) => {
              const sortableIds = (day.items || []).map((item) => `${dayIndex}:${item.poi_id}`);

              return (
                <div key={dayIndex} className="relative pl-10">
                  <div className="absolute left-0 top-1.5 w-7 h-7 rounded-full bg-surface border border-border flex items-center justify-center">
                    <span className="text-xs font-mono tabular-nums text-text-muted">{dayIndex + 1}</span>
                  </div>
                  <div className="text-xs text-text-muted font-mono mb-2">{day.date}</div>

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

                  <SortableContext items={sortableIds} strategy={verticalListSortingStrategy}>
                    {day.items && day.items.length > 0 ? (
                      <ol className="itinerary-list space-y-2.5">
                        {day.items.map((item, itemIndex) => {
                          const assignment = assignments?.find(
                            (a) => a.line.id === item.poi_id || a.line.id === `poi:${item.poi_id}`
                          );

                          return (
                            <SortableTimelineItem
                              key={`${dayIndex}:${item.poi_id}`}
                              item={item}
                              dayIndex={dayIndex}
                              itemIndex={itemIndex}
                              totalDays={itinerary.days.length}
                              totalItemsInDay={day.items?.length ?? 0}
                              assignment={assignment}
                              isRecomputing={isRecomputing}
                              onMoveWithinDay={handleMoveWithinDay}
                              onMoveBetweenDays={handleMoveBetweenDays}
                              onRemove={handleRemove}
                              onOpenReplace={handleOpenReplace}
                              expandedExplanation={expandedExplanation}
                              onToggleExplanation={toggleExplanation}
                            />
                          );
                        })}
                      </ol>
                    ) : (
                      <p className="text-sm text-text-muted italic py-2">Free / unscheduled</p>
                    )}
                  </SortableContext>

                  {onEdit && (
                    <button
                      type="button"
                      disabled={isRecomputing}
                      onClick={() => handleOpenAdd(dayIndex)}
                      className="mt-3 min-h-[44px] w-full border border-dashed border-border rounded text-xs text-text-muted hover:text-text hover:bg-surface-raised flex items-center justify-center gap-1.5 focus-visible:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                      aria-label={`Add activity to day ${dayIndex + 1}`}
                    >
                      <Plus className="w-3.5 h-3.5" />
                      <span>Add activity to Day {dayIndex + 1}</span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>

        <DragOverlay>
          {draggedItem ? (
            <div className="p-3 rounded border border-primary bg-surface shadow-lg opacity-90 text-sm">
              <span className="font-medium text-text">{draggedItem.name || draggedItem.poi_id}</span>
              {draggedItem.category && (
                <span className="ml-2 text-[11px] text-text-muted uppercase tracking-wider border border-border px-1 rounded">
                  {draggedItem.category}
                </span>
              )}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>

      <ActivityPickerDialog
        isOpen={pickerOpen}
        onClose={() => setPickerOpen(false)}
        destination={destination}
        onSelect={handlePickerSelect}
        title={pickerMode === "add" ? `Add Activity to Day ${pickerDayIndex + 1}` : "Replace Activity"}
        currentPoiId={pickerReplaceOldPoiId}
      />
    </div>
  );
}
