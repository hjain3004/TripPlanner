import React from 'react';
import { CreditCard, PlaneTakeoff } from 'lucide-react';
import { MoneyText } from './SharedUI';

export const FlightRouteCard = ({ originCode, originName, destCode, destName, airline, flightNumber, duration }: any) => (
  <div className="relative overflow-hidden rounded-2xl border border-border bg-card shadow-sm mt-4">
    <div className="absolute -top-16 -right-16 w-48 h-48 bg-primary/5 rounded-full blur-3xl pointer-events-none" />
    <div className="p-6 relative z-10 flex flex-col md:flex-row justify-between items-center gap-6">
      <div className="text-center md:text-left">
        <div className="text-5xl font-display font-bold text-foreground tracking-tighter">{originCode}</div>
        <div className="text-sm font-medium text-muted-foreground mt-1 uppercase tracking-widest">{originName}</div>
      </div>
      <div className="flex-1 w-full flex flex-col items-center px-4 relative">
        <div className="text-xs font-bold text-lacquer uppercase tracking-widest mb-3 bg-lacquer/10 px-3 py-1 rounded-full">{duration}</div>
        <div className="w-full relative flex items-center justify-center h-8">
          <svg className="absolute w-full h-full text-border" preserveAspectRatio="none" viewBox="0 0 100 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
            <path d="M 0 10 Q 12.5 0, 25 10 T 50 10 T 75 10 T 100 10" strokeDasharray="4 4" className="text-primary/40" />
          </svg>
          <div className="absolute bg-background p-2 rounded-full border-2 border-primary text-primary shadow-sm z-10">
            <PlaneTakeoff className="w-4 h-4" />
          </div>
        </div>
        <div className="text-sm font-medium text-foreground mt-3 bg-secondary/50 px-3 py-1 rounded-md">{airline} <span className="text-muted-foreground ml-1">• {flightNumber}</span></div>
      </div>
      <div className="text-center md:text-right">
        <div className="text-5xl font-display font-bold text-foreground tracking-tighter">{destCode}</div>
        <div className="text-sm font-medium text-muted-foreground mt-1 uppercase tracking-widest">{destName}</div>
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
    grid grid-cols-12 gap-4 py-3 px-4 items-center border-b border-border/40 last:border-0
    ${isChosen ? 'bg-accent rounded-md' : 'hover:bg-secondary/50 transition-colors'}
  `}>
    <div className="col-span-5 flex flex-col">
      <span className="font-medium text-foreground flex items-center gap-2">
        <CreditCard className="w-4 h-4 text-muted-foreground" />
        {card}
      </span>
      {notch && (
        <div className="mt-1 pl-2 border-l-2 border-lacquer text-xs text-muted-foreground">{notch}</div>
      )}
    </div>
    <div className="col-span-4 text-right">
      <span className="text-sm text-muted-foreground">Value: </span>
      <MoneyText amount={value} />
    </div>
    <div className="col-span-3 text-right font-medium">
      <MoneyText amount={cost} />
    </div>
  </div>
);

export const DecisionLedger = ({ rows }: { rows: any[] }) => (
  <div className="border border-border rounded-xl bg-card overflow-hidden shadow-sm mt-4">
    <div className="grid grid-cols-12 gap-4 py-2 px-4 bg-secondary/30 border-b border-border text-xs font-semibold text-muted-foreground uppercase tracking-wider">
      <div className="col-span-5">Payment Method</div>
      <div className="col-span-4 text-right">Points Value</div>
      <div className="col-span-3 text-right">Net Cost</div>
    </div>
    <div className="flex flex-col">
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
    done: 'bg-primary border-primary text-primary-foreground shadow-sm',
    current: 'bg-card border-primary text-primary shadow-sm',
    pending: 'bg-card border-border text-muted-foreground',
    warning: 'bg-card border-lacquer text-lacquer'
  };

  return (
    <div className="relative pl-12 pb-12 last:pb-0">
      {/* Decorative vertical timeline connector */}
      <div className="absolute left-[15px] top-10 bottom-[-10px] w-0.5 bg-gradient-to-b from-border to-transparent last:hidden" />
      
      <div className={`absolute left-0 top-1 w-8 h-8 rounded-full border-2 flex items-center justify-center z-10 ${colors[state]}`}>
        <Icon className="w-4 h-4" />
      </div>

      <div className="flex flex-col gap-1">
        <h3 className={`font-display text-xl font-bold ${state === 'pending' ? 'text-muted-foreground' : 'text-foreground'}`}>
          {title}
        </h3>
        <p className="text-sm text-muted-foreground">{subtitle}</p>
      </div>

      {children && (
        <div className="mt-4">
          {children}
        </div>
      )}
    </div>
  );
};