"use client";
import React from 'react';
import { motion } from 'motion/react';
import { PlaneTakeoff, Hotel, Train } from 'lucide-react';
import { NotchLabel, ProvenanceBand, WhyThis, MoneyText } from '../../components/product/SharedUI';
import { RouteNode, FlightRouteCard, DecisionLedger } from '../../components/product/ItineraryUI';

export const ItineraryView = () => (
  <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="max-w-3xl">
    <header className="mb-12">
      <NotchLabel>Curated for your wallet</NotchLabel>
      <h1 className="font-display text-4xl md:text-5xl font-bold leading-tight mt-4 mb-4">Tokyo & Kyoto Escape</h1>
      <p className="text-lg text-muted-foreground max-w-2xl">Optimized for maximum value using your Chase Sapphire Reserve and Amex Gold cards.</p>
    </header>
    
    <div className="max-w-2xl">
      <RouteNode 
        state="done" 
        icon={PlaneTakeoff} 
        title="Outbound Flight" 
        subtitle="JFK → HND • Tue, Oct 12"
      >
        <FlightRouteCard 
          originCode="JFK" originName="New York"
          destCode="HND" destName="Tokyo Haneda"
          airline="ANA First Class"
          flightNumber="NH109"
          duration="14h 20m"
        />
        <div className="mt-4 flex justify-between items-center bg-secondary/30 p-3 rounded-lg border border-border">
           <span className="text-sm font-medium text-muted-foreground">Final Cost</span>
           <div className="text-right">
             <span className="font-bold text-primary text-lg">110,000 pts</span>
             <span className="text-sm text-muted-foreground ml-2">+ <MoneyText amount={11200} /></span>
           </div>
        </div>
        <ProvenanceBand 
          source="Virgin Atlantic Mileage Club" 
          date="Oct 1" 
          verifier="AwardHacker API" 
          confidence={100} 
          state="verified" 
        />
      </RouteNode>

      <RouteNode 
        state="current" 
        icon={Hotel} 
        title="Aman Tokyo" 
        subtitle="4 Nights • Oct 13 - Oct 17"
      >
        <p className="text-sm text-muted-foreground mb-4">
          Pending final booking. Prices have fluctuated slightly since yesterday.
        </p>
        
        <DecisionLedger 
          rows={[
            { card: "Amex Fine Hotels & Resorts", value: 45000, cost: 240000, isChosen: true, notch: "Includes $100 spa credit & breakfast" },
            { card: "Chase Ultimate Rewards", value: 36000, cost: 240000, isChosen: false },
            { card: "Direct Booking (Cash)", value: 0, cost: 285000, isChosen: false }
          ]} 
        />

        <WhyThis title="Why Amex FHR is the best choice here">
          While Chase UR offers a flat 1.5c/pt redemption, Aman Tokyo is part of Amex's Fine Hotels & Resorts program. Booking through FHR triggers your platinum $200 hotel credit, plus provides daily breakfast for two (valued at $90/day) and a $100 property credit, resulting in significantly higher net value despite the same base point cost.
        </WhyThis>

        <ProvenanceBand 
          source="Amex Travel Portal" 
          date="Today, 09:41 AM" 
          confidence={95} 
          state="needs-verification" 
        />
      </RouteNode>

      <RouteNode 
        state="pending" 
        icon={Train} 
        title="Bullet Train to Kyoto" 
        subtitle="Shinkansen Nozomi • Oct 17"
      >
        <FlightRouteCard 
          originCode="TYO" originName="Tokyo Stn"
          destCode="KYO" destName="Kyoto Stn"
          airline="Shinkansen Nozomi"
          flightNumber="Superexpress"
          duration="2h 15m"
        />
      </RouteNode>
    </div>
  </motion.div>
);