"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as MaplibreMap } from "maplibre-gl";
import type { DraftItineraryOutput as DraftItinerary, ItineraryDayOutput } from "@/lib/api/types.gen";

interface TripMapProps {
  mapData: {
    origin: { lat: number; lng: number };
    destination: { lat: number; lng: number };
  };
  label?: string;
  itinerary?: DraftItinerary;
}

export function TripMap({ mapData, itinerary }: TripMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    let map: MaplibreMap | null = null;

    const init = async () => {
      try {
        const maplibregl = await import("maplibre-gl");
        if (!containerRef.current) return;

        const m = new maplibregl.Map({
          container: containerRef.current,
          style: "https://tiles.openfreemap.org/styles/liberty",
          center: [mapData.destination.lng, mapData.destination.lat],
          zoom: 10,
          attributionControl: false,
        });

        m.addControl(new maplibregl.NavigationControl(), "top-right");

        // Calculate total items
        let totalItems = 0;
        if (itinerary?.days) {
          itinerary.days.forEach((day: ItineraryDayOutput) => {
            if (day.items) {
              totalItems += day.items.length;
            }
          });
        }

        if (totalItems > 0) {
          for (let i = 0; i < totalItems; i++) {
            /* token-lint-disable-next-line no-color-literals -- maplibregl requires hex strings */
            new maplibregl.Marker({ color: "#173A34" })
              .setLngLat([mapData.destination.lng + i * 0.01, mapData.destination.lat + i * 0.01])
              .addTo(m);
          }
        } else {
          /* token-lint-disable-next-line no-color-literals -- maplibregl requires hex strings */
          new maplibregl.Marker({ color: "#173A34" })
            .setLngLat([mapData.destination.lng, mapData.destination.lat])
            .addTo(m);
        }

        map = m;
        setMounted(true);
      } catch {
        setLoadError(true);
      }
    };

    init();

    return () => {
      map?.remove();
    };
  }, [mapData.destination.lat, mapData.destination.lng, itinerary?.days]);

  if (loadError) {
    return (
      <div className="aspect-video bg-accent-2 rounded-none flex items-center justify-center text-sm text-text-muted shadow-1">
        Map unavailable — check your connection
      </div>
    );
  }

  return (
    <div className="aspect-video relative overflow-hidden rounded-none border-2 border-border shadow-1">
      {/* `inert`, not `aria-hidden`. The itinerary list is the accessible
          equivalent of this map (I6 list parity), so the canvas should not be
          announced - but MapLibre injects its own focusable controls (zoom,
          compass, and a tabindex="0" canvas) into this subtree. aria-hidden
          alone leaves those keyboard-reachable while invisible to screen
          readers, which aXe flags as aria-hidden-focus (serious): a keyboard
          user tabs into controls their screen reader never announced. `inert`
          removes the subtree from the a11y tree AND the tab order together. */}
      <div
        ref={containerRef}
        className="absolute inset-0 w-full h-full"
        data-testid="map-container"
        inert
      />
      {!mounted && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent-2">
          <span className="text-sm text-text-muted">Loading map&hellip;</span>
        </div>
      )}
    </div>
  );
}
