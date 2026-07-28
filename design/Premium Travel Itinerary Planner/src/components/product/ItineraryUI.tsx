import React from 'react';
import { CreditCard, PlaneTakeoff } from 'lucide-react';
import { MoneyText } from './SharedUI';

export const FlightRouteCard = ({ originCode, originName, destCode, destName, airline, flightNumber, duration }: any) => (
  <div className="relative overflow-hidden rounded-none border border-border bg-card shadow-1 mt-4">
    <div className="absolute -top-16 -right-16 w-48 h-48 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
    <div className="p-8 relative z-10 grid grid-cols-1 md:grid-cols-[1fr_2fr_1fr] items-center gap-6">
      <div className="text-center md:text-left">
        <div className="text-[40px] font-mono font-medium text-foreground tracking-tight leading-none">{originCode}</div>
        <div className="text-[11px] font-mono font-medium text-muted-foreground mt-3 uppercase tracking-[0.16em]">{originName}</div>
      </div>
      <div className="flex flex-col items-center justify-center px-4 w-full">
        <div className="text-[10px] font-mono font-medium text-[var(--color-lacquer)] uppercase tracking-[0.16em] mb-4 bg-[var(--color-lacquer)]/5 border border-[var(--color-lacquer)]/20 px-3 py-1">{duration}</div>
        <div className="w-full relative flex items-center justify-center h-[1px] bg-border/50">
          <div className="absolute bg-card px-4 text-primary">
            <PlaneTakeoff className="w-4 h-4" />
          </div>
        </div>
        <div className="text-[13px] font-ui font-medium text-foreground mt-4 bg-secondary/30 px-3 py-1.5 rounded-sm border border-border/50">{airline} <span className="text-muted-foreground ml-1">• {flightNumber}</span></div>
      </div>
      <div className="text-center md:text-right">
        <div className="text-[40px] font-mono font-medium text-foreground tracking-tight leading-none">{destCode}</div>
        <div className="text-[11px] font-mono font-medium text-muted-foreground mt-3 uppercase tracking-[0.16em]">{destName}</div>
      </div>
    </div>
  </div>
);

export const LedgerRow = ({ 
  card, 
  value, 
  cost, 
  isChosen, 
  notch 
}: { 
  card: string, 
  value: number, 
  cost: number, 
  isChosen?: boolean,
  notch?: string
}) => (
  <div className={`
    relative grid grid-cols-12 md:grid-cols-[2fr_1fr_1fr] gap-4 py-4 px-6 items-center border-b border-border/40 last:border-0 bg-card
    ${isChosen ? 'bg-secondary/50 border-l-[3px] border-l-primary' : 'hover:bg-secondary/30 transition-colors border-l-[3px] border-l-transparent'}
  `}>
    {notch && (
      <span className="absolute -top-[10px] left-[20px] inline-block px-[8px] py-[4px] text-primary-foreground bg-[var(--color-lacquer)] font-mono font-medium text-[9px] uppercase tracking-[.06em] leading-none z-10">
        {notch}
      </span>
    )}
    
    <div className="col-span-12 md:col-span-1 flex flex-col">
      <span className="font-ui font-semibold text-[18px] text-primary flex items-center gap-3">
        <CreditCard className="w-4 h-4 text-muted-foreground" />
        {card}
      </span>
    </div>
    <div className="col-span-6 md:col-span-1 text-right flex flex-col items-end">
      <span className="font-ui font-semibold text-[18px] text-foreground">
        <MoneyText amount={value} />
      </span>
    </div>
    <div className="col-span-6 md:col-span-1 text-right flex flex-col items-end">
      <span className="font-ui font-semibold text-[18px] text-primary">
        <MoneyText amount={cost} />
      </span>
    </div>
  </div>
);

export const DecisionLedger = ({ rows }: { rows: any[] }) => (
  <div className="border border-border rounded-none bg-card overflow-hidden shadow-1 mt-6">
    <div className="hidden md:grid grid-cols-[2fr_1fr_1fr] gap-4 py-3 px-6 bg-secondary/30 border-b border-border text-[10px] font-mono font-medium text-muted-foreground uppercase tracking-wider">
      <div className="pl-1">Payment Method</div>
      <div className="text-right pr-1">Points Value</div>
      <div className="text-right pr-1">Net Cost</div>
    </div>
    <div className="flex flex-col bg-card">
      {rows.map((row, i) => <LedgerRow key={i} {...row} />)}
    </div>
  </div>
);

export const RouteNode = ({ 
  state, 
  icon: Icon, 
  title, 
  subtitle, 
  children 
}: { 
  state: 'done' | 'current' | 'pending' | 'warning', 
  icon: any, 
  title: string, 
  subtitle: string,
  children?: React.ReactNode 
}) => {
  const colors = {
    done: 'bg-primary border-primary text-primary-foreground shadow-1',
    current: 'bg-card border-primary text-primary shadow-1',
    pending: 'bg-card border-border text-muted-foreground',
    warning: 'bg-card border-[var(--color-lacquer)] text-[var(--color-lacquer)]'
  };

  return (
    <div className="relative pl-[44px] pb-14 last:pb-0">
      {/* Structural Timeline Connector 
          w-8 is 32px. Center is 16px. 
          left-[15px] w-[2px] is perfectly centered. 
      */}
      <div className="absolute left-[15px] top-10 bottom-0 w-[2px] bg-border last:hidden" />
      
      <div className={`absolute left-0 top-1 w-[32px] h-[32px] rounded-none border-[2px] flex items-center justify-center z-10 ${colors[state]}`}>
        <Icon className="w-4 h-4" />
      </div>

      <div className="flex flex-col gap-1">
        <h3 className={`font-ui text-[24px] font-semibold leading-[1.15] tracking-[-0.005em] ${state === 'pending' ? 'text-muted-foreground' : 'text-primary'}`}>
          {title}
        </h3>
        <p className="text-[14px] text-muted-foreground font-ui">{subtitle}</p>
      </div>

      {children && (
        <div className="mt-5">
          {children}
        </div>
      )}
    </div>
  );
};
