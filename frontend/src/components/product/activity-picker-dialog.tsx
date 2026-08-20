"use client";

import React, { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { TrustChip } from "./trust-chip";
import type { PlaceSearchResult } from "@/lib/api";
import { Search, MapPin, Tag } from "lucide-react";

interface ActivityPickerDialogProps {
  isOpen: boolean;
  onClose: () => void;
  destination: string;
  onSelect: (poiId: string) => void;
  title: string;
  currentPoiId?: string;
}

const CATEGORIES = [
  { value: "all", label: "All" },
  { value: "food", label: "Food" },
  { value: "culture", label: "Culture" },
  { value: "nature", label: "Nature" },
  { value: "attractions", label: "Attractions" },
];

export function ActivityPickerDialog({
  isOpen,
  onClose,
  destination,
  onSelect,
  title,
  currentPoiId,
}: ActivityPickerDialogProps) {
  const [query, setQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [results, setResults] = useState<PlaceSearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const handleClose = () => {
    setQuery("");
    setSelectedCategory("all");
    setResults([]);
    setSearchError(null);
    onClose();
  };

  useEffect(() => {
    if (!isOpen) return;

    const timer = setTimeout(async () => {
      setIsLoading(true);
      setSearchError(null);
      try {
        const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
        const resp = await fetch(`${apiBase}/places/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            destination,
            query,
            category: selectedCategory === "all" ? null : selectedCategory,
            limit: 15,
          }),
        });
        if (!resp.ok) {
          throw new Error(`Search failed (${resp.status}): ${resp.statusText}`);
        }
        const data = await resp.json();
        setResults(data.results || []);
      } catch (err: unknown) {
        setSearchError(err instanceof Error ? err.message : "Failed to search places");
      } finally {
        setIsLoading(false);
      }
    }, 200);

    return () => clearTimeout(timer);
  }, [isOpen, query, selectedCategory, destination]);

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-w-xl max-h-[85vh] flex flex-col p-6 overflow-hidden bg-surface border border-border">
        <DialogHeader>
          <DialogTitle className="font-ui text-h3 text-text font-semibold">{title}</DialogTitle>
        </DialogHeader>

        <div className="space-y-3 my-2">
          <div className="relative">
            <Search className="absolute left-3 top-3 w-4 h-4 text-text-muted" />
            <Input
              type="search"
              placeholder="Search places by name or category..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="pl-9 min-h-[44px] bg-bg border-border text-sm"
              autoFocus
            />
          </div>

          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by category">
            {CATEGORIES.map((cat) => (
              <button
                key={cat.value}
                type="button"
                onClick={() => setSelectedCategory(cat.value)}
                className={`px-3 py-1.5 rounded text-xs font-medium capitalize transition-colors min-h-[36px] cursor-pointer ${
                  selectedCategory === cat.value
                    ? "bg-accent-1 text-text-on-primary"
                    : "bg-surface-raised text-text-muted hover:text-text border border-border"
                }`}
                aria-pressed={selectedCategory === cat.value}
              >
                {cat.label}
              </button>
            ))}
          </div>
        </div>

        {searchError && (
          <div className="p-3 my-2 rounded bg-accent-2 border border-border text-xs text-danger" role="alert">
            {searchError}
          </div>
        )}

        <div className="flex-1 overflow-y-auto space-y-2.5 my-2 pr-1" role="list">
          {isLoading && (
            <div className="py-8 text-center text-xs font-mono text-text-muted animate-pulse">
              Searching local verified places...
            </div>
          )}

          {!isLoading && results.length === 0 && (
            <div className="py-8 text-center text-sm text-text-muted">
              No venues found matching your search in {destination}.
            </div>
          )}

          {!isLoading &&
            results.map((place) => {
              const isCurrent = place.poi_id === currentPoiId;

              return (
                <div
                  key={place.poi_id}
                  role="listitem"
                  className={`p-3.5 rounded border border-border bg-surface flex items-start justify-between gap-3 hover:border-border transition-colors ${
                    isCurrent ? "opacity-60 bg-surface-raised" : ""
                  }`}
                >
                  <div className="space-y-1 flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium text-sm text-text truncate">{place.name}</span>
                      <span className="inline-flex items-center gap-1 text-[11px] uppercase tracking-wider text-text-muted border border-border px-1.5 py-0.5 rounded">
                        <Tag className="w-2.5 h-2.5" />
                        {place.category}
                      </span>
                    </div>

                    {place.area && (
                      <div className="flex items-center gap-1 text-xs text-text-muted">
                        <MapPin className="w-3 h-3 shrink-0" />
                        <span>{place.area}</span>
                      </div>
                    )}

                    <div className="pt-1">
                      <TrustChip
                        variant={place.evidence.needs_verification ? "needs-verification" : "verified"}
                        label={place.evidence.needs_verification ? "Needs verification" : place.evidence.status}
                      />
                    </div>
                  </div>

                  <Button
                    type="button"
                    disabled={isCurrent}
                    onClick={() => {
                      onSelect(place.poi_id);
                      handleClose();
                    }}
                    className="min-h-[44px] min-w-[70px] shrink-0 text-xs font-medium cursor-pointer"
                    aria-label={`Select ${place.name}`}
                  >
                    {isCurrent ? "Current" : "Select"}
                  </Button>
                </div>
              );
            })}
        </div>
      </DialogContent>
    </Dialog>
  );
}
