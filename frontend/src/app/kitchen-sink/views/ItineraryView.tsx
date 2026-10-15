"use client";

import React from "react";
import { motion } from "motion/react";
import { Hotel, PlaneTakeoff, Train } from "lucide-react";
import { NotchLabel } from "@/components/product/notch-label";
import { ProvenanceBand } from "@/components/product/provenance-band";
import { MoneyText } from "@/components/product/money-text";
import { FlightRouteCard } from "@/components/product/ItineraryUI";
import { RouteNode } from "@/components/product/route-node";
import { japanVisualFixture } from "@/mocks/japan-visual-fixture";

export const ItineraryView = () => {
  const report = japanVisualFixture.report;
  const flight = report.flights_pick;
  const hotel = report.hotel_pick;
  const flightLine = report.costed_trip.lines.find((line) => line.id === "flight_001");
  const hotelLine = report.costed_trip.lines.find((line) => line.id === "hotel_001");

  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl">
      <header className="mb-12">
        <NotchLabel>Sample itinerary evidence</NotchLabel>
        <h1 className="font-display display-hero text-[56px] leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-text">
          Delhi → Tokyo Preview
        </h1>
        <p className="text-[17px] leading-[1.65] text-text-muted max-w-2xl font-ui">
          Built from the type-valid Japan visual fixture. Prices, award space, and hotel availability are sample data.
        </p>
      </header>

      <div className="max-w-2xl">
        {flight && flightLine && (
          <RouteNode state="done" icon={PlaneTakeoff} label="Sample outbound flight" subtitle="DEL → TYO">
            <FlightRouteCard
              originCode={flight.origin}
              originName="Delhi"
              destCode={flight.destination}
              destName="Tokyo"
              airline={flight.airline}
              flightNumber={flight.id}
              duration="sample itinerary"
            />
            {/* token-lint-disable-next-line no-dead-classes -- arbitrary opacity values compile to direct CSS values, not class names */}
            <div className="mt-4 flex justify-between items-center bg-accent-2/30 p-4 border-l-2 border-primary">
              <span className="text-[13px] font-mono font-medium text-text-muted uppercase tracking-wide">Sample cash quote</span>
              <MoneyText minor={flightLine.amount_minor} currency={flightLine.currency} className="font-ui font-semibold text-primary text-[20px]" />
            </div>
            <ProvenanceBand
              sourceUrl={flight.provenance.source_url ?? undefined}
              lastVerified={flight.provenance.last_verified}
              verifiedBy="sample data · needs verification"
              confidence={flight.provenance.confidence}
            />
          </RouteNode>
        )}

        {hotel && hotelLine && (
          <RouteNode state="current" icon={Hotel} label={hotel.name} subtitle={`${hotel.area} · ${hotel.city}`}>
            <div className="border-2 border-border bg-bg p-5 shadow-1">
              <p className="text-[14px] text-text-muted mb-4 font-ui leading-[1.6]">
                Sample hotel evidence only. Verify rate, taxes, location, cancellation rules, and card benefit eligibility before booking.
              </p>
              <div className="flex justify-between items-center">
                <span className="font-mono text-xs uppercase tracking-wide text-text-muted">Fixture hotel line</span>
                <MoneyText minor={hotelLine.amount_minor} currency={hotelLine.currency} />
              </div>
            </div>
            <ProvenanceBand
              sourceUrl={hotel.provenance.source_url ?? undefined}
              lastVerified={hotel.provenance.last_verified}
              verifiedBy="sample data · needs verification"
              confidence={hotel.provenance.confidence}
            />
          </RouteNode>
        )}

        <RouteNode state="pending" icon={Train} label="Fixture day plan" subtitle="5 sample days · verify locally">
          <div className="border-2 border-border bg-bg p-5 shadow-1 space-y-2">
            {report.itinerary.days.map((day, index) => (
              /* token-lint-disable-next-line no-dead-classes -- border-b-0 only exists under the last: modifier Tailwind emits; not matched by this script's plain-selector class scan */
              <div key={day.date} className="flex items-start justify-between gap-4 border-b border-border last:border-b-0 pb-2 last:pb-0">
                <span className="font-mono text-xs text-text-muted">{day.date}</span>
                <span className="text-sm text-text">Day {index + 1}: {day.items?.[0]?.poi_id ?? "open sample slot"}</span>
              </div>
            ))}
          </div>
        </RouteNode>
      </div>
    </motion.div>
  );
};
