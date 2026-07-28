import React from 'react';
import { CreditCard, PlaneTakeoff } from 'lucide-react';

interface FlightRouteCardProps {
  originCode: string;
  originName: string;
  destCode: string;
  destName: string;
  airline: string;
  flightNumber: string;
  duration: string;
}

export const FlightRouteCard = ({ originCode, originName, destCode, destName, airline, flightNumber, duration }: FlightRouteCardProps) => (
  <div className="relative overflow-hidden rounded-none border border-border bg-bg shadow-1 mt-4">
    <div className="absolute -top-16 -right-16 w-48 h-48 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
    <div className="p-8 relative z-10 grid grid-cols-1 md:grid-cols-[1fr_2fr_1fr] items-center gap-6">
      <div className="text-center md:text-left">
        <div className="text-[40px] font-mono font-medium text-text tracking-tight leading-none">{originCode}</div>
        <div className="text-[11px] font-mono font-medium text-text-muted mt-3 uppercase tracking-[0.16em]">{originName}</div>
      </div>
      <div className="flex flex-col items-center justify-center px-4 w-full">
        <div className="text-[10px] font-mono font-medium text-accent-4 uppercase tracking-[0.16em] mb-4 bg-accent-4/5 border border-accent-4/20 px-3 py-1">{duration}</div>
        <div className="w-full relative flex items-center justify-center h-[1px] bg-border/50">
          <div className="absolute bg-bg px-4 text-primary">
            <PlaneTakeoff className="w-4 h-4" />
          </div>
        </div>
        <div className="text-[13px] font-ui font-medium text-text mt-4 bg-accent-2/30 px-3 py-1.5 rounded-sm border border-border/50">{airline} <span className="text-text-muted ml-1">• {flightNumber}</span></div>
      </div>
      <div className="text-center md:text-right">
        <div className="text-[40px] font-mono font-medium text-text tracking-tight leading-none">{destCode}</div>
        <div className="text-[11px] font-mono font-medium text-text-muted mt-3 uppercase tracking-[0.16em]">{destName}</div>
      </div>
    </div>
  </div>
);