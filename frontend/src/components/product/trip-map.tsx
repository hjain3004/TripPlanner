"use client";

import { useEffect, useRef, useState } from "react";
import type { Map as MaplibreMap } from "maplibre-gl";

interface TripMapProps {
  mapData: {
    origin: { lat: number; lng: number };
    destination: { lat: number; lng: number };
  };
  label?: string;
}

export function TripMap({ mapData }: TripMapProps) {
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

        /* token-lint-disable-next-line no-color-literals -- MapLibre JS API needs raw hex; sourced from --color-primary (mangrove), canvas-rendered cannot use Tailwind class */
        new maplibregl.Marker({ color: "#173A34" })
          .setLngLat([mapData.destination.lng, mapData.destination.lat])
          .addTo(m);

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
  }, [mapData.destination.lat, mapData.destination.lng]);

  if (loadError) {
    return (
      <div className="aspect-video bg-accent-2 rounded-none flex items-center justify-center text-sm text-text-muted shadow-1">
        Map unavailable — check your connection
      </div>
    );
  }

  return (
    <div className="aspect-video relative overflow-hidden rounded-none border-2 border-border shadow-1">
      <div ref={containerRef} className="absolute inset-0 w-full h-full" />
      {!mounted && (
        <div className="absolute inset-0 flex items-center justify-center bg-accent-2">
          <span className="text-sm text-text-muted">Loading map&hellip;</span>
        </div>
      )}
    </div>
  );
}
