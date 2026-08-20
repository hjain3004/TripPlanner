
"use client";
import React from "react";
import { motion } from "motion/react";
import { PlaneTakeoff, Hotel } from "lucide-react";
import { NotchLabel } from "@/components/product/notch-label";
import { ProvenanceBand } from "@/components/product/provenance-band";
import { WhyThis } from "@/components/product/why-this";
import { MoneyText } from "@/components/product/money-text";
import { FlightRouteCard } from "@/components/product/ItineraryUI";
import { RouteNode } from "@/components/product/route-node";
import { DecisionLedger } from "@/components/product/decision-ledger";
import fixtures from "@/mocks/fixtures.json";

export const ItineraryView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl">
    <header className="mb-12">
      <NotchLabel>Curated for your wallet</NotchLabel>
      <h1 className="font-display text-[56px] font-semibold leading-[1.05] tracking-[-0.02em] mt-6 mb-6 text-text">
        Delhi & Singapore Escape
      </h1>
      <p className="text-[17px] leading-[1.65] text-text-muted max-w-2xl font-ui">
        Optimized for maximum value using your HDFC Infinia and Amex Platinum cards.
      </p>
    </header>
    
    <div className="max-w-2xl">
      <RouteNode 
        state="done" 
        icon={PlaneTakeoff} 
        label="Outbound Flight" 
        subtitle="DEL → SIN • Tue, Oct 12"
      >
        <FlightRouteCard 
          originCode={fixtures.itinerary.outbound.originCode} originName={fixtures.itinerary.outbound.originName}
          destCode={fixtures.itinerary.outbound.destCode} destName={fixtures.itinerary.outbound.destName}
          airline={fixtures.itinerary.outbound.airline}
          flightNumber={fixtures.itinerary.outbound.flightNumber}
          duration={fixtures.itinerary.outbound.duration}
        />
        <div className="mt-4 flex justify-between items-center bg-accent-2/30 p-4 border-l-2 border-primary">
           <span className="text-[13px] font-mono font-medium text-text-muted uppercase tracking-wide">Final Cost</span>
           <div className="text-right flex items-center justify-end">
             <span className="font-ui font-semibold text-primary text-[20px] tabular-nums">{fixtures.itinerary.outbound.costPoints} pts</span>
             <span className="text-[14px] text-text-muted ml-2 font-ui">+ <MoneyText minor={fixtures.itinerary.outbound.costCash} currency="INR" /></span>
           </div>
        </div>
        <ProvenanceBand 
          sourceUrl={fixtures.itinerary.outbound.provenance.sourceUrl} 
          lastVerified={fixtures.itinerary.outbound.provenance.lastVerified} 
          verifiedBy={fixtures.itinerary.outbound.provenance.verifiedBy} 
          confidence={fixtures.itinerary.outbound.provenance.confidence} 
        />
      </RouteNode>

      <RouteNode 
        state="current" 
        icon={Hotel} 
        label={fixtures.itinerary.hotel.title} 
        subtitle={fixtures.itinerary.hotel.subtitle}
      >
        <p className="text-[14px] text-text-muted mb-4 font-ui leading-[1.6]">
          Pending final booking. Prices have fluctuated slightly since yesterday.
        </p>
        
        <DecisionLedger 
          items={fixtures.itinerary.hotel.ledger.map(row => ({
            id: row.id,
            label: row.label,
            value: row.value,
            cost: <MoneyText minor={row.cost} currency="INR" />,
            dominant: row.dominant,
            notch: row.notch
          }))}
        />

        <WhyThis summary="Why Amex FHR is the best choice here">
          {fixtures.itinerary.hotel.whyThis}
        </WhyThis>

        <ProvenanceBand 
          sourceUrl={fixtures.itinerary.hotel.provenance.sourceUrl} 
          lastVerified={fixtures.itinerary.hotel.provenance.lastVerified} 
          confidence={fixtures.itinerary.hotel.provenance.confidence} 
        />
      </RouteNode>

      <RouteNode 
        state="pending" 
        icon={PlaneTakeoff} 
        label="Return Flight" 
        subtitle="SIN → DEL • Oct 17"
      >
        <FlightRouteCard 
          originCode={fixtures.itinerary.return.originCode} originName={fixtures.itinerary.return.originName}
          destCode={fixtures.itinerary.return.destCode} destName={fixtures.itinerary.return.destName}
          airline={fixtures.itinerary.return.airline}
          flightNumber={fixtures.itinerary.return.flightNumber}
          duration={fixtures.itinerary.return.duration}
        />
      </RouteNode>
    </div>
  </motion.div>
);
