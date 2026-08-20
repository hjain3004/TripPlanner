"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as MaplibreMap } from "maplibre-gl";
import type { DraftItineraryOutput as DraftItinerary, ItineraryDayOutput } from "@/lib/api";

const REGION_CENTROIDS: Record<string, { lat: number; lng: number }> = {
  SIN: { lat: 1.3521, lng: 103.8198 },
  BOM: { lat: 19.076, lng: 72.8777 },
  DXB: { lat: 25.2048, lng: 55.2708 },
  NYC: { lat: 40.7128, lng: -74.006 },
  LON: { lat: 51.5074, lng: -0.1278 },
  PAR: { lat: 48.8566, lng: 2.3522 },
};

interface TripMapProps {
  destination?: string;
  mapData?: {
    origin?: { lat: number; lng: number };
    destination: { lat: number; lng: number };
  };
  label?: string;
  itinerary?: DraftItinerary;
}

export function TripMap({ destination, mapData, itinerary }: TripMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [loadError, setLoadError] = useState(false);

  // Extract all plotted POIs with real catalog coordinates
  const validPoints: {
    poi_id: string;
    name: string;
    lat: number;
    lon: number;
    dayIndex: number;
    itemIndex: number;
  }[] = [];

  if (itinerary?.days) {
    itinerary.days.forEach((day: ItineraryDayOutput, dayIndex: number) => {
      if (day.items) {
        day.items.forEach((item, itemIndex) => {
          if (item.lat != null && item.lon != null) {
            validPoints.push({
              poi_id: item.poi_id,
              name: item.name || item.poi_id,
              lat: item.lat,
              lon: item.lon,
              dayIndex,
              itemIndex,
            });
          }
        });
      }
    });
  }

  const destCentroid =
    (destination ? REGION_CENTROIDS[destination.toUpperCase()] : undefined) ||
    mapData?.destination || { lat: 1.3521, lng: 103.8198 };

  const pointsKey = validPoints.map((p) => `${p.poi_id}:${p.lat}:${p.lon}`).join("|");

  useEffect(() => {
    let map: MaplibreMap | null = null;

    if (validPoints.length === 0) {
      return;
    }

    const init = async () => {
      try {
        const maplibregl = await import("maplibre-gl");
        if (!containerRef.current) return;

        const centerLng = validPoints[0]?.lon ?? destCentroid.lng;
        const centerLat = validPoints[0]?.lat ?? destCentroid.lat;

        const m = new maplibregl.Map({
          container: containerRef.current,
          style: "https://tiles.openfreemap.org/styles/liberty",
          center: [centerLng, centerLat],
          zoom: 12,
          attributionControl: false,
        });

        m.addControl(new maplibregl.NavigationControl(), "top-right");

        // Plot real coordinates without fake offsets
        validPoints.forEach((point) => {
          const el = document.createElement("div");
          el.className = "custom-map-marker";
          /* token-lint-disable-next-line no-color-literals -- MapLibre DOM marker styles */
          el.style.backgroundColor = "#173A34";
          /* token-lint-disable-next-line no-color-literals -- MapLibre DOM marker styles */
          el.style.color = "#ffffff";
          el.style.borderRadius = "9999px";
          el.style.padding = "2px 6px";
          el.style.fontSize = "11px";
          el.style.fontFamily = "monospace";
          el.style.fontWeight = "bold";
          /* token-lint-disable-next-line no-color-literals -- MapLibre DOM marker styles */
          el.style.border = "2px solid #ffffff";
          /* token-lint-disable-next-line no-color-literals -- MapLibre DOM marker styles */
          el.style.boxShadow = "0 2px 4px rgba(0,0,0,0.25)";
          el.innerText = `D${point.dayIndex + 1}:${point.itemIndex + 1}`;

          new maplibregl.Marker({ element: el })
            .setLngLat([point.lon, point.lat])
            .addTo(m);
        });

        if (validPoints.length > 1) {
          const bounds = new maplibregl.LngLatBounds();
          validPoints.forEach((p) => bounds.extend([p.lon, p.lat]));
          m.fitBounds(bounds, { padding: 40, maxZoom: 14 });
        }

        map = m;
      } catch {
        setLoadError(true);
      }
    };

    init();

    return () => {
      map?.remove();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointsKey, destCentroid.lat, destCentroid.lng]);

  if (loadError) {
    return (
      <div className="aspect-video bg-accent-2 rounded-none flex items-center justify-center text-sm text-text-muted shadow-1">
        Map unavailable — check your connection
      </div>
    );
  }

  if (validPoints.length === 0) {
    return (
      <div className="aspect-video bg-surface rounded-none border border-border flex items-center justify-center p-6 text-center text-sm text-text-muted">
        Map unavailable for these activities.
      </div>
    );
  }

  return (
    <div className="aspect-video relative overflow-hidden rounded-none border-2 border-border shadow-1">
      {/* `inert` accessibility isolation */}
      <div
        ref={containerRef}
        className="absolute inset-0 w-full h-full"
        data-testid="map-container"
        inert
      />
    </div>
  );
}
